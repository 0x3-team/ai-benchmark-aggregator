"""F7 regression: official candidate and legacy inventory paths must be bounded
by hard cardinality caps with batch-loaded related rows (no per-claim SELECT).

Every claim must be accounted exactly once under-cap; cap+1 or over-cap
related rows must fail closed before per-claim processing with no partial
artifact; statement counts must not grow per claim; and invalid decision
chains must remain fail-closed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db import models, repositories as repo
from app.db.engine import get_session
from app.export.official_json import (
    FeedCandidateAnalysis,
    analyze_official_feed_candidates,
    project_official_feed,
)
from app.reporting.legacy_inventory import (
    LegacyInventoryError,
    build_legacy_inventory_report,
)
from test_official_feed_projection import (
    _candidate_claim,
    _certified_source,
)


class StatementCounter:
    """Count SELECT statements executed on an engine between construct/detach."""

    def __init__(self, session: Session) -> None:
        self.statements: list[str] = []
        self._engine = session.bind
        event.listen(self._engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        self.statements.append(str(statement))

    def selects(self) -> int:
        return sum(1 for s in self.statements if s.lstrip().upper().startswith("SELECT"))

    def detach(self) -> None:
        event.remove(self._engine, "before_cursor_execute", self._on_execute)


def _seed_claims(session, count: int, *, source_id: str, suffix_base: str) -> None:
    source, revision, certified = _certified_source(session, source_id=source_id)
    for index in range(count):
        _candidate_claim(
            session,
            suffix=f"{suffix_base}-{index}",
            source=source,
            revision=revision,
            certified=certified,
            model_id=f"feed-model-{index % 3}",
        )
    session.commit()


def test_cap_plus_one_claims_fails_closed_before_partial_artifact(
    seeded_db, monkeypatch
):
    """At cap+1 claims, analyze fails closed and no partial artifact is
    produced; the pre-claim-cap check runs before candidate evaluation."""
    import app.export.official_json as oj

    calls = {"eligible": 0}
    real_eligible = oj._eligible_claim_batched

    def _counting_eligible(session, claim):
        calls["eligible"] += 1
        return real_eligible(session, claim)

    with get_session() as session:
        _seed_claims(session, 4, source_id="cap-claims", suffix_base="cap")
        # Force a tiny claim cap for the test: cap=2, load 3 -> fail.
        monkeypatch.setattr(oj, "MAX_CLAIMS", 2)
        monkeypatch.setattr(oj, "_eligible_claim_batched", _counting_eligible)
        with pytest.raises(oj.FeedResourceLimitError, match="claim"):
            analyze_official_feed_candidates(session)
        assert calls["eligible"] == 0, "cap check must precede candidate evaluation"


def test_over_cap_related_rows_fails_closed(seeded_db, monkeypatch):
    """More than cap validations for a claim window fails closed."""
    import app.export.official_json as oj

    with get_session() as session:
        source, revision, certified = _certified_source(
            session, source_id="cap-related"
        )
        claim = _candidate_claim(
            session,
            suffix="rel",
            source=source,
            revision=revision,
            certified=certified,
            validation_outcomes=("pass", "pass"),
        )
        session.commit()
        monkeypatch.setattr(oj, "MAX_RELATED_ROWS", 1)
        with pytest.raises(oj.FeedResourceLimitError, match="related"):
            analyze_official_feed_candidates(session)


def test_legacy_snapshot_cap_fails_closed(seeded_db, monkeypatch):
    """The legacy inventory snapshot cap fails closed before output."""
    import app.reporting.legacy_inventory as li

    with get_session() as session:
        source, revision, certified = _certified_source(
            session, source_id="cap-snapshots"
        )
        _candidate_claim(
            session,
            suffix="snap",
            source=source,
            revision=revision,
            certified=certified,
        )
        session.commit()
        monkeypatch.setattr(li, "MAX_SNAPSHOTS", 0)
        with pytest.raises(LegacyInventoryError, match="snapshot"):
            build_legacy_inventory_report(session)


def test_statement_count_is_flat_across_small_and_larger_same_batch_datasets(
    seeded_db,
):
    """A larger under-cap dataset must not add per-claim SELECTs: the same
    batch load runs a constant number of queries regardless of claim count."""
    with get_session() as session:
        _seed_claims(session, 1, source_id="stmt-small", suffix_base="s")
        small = analyze_official_feed_candidates(session)
        small_count = len(small.eligible_candidates)
    with get_session() as session:
        counter = StatementCounter(session)
        try:
            small_again = analyze_official_feed_candidates(session)
            small_again_count = len(small_again.eligible_candidates)
            small_selects = counter.selects()
        finally:
            counter.detach()

    with get_session() as session:
        _seed_claims(session, 3, source_id="stmt-large", suffix_base="l")
    with get_session() as session:
        counter = StatementCounter(session)
        try:
            large = analyze_official_feed_candidates(session)
            large_count = len(large.eligible_candidates)
            large_selects = counter.selects()
        finally:
            counter.detach()

    assert small_count == 1
    assert small_again_count == 1
    # The large dataset shares the seeded DB with the small set (1 + 3 = 4).
    assert large_count == 4
    # The batch loader is flat: 4-claim and 1-claim windows issue the same
    # number of SELECTs (no per-claim query).
    assert large_selects == small_selects, (
        f"statement count grew per claim: small={small_selects} large={large_selects}"
    )


def test_large_under_cap_fixture_returns_all_rows_deterministically(seeded_db):
    """A larger but under-cap fixture returns every claim, deterministically."""
    with get_session() as session:
        _seed_claims(session, 5, source_id="under-cap", suffix_base="u")
        analysis = analyze_official_feed_candidates(session)
        report = build_legacy_inventory_report(session)
        # Inspect inside the session: the analysis holds ORM rows bound to it.
        assert len(analysis.eligible_candidates) == 5
        assert report["manifest"]["claimCount"] == 5
        ids = [candidate.claim.id for candidate in analysis.eligible_candidates]
        # Deterministic: a second analysis over the same data is identical
        # (eligible_candidates is sorted by cell key then claim id).
        analysis_again = analyze_official_feed_candidates(session)
        ids_again = [candidate.claim.id for candidate in analysis_again.eligible_candidates]
        assert ids == ids_again
        assert len(set(ids)) == 5  # every claim accounted exactly once


def test_invalid_decision_chain_remains_fail_closed(seeded_db, monkeypatch):
    """An invalid review chain still surfaces fail-closed (REVIEW_CHAIN_INVALID),
    and the projection excludes the claim rather than inventing a winner.

    The DB-level append-only trigger prevents creating a genuinely ambiguous
    chain, so the fail-closed path is proven by forcing the pure chain resolver
    to report an invalid chain for one claim.
    """
    import app.export.official_json as oj

    with get_session() as session:
        source, revision, certified = _certified_source(
            session, source_id="bad-chain"
        )
        claim = _candidate_claim(
            session,
            suffix="bad",
            source=source,
            revision=revision,
            certified=certified,
        )
        session.commit()

        real_resolve = repo._resolve_review_chain

        def _broken_resolve(claim_id, decisions):
            if claim_id == claim.id:
                raise repo.ClaimReviewChainError(f"Claim {claim_id} has an invalid chain")
            return real_resolve(claim_id, decisions)

        monkeypatch.setattr(repo, "_resolve_review_chain", _broken_resolve)
        analysis = analyze_official_feed_candidates(session)
        reasons = {row["reasonCode"] for row in analysis.excluded_claims}
        eligible_ids = {candidate.claim.id for candidate in analysis.eligible_candidates}
        claim_id = claim.id
    assert "REVIEW_CHAIN_INVALID" in reasons
    assert claim_id not in eligible_ids


def test_claims_load_uses_sql_limit_mutation_removal_fails(seeded_db, monkeypatch):
    """The claims load must carry an SQL LIMIT.

    Mutation proof: if the LIMIT were removed from the claims SELECT (the
    mutation), a cap+1 dataset would be fully materialized before the
    post-load check.  The test proves the production query carries ``LIMIT``
    (so the mutation would change behavior) and that the cap check still
    fails closed on a cap+1 dataset.
    """
    import app.export.official_json as oj

    captured: list[str] = []
    real_scalars = None

    with get_session() as session:
        _seed_claims(session, 3, source_id="limit-mut", suffix_base="lim")
        session.commit()

        real_scalars = session.scalars

        def _spy(statement, *args, **kwargs):
            captured.append(str(statement))
            return real_scalars(statement, *args, **kwargs)

        monkeypatch.setattr(session, "scalars", _spy)
        monkeypatch.setattr(oj, "MAX_CLAIMS", 2)
        # cap+1 (3 > 2) fails closed even though all rows are loaded by the
        # spy; the SQL LIMIT is what prevents materializing more than cap+1.
        with pytest.raises(oj.FeedResourceLimitError, match="claim"):
            analyze_official_feed_candidates(session)
        claims_statements = [s for s in captured if "FROM result_claims" in s]
        assert claims_statements, "claims load statement not captured"
        # Mutation evidence: removing this LIMIT changes the query and would
        # let a cap+1 dataset materialize fully before the check.
        assert "LIMIT" in claims_statements[0].upper()


def test_reintroducing_a_per_claim_query_breaks_flat_statement_count(seeded_db, monkeypatch):
    """Mutation proof: reintroducing one per-claim query makes the statement
    count grow with the dataset, which the flat-count assertion rejects."""
    import app.export.official_json as oj

    with get_session() as session:
        _seed_claims(session, 1, source_id="mut-small", suffix_base="ms")
        session.commit()
        counter = StatementCounter(session)
        try:
            analyze_official_feed_candidates(session)
            small_selects = counter.selects()
        finally:
            counter.detach()

    with get_session() as session:
        _seed_claims(session, 3, source_id="mut-large", suffix_base="ml")
        session.commit()
        # Mutation: force one extra SELECT per claim inside the evaluator.
        real_eval = oj._eligible_claim_batched

        def _leaky_eval(batch, claim):
            # A genuine per-claim query on a column not identity-mapped.
            session.scalar(
                select(models.ResultClaim.claim_fingerprint).where(
                    models.ResultClaim.id == claim.id
                )
            )
            return real_eval(batch, claim)

        monkeypatch.setattr(oj, "_eligible_claim_batched", _leaky_eval)
        counter = StatementCounter(session)
        try:
            analyze_official_feed_candidates(session)
            large_selects = counter.selects()
        finally:
            counter.detach()

    # The mutation adds a per-claim SELECT (1 small claim vs 4 total large),
    # so the mutated count is strictly greater — proving the flat-count
    # assertion is what rejects a per-claim query regression.
    assert large_selects > small_selects


def test_cli_legacy_inventory_emits_generic_refusal_on_cap_overflow(
    seeded_db, monkeypatch
):
    """The legacy-inventory CLI catches the resource-cap error and emits one
    fixed terminal-safe refusal with exit 2; hostile exception detail is never
    interpolated into the output."""
    from typer.testing import CliRunner

    import app.cli as cli_module
    from app.cli import app
    from app.reporting import legacy_inventory as li

    cli_runner = CliRunner()

    with get_session() as session:
        _seed_claims(session, 1, source_id="cli-cap", suffix_base="cli")
        session.commit()

    hostile_detail = "CAP=250000 table=result_claims host=/private/secret path"
    fixed_refusal = "Legacy inventory refused: report exceeds the bounded resource limits."

    def _refuse(session):
        raise li.LegacyInventoryError(hostile_detail)

    # The CLI calls the name imported into app.cli's namespace.
    monkeypatch.setattr(cli_module, "build_legacy_inventory_report", _refuse)
    result = cli_runner.invoke(app, ["reports", "legacy-inventory"])
    assert result.exit_code == 2
    # Exact fixed output; hostile exception detail absent.
    assert fixed_refusal in result.output
    assert hostile_detail not in result.output
    assert "CAP=250000" not in result.output
    assert "Traceback" not in result.output


def test_related_cap_counts_actual_orm_rows_not_grouped_keys(seeded_db, monkeypatch):
    """The aggregate cap must count ORM rows, never grouped-dictionary keys.

    Many validations on ONE claim (one grouped key, many rows) must trip a
    small cap — R1 counted grouped keys and would have missed this.
    """
    import app.export.official_json as oj

    with get_session() as session:
        source, revision, certified = _certified_source(
            session, source_id="row-count"
        )
        _candidate_claim(
            session,
            suffix="rows",
            source=source,
            revision=revision,
            certified=certified,
            validation_outcomes=("pass",) * 4,
        )
        session.commit()
        monkeypatch.setattr(oj, "MAX_RELATED_ROWS", 3)
        with pytest.raises(oj.FeedResourceLimitError, match="related"):
            analyze_official_feed_candidates(session)


def test_cross_chunk_remaining_budget_is_persistent(seeded_db, monkeypatch):
    """A tiny chunk size must not let a chunk reset the budget; the persistent
    remaining budget fails closed across chunks."""
    import app.export.official_json as oj

    with get_session() as session:
        _seed_claims(session, 2, source_id="chunk-budget", suffix_base="cb")
        session.commit()
        monkeypatch.setattr(oj, "_BATCH_CHUNK", 1)
        monkeypatch.setattr(oj, "MAX_RELATED_ROWS", 4)
        # Each claim carries ~4 related rows (validation, review, publication,
        # source decisions); with chunk=1 and cap=4 the aggregate must fail.
        with pytest.raises(oj.FeedResourceLimitError, match="related"):
            analyze_official_feed_candidates(session)


def test_source_decision_chain_row_overflow_fails_closed(seeded_db, monkeypatch):
    """The source-revision decision chain query is budgeted: over-cap source
    decisions on a revision fail closed."""
    import app.export.official_json as oj

    with get_session() as session:
        source, revision, certified = _certified_source(
            session, source_id="src-decision-cap"
        )
        _candidate_claim(
            session,
            suffix="sd",
            source=source,
            revision=revision,
            certified=certified,
        )
        session.commit()
        monkeypatch.setattr(oj, "MAX_RELATED_ROWS", 0)
        with pytest.raises(oj.FeedResourceLimitError, match="related"):
            analyze_official_feed_candidates(session)


def test_snapshot_cross_chunk_overflow_fails_closed(seeded_db, monkeypatch):
    """The snapshot budget is aggregate across chunks: a tiny chunk plus a tiny
    snapshot cap must fail on the aggregate count."""
    import app.export.official_json as oj

    with get_session() as session:
        _seed_claims(session, 2, source_id="snap-chunk", suffix_base="sc")
        session.commit()
        monkeypatch.setattr(oj, "_BATCH_CHUNK", 1)
        monkeypatch.setattr(oj, "MAX_SNAPSHOTS", 1)
        with pytest.raises(oj.FeedResourceLimitError, match="snapshot"):
            analyze_official_feed_candidates(session)


def test_referenced_source_decision_counted_once_not_twice(seeded_db, monkeypatch):
    """A certified source-revision decision referenced by a claim is loaded
    once (by revision, then not re-queried by exact id) and charged once, so
    an under-cap ledger is not falsely rejected."""
    import app.export.official_json as oj

    with get_session() as session:
        source, revision, certified = _certified_source(
            session, source_id="count-once"
        )
        claim = _candidate_claim(
            session,
            suffix="once",
            source=source,
            revision=revision,
            certified=certified,
        )
        session.commit()
        monkeypatch.setattr(oj, "MAX_RELATED_ROWS", 6)
        # The claim's certified decision + its superseded predecessor + review
        # + publication + validation must fit: under-cap means no raise and the
        # claim is eligible.
        analysis = analyze_official_feed_candidates(session)
        assert any(c.claim.id == claim.id for c in analysis.eligible_candidates)


def test_legacy_inventory_statement_count_is_flat(seeded_db):
    """The legacy inventory path must not issue per-claim SELECTs: a larger
    same-chunk dataset keeps the same SELECT count."""
    with get_session() as session:
        _seed_claims(session, 1, source_id="legacy-flat-s", suffix_base="lfs")
        session.commit()
        counter = StatementCounter(session)
        try:
            build_legacy_inventory_report(session)
            small_selects = counter.selects()
        finally:
            counter.detach()

    with get_session() as session:
        _seed_claims(session, 3, source_id="legacy-flat-l", suffix_base="lfl")
        session.commit()
        counter = StatementCounter(session)
        try:
            build_legacy_inventory_report(session)
            large_selects = counter.selects()
        finally:
            counter.detach()

    assert large_selects == small_selects, (
        f"legacy inventory SELECT count grew per claim: small={small_selects} large={large_selects}"
    )


def test_shared_cap_cannot_be_bypassed_by_prebuilt_batch(seeded_db, monkeypatch):
    """An oversized prebuilt batch must fail closed at the shared claim cap
    even when analyze's own claim-load (and its LIMIT) is bypassed."""
    import app.export.official_json as oj

    with get_session() as session:
        _seed_claims(session, 4, source_id="prebuilt-cap", suffix_base="pb")
        session.commit()
        claims = list(session.scalars(select(models.ResultClaim)))
        monkeypatch.setattr(oj, "MAX_CLAIMS", 2)
        with pytest.raises(oj.FeedResourceLimitError, match="claim"):
            oj.FeedBatch(session, claims)


def test_legacy_route_uses_shared_caps_not_local_duplicates(seeded_db, monkeypatch):
    """The legacy inventory must import the shared caps; monkeypatching the
    shared MAX_CLAIMS is honored by the legacy route (no local duplicate)."""
    import app.export.official_json as oj
    from app.reporting import legacy_inventory as li

    # The legacy module references the imported shared names.
    assert li.MAX_CLAIMS is oj.MAX_CLAIMS
    assert li.MAX_SNAPSHOTS is oj.MAX_SNAPSHOTS

    with get_session() as session:
        _seed_claims(session, 4, source_id="legacy-shared", suffix_base="ls")
        session.commit()
        monkeypatch.setattr(oj, "MAX_CLAIMS", 2)
        with pytest.raises(LegacyInventoryError, match="claim"):
            build_legacy_inventory_report(session)
