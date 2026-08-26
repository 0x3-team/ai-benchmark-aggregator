"""Deterministic SQLite statement-counter tests for the bounded review-queue page.

Acceptance is *statement/scanned counts*, never wall-clock timing.  A review
page must use a constant, bounded number of ``SELECT``s independent of window
size and of how many rows happen to be eligible; cursor pagination must be
stable and duplicate-free even across equal ``created_at`` values; invalid
review chains must still be included (fail-closed); a sparse page must advance
via a continuation rather than scanning unboundedly; and a 10,000-claim bounded
window fixture must hold the same bounded statement count.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.db import models, repositories as repo
from app.db.engine import get_session

BENCHMARK_ID = "hf_official_benchmarks"
FIXTURE_SOURCE_ID = "fake_local_fixture"


class StatementCounter:
    """Count every SELECT executed on an engine between construction/detach."""

    def __init__(self, engine) -> None:
        self.selects: list[str] = []
        self._engine = engine
        event.listen(engine, "before_cursor_execute", self._on_execute)

    def _on_execute(self, conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
        self.selects.append(str(statement))

    @property
    def select_count(self) -> int:
        return len(self.selects)

    def detach(self) -> None:
        event.remove(self._engine, "before_cursor_execute", self._on_execute)


def _fingerprint(i: int) -> str:
    return hashlib.sha256(f"perf-claim-{i}".encode()).hexdigest()


def create_claims(
    session: Session,
    n_claims: int,
    *,
    source_revision_id: str,
    official_source_id: str,
    all_needs_review: bool = False,
    resolved_model_ids: set[int] | None = None,
) -> None:
    """Insert ``n_claims`` ResultClaim rows sharing one snapshot + certified decision.

    snapshot must have a certified effective decision so the admission guard
    passes.  When ``resolved_model_ids`` is given, the claim at that index is
    given a real resolved ``model_entity_id`` (and a ``parser_verified`` status)
    so it is NOT queue-eligible — a genuinely sparse mix for exercising
    continuation without unbounded scans.
    """
    resolved_model_ids = resolved_model_ids or set()
    # Real ModelEntity rows so the FK on result_claims.model_entity_id resolves.
    for midx in sorted(resolved_model_ids):
        if session.get(models.ModelEntity, f"resolved-model-{midx}") is None:
            session.add(
                models.ModelEntity(
                    id=f"resolved-model-{midx}",
                    canonical_name=f"resolved-model-{midx}",
                    display_name=f"Resolved model {midx}",
                    entity_type="model",
                )
            )
    if resolved_model_ids:
        session.flush()
    snapshot = repo.insert_snapshot(
        session,
        official_source_id=official_source_id,
        source_revision_id=source_revision_id,
        raw_content_uri=f"file:///perf-snapshot-{n_claims}.json",
        content_hash=hashlib.sha256(f"perf-{n_claims}".encode()).hexdigest(),
        content_type="application/json",
        http_status=200,
        etag=None,
        last_modified_header=None,
        fetch_metadata={"fixture": True, "perf": True},
        parser_version="perf-v1",
    )
    session.flush()
    decision_id = _certified_leaf_decision(session, source_revision_id)
    for i in range(n_claims):
        resolved = i in resolved_model_ids
        claim = models.ResultClaim(
            source_snapshot_id=snapshot.id,
            source_revision_decision_id=decision_id,
            official_source_id=official_source_id,
            benchmark_id=BENCHMARK_ID,
            model_entity_id=f"resolved-model-{i}" if resolved else None,
            model_raw=f"Perf-Model-{i}",
            benchmark_raw="Perf benchmark",
            score_raw=f"{i % 100}.00",
            score_numeric=float(i % 100),
            score_unit="percent",
            evidence_location={"type": "json_path_v1", "fields": {}},
            capture_method="fake",
            capture_confidence=1.0,
            capture_status=(
                "parser_verified"
                if (resolved or (not all_needs_review and i % 3 != 0))
                else "needs_review"
            ),
            scientific_status="unknown",
            officialness_level="O5",
            claim_fingerprint=_fingerprint(i),
        )
        session.add(claim)
    session.flush()


def _certified_leaf_decision(session: Session, source_revision_id: str) -> str:
    """Return the single effective certified decision for a source revision."""
    decisions = list(
        session.scalars(
            select(models.SourceRevisionDecision).where(
                models.SourceRevisionDecision.source_revision_id == source_revision_id
            )
        )
    )
    superseded = {
        d.supersedes_decision_id
        for d in decisions
        if d.supersedes_decision_id is not None
    }
    leaves = [d for d in decisions if d.id not in superseded]
    if len(leaves) == 1 and leaves[0].outcome == "certified":
        return leaves[0].id
    prior = leaves[0] if leaves else None
    decision = models.SourceRevisionDecision(
        source_revision_id=source_revision_id,
        outcome="certified",
        policy_version="perf-fixture-v1",
        reason_code="perf_fixture_bypass",
        basis_json={"test_fixture": True},
        actor="pytest",
        supersedes_decision_id=prior.id if prior is not None else None,
    )
    session.add(decision)
    session.flush()
    return decision.id


def _current_source_revision_id(session: Session) -> str:
    return repo.get_current_source_revision(session, FIXTURE_SOURCE_ID).id


def _prepare_claims(session: Session, n_claims: int) -> None:
    create_claims(
        session,
        n_claims,
        source_revision_id=_current_source_revision_id(session),
        official_source_id=FIXTURE_SOURCE_ID,
    )


def _prepare_claims_eligible(session: Session, *, n_claims: int, eligible_every: int) -> None:
    """Insert claims where every ``eligible_every``-th index is queue-eligible.

    Indices ``i % eligible_every != 0`` get a resolved model identity, so they
    are NOT queue-eligible (genuinely sparse); the rest are eligible.
    """
    resolved = {i for i in range(n_claims) if i % eligible_every != 0}
    create_claims(
        session,
        n_claims,
        source_revision_id=_current_source_revision_id(session),
        official_source_id=FIXTURE_SOURCE_ID,
        resolved_model_ids=resolved,
    )


def _page_counts(session: Session, limit: int = 7) -> tuple[int, repo.ReviewQueuePage]:
    """Run one page and return (SELECT count, page) with the counter attached only here."""
    from app.db.engine import _engine

    counter = StatementCounter(_engine)
    try:
        page = repo.list_review_queue_page(session, limit=limit)
    finally:
        counter.detach()
    return counter.select_count, page


@pytest.fixture
def seeded_perf_db(seeded_db):
    yield


def test_page_uses_two_constant_selects_independent_of_window_size(seeded_perf_db):
    """A page issues exactly 2 SELECTs (claim window + grouped decisions)."""
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        _prepare_claims(session, 500)
        count_small, page_small = _page_counts(session, limit=10)
        assert count_small == 2, f"expected 2 SELECTs, got {count_small}"
        assert page_small.scanned == 10
        assert len(page_small.items) <= 10
        assert page_small.exhausted is False


def test_10k_window_holds_bounded_selects(seeded_perf_db):
    """A 10,000-claim bounded window uses the same constant 2 SELECTs.

    An exact 10,000-row fixture at the max window fills it completely, so a
    single page is not yet provably exhausted (the queue emits one final empty
    page at the true end, per the documented exact-full semantics); the real
    assertions here are the constant SELECT count and the bounded scanned <=
    limit <= REVIEW_QUEUE_MAX_SCAN.
    """
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        _prepare_claims(session, 10_000)
        counter = StatementCounter(_session_engine(session))
        try:
            page = repo.list_review_queue_page(session, limit=10_000)
        finally:
            counter.detach()
        assert counter.select_count == 2, f"got {counter.select_count} SELECTs for 10k window"
        assert page.scanned == 10_000
        assert page.scanned <= repo.REVIEW_QUEUE_MAX_SCAN
        assert len(page.items) == 10_000
        assert page.projected == 10_000
        assert page.exhausted is False


def test_limit_greater_than_max_is_rejected(seeded_perf_db):
    """A window larger than the documented max fails closed (bounded API)."""
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        with pytest.raises(ValueError, match="maximum of 10000"):
            repo.list_review_queue_page(session, limit=repo.REVIEW_QUEUE_MAX_SCAN + 1)


def _session_engine(session: Session):
    from app.db.engine import _engine

    return session.bind or _engine


def test_window_larger_than_claims_is_exhausted(seeded_perf_db):
    """When rows < scan_limit the page is exhausted with scanned == row count."""
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        _prepare_claims(session, 3)
        count, page = _page_counts(session, limit=10)
        assert count == 2
        assert page.scanned == 3
        assert page.exhausted is True
        assert page.next_cursor is None


def test_pagination_no_duplicates_across_equal_timestamps(seeded_perf_db):
    """Cursor (created_at,id) pagination never re-emits a claim, even at equal created_at."""
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        _prepare_claims(session, 25)
        seen: set[str] = set()
        cursor = None
        pages = 0
        while pages < 50:
            page = repo.list_review_queue_page(session, limit=7, cursor=cursor)
            pages += 1
            for item in page.items:
                assert item.claim.id not in seen, "duplicate claim across pagination"
                seen.add(item.claim.id)
            if page.exhausted:
                break
            assert page.next_cursor is not None
            cursor = page.next_cursor
        assert page.exhausted is True
        assert len(seen) == 25


def test_invalid_review_chain_is_included_fail_closed(seeded_perf_db):
    """A branching (invalid) review chain is included with a chain_error, not dropped.

    The production schema enforces one linear review chain per claim, so a
    genuine branch cannot be written through normal SQL.  The DB here is the
    disposable per-test in-memory SQLite, so we relax only the branch-enforcing
    trigger to prove the in-memory resolver and page keep the documented
    fail-closed contract: an unresolvable chain yields a ``chain_error``
    projection (never a raise) and the page still includes the claim.
    """
    from sqlalchemy import text
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        conn = session.connection()
        conn.execute(text("DROP TRIGGER IF EXISTS trg_claim_review_decisions_linear_insert"))
        conn.execute(text("DROP INDEX IF EXISTS uq_claim_review_root"))
        conn.execute(text("DROP INDEX IF EXISTS uq_claim_review_successor"))
        # Ensure the model referenced by the manual decision exists.
        if session.get(models.ModelEntity, "fake_model_1") is None:
            session.add(
                models.ModelEntity(
                    id="fake_model_1",
                    canonical_name="fake",
                    display_name="fake",
                    entity_type="model",
                )
            )
            session.flush()
        _prepare_claims(session, 5)
        claim_rows = list(session.scalars(select(models.ResultClaim)))
        assert claim_rows
        claim = claim_rows[0]
        repo.append_manual_model_mapping(
            session, result_claim_id=claim.id, model_entity_id="fake_model_1"
        )
        session.flush()
        # Append a sibling leaf with no supersession -> branching -> fail closed.
        session.add(
            models.ClaimReviewDecision(
                result_claim_id=claim.id,
                outcome="identity_resolved",
                reason_code="manual_model_mapping",
                model_entity_id="fake_model_1",
                supersedes_decision_id=None,
            )
        )
        session.flush()
        # Fail-closed public contract: the projection carries chain_error, not a raise.
        projection = repo.get_claim_review_projection(session, claim)
        assert projection.chain_error is not None
        page = repo.list_review_queue_page(session, limit=10)
        ids = [item.claim.id for item in page.items]
        assert claim.id in ids
        item = next(i for i in page.items if i.claim.id == claim.id)
        assert item.projection.chain_error is not None


def test_sparse_page_returns_continuation_without_unbounded_scan(seeded_perf_db):
    """A genuinely sparse page advances via continuation, never an unbounded scan.

    Half the claims carry a resolved model identity (``parser_verified`` +
    non-null ``model_entity_id``), so they are not queue-eligible.  The queue
    window is ``limit`` (same as the output cap), so a page that reads a full
    window but returns a few eligible items still advances; iteration must reach
    exactly the eligible claims and stop, each page projected (and scanned) at
    most ``limit``.
    """
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        _prepare_claims_eligible(session, n_claims=60, eligible_every=2)
        seen: set[str] = set()
        cursor = None
        guard = 0
        while guard < 40:
            guard += 1
            page = repo.list_review_queue_page(session, limit=7, cursor=cursor)
            assert page.scanned <= 7

            for item in page.items:
                assert item.claim.id not in seen
                seen.add(item.claim.id)
                # Every emitted row is genuinely eligible.
                assert (
                    item.projection.chain_error is not None
                    or item.projection.model_entity_id is None
                    or item.claim.capture_status == "needs_review"
                )
            if page.exhausted:
                break
            cursor = page.next_cursor
        assert page.exhausted is True
        assert len(seen) == 30  # exactly the eligible rows, none double-counted


def test_limit_strictly_positive_validation(seeded_perf_db):
    """Non-positive bounds fail closed with a clear error."""
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        with pytest.raises(ValueError, match="limit"):
            repo.list_review_queue_page(session, limit=0)
        with pytest.raises(ValueError, match="limit"):
            repo.list_review_queue_page(session, limit=-1)


def _b64url(payload: dict) -> str:
    import base64
    import json as _json

    raw = _json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _assert_cursor_rejected(cursor: str) -> None:
    """Assert that passing ``cursor`` to the page fails closed with a ValueError."""
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        with pytest.raises(ValueError, match="Invalid review-queue cursor"):
            repo.list_review_queue_page(session, limit=5, cursor=cursor)


def test_invalid_cursor_is_rejected(seeded_perf_db):
    """A malformed cursor token fails closed."""
    _assert_cursor_rejected("not-a-token")


def test_truncated_cursor_is_rejected(seeded_perf_db):
    """Truncating the base64url token (dropping the tail) fails closed."""
    import json

    payload = {"created_at": "2026-08-10 20:59:16", "id": "00000000-0000-0000-0000-000000000001"}
    tok = "v1." + _b64url(payload)
    _assert_cursor_rejected(tok[:-3])  # drop the last chars -> non-canonical length


def test_extra_key_cursor_is_rejected(seeded_perf_db):
    """A token with an extra key is non-canonical and fails closed."""
    payload = {
        "created_at": "2026-08-10 20:59:16",
        "id": "00000000-0000-0000-0000-000000000001",
        "extra": "garbage",
    }
    _assert_cursor_rejected("v1." + _b64url(payload))


def test_invalid_time_cursor_is_rejected(seeded_perf_db):
    """An invalid timestamp (wrong shape/range) fails closed."""
    payload = {"created_at": "not-a-time", "id": "00000000-0000-0000-0000-000000000001"}
    _assert_cursor_rejected("v1." + _b64url(payload))


def test_invalid_id_cursor_is_rejected(seeded_perf_db):
    """An invalid/non-UUID id fails closed."""
    payload = {"created_at": "2026-08-10 20:59:16", "id": "not-a-uuid-xxxxxxxxxxxxx"}
    _assert_cursor_rejected("v1." + _b64url(payload))


def test_noncanonical_uuid_spelling_is_rejected(seeded_perf_db):
    """A 36-char, parseable but non-canonical (uppercase) UUID fails closed.

    ``UUID(claim_id)`` accepts uppercase hex and other spellings; the cursor
    must reject them because ``str(UUID(...)) != claim_id``.
    """
    lower = "01234567-89ab-cdef-0123-456789abcdef"
    payload = {
        "created_at": "2026-08-10 20:59:16",
        "id": lower.upper(),  # 36 chars, parseable UUID, but non-canonical case
    }
    tok = "v1." + _b64url(payload)
    assert len(payload["id"]) == 36
    assert str(uuid.UUID(lower.upper())) == lower  # canonical str() is lowercase, so != payload id
    assert payload["id"] != lower
    _assert_cursor_rejected(tok)


def test_noncanonical_spelling_is_rejected(seeded_perf_db):
    """Two spellings of the same parsed value (extra whitespace) fail closed."""
    import json as _json
    import base64 as _b64

    obj = json.loads('{"created_at": "2026-08-10 20:59:16", "id": "00000000-0000-0000-0000-000000000001"}')
    # Re-serialize with whitespace so the decoded JSON is equivalent-but-not-canonical.
    spaced = _json.dumps(obj, sort_keys=True, indent=2).encode()
    tok = "v1." + _b64.urlsafe_b64encode(spaced).decode().rstrip("=")
    _assert_cursor_rejected(tok)


def test_cursor_roundtrip_and_concurrent_insert_does_not_perturb(seeded_perf_db):
    """A live page's cursor advances; a concurrent newer insert does not disturb it."""
    from app.db.engine import _SessionLocal

    with _SessionLocal() as session:
        _prepare_claims(session, 25)
        original_ids: set[str] = {
            c.id for c in session.scalars(select(models.ResultClaim))
        }
        assert len(original_ids) == 25
        # Take the first page, record its last emitted id + cursor.
        page = repo.list_review_queue_page(session, limit=7)
        assert page.next_cursor is not None
        seen: set[str] = {item.claim.id for item in page.items}
        cursor = page.next_cursor
        # Simulate a concurrent newer insert that lands at the top of ordering.
        _prepare_claims(session, 1)  # newest, but the page already stored its cursor
        concurrent_id = next(
            c.id for c in session.scalars(select(models.ResultClaim)) if c.id not in original_ids
        )
        page2 = repo.list_review_queue_page(session, limit=7, cursor=cursor)
        for item in page2.items:
            assert item.claim.id not in seen, "concurrent insert perturbed continuation"
            seen.add(item.claim.id)
        # Continue draining; never a duplicate, and every original that sorts on
        # this side of the cursor must be emitted (no omission).
        guard = 0
        while not page2.exhausted and guard < 20:
            guard += 1
            cursor = page2.next_cursor
            page2 = repo.list_review_queue_page(session, limit=7, cursor=cursor)
            for item in page2.items:
                assert item.claim.id not in seen, "duplicate claim across pagination"
                seen.add(item.claim.id)
        # No-omission: every one of the 25 originals must appear exactly once,
        # and only the one concurrent insert may additionally appear.  The sweep
        # strictly moves downward on ``(created_at, id)`` from the captured cursor;
        # the concurrent row shares the same wall-clock second (SQLite
        # CURRENT_TIMESTAMP) as the originals, so its random UUID may sort either
        # side of the cursor.  Either way no original is skipped.
        assert original_ids.issubset(seen), "an original claim was omitted by pagination"
        assert seen - original_ids <= {concurrent_id}, "unexpected claims in the sweep"
        assert len(seen) in (25, 26)


def _prepare_claims_at_times(
    session: Session, times: list[datetime],
) -> dict[str, datetime]:
    """Insert queue-eligible claims with explicit distinct created_at datetimes.

    ``times`` are naive UTC datetimes written directly to ``created_at`` so the
    cursor must carry exact microsecond precision.  Returns ``{row.id:
    supplied_datetime}`` so the caller can assert the stored value equals the
    exact datetime supplied — never a second-truncated approximation.
    """
    source_revision_id = _current_source_revision_id(session)
    snapshot = repo.insert_snapshot(
        session,
        official_source_id=FIXTURE_SOURCE_ID,
        source_revision_id=source_revision_id,
        raw_content_uri=f"file:///us-micro-{source_revision_id}.json",
        content_hash=hashlib.sha256(f"us-micro-{source_revision_id}".encode()).hexdigest(),
        content_type="application/json",
        http_status=200,
        etag=None,
        last_modified_header=None,
        fetch_metadata={"fixture": True, "perf": True, "micro": True},
        parser_version="perf-v1",
    )
    session.flush()
    decision_id = _certified_leaf_decision(session, source_revision_id)
    objects: list[tuple[models.ResultClaim, datetime]] = []
    for i, t in enumerate(times):
        claim = models.ResultClaim(
            source_snapshot_id=snapshot.id,
            source_revision_decision_id=decision_id,
            official_source_id=FIXTURE_SOURCE_ID,
            benchmark_id=BENCHMARK_ID,
            model_entity_id=None,
            model_raw=f"UsMicro-Model-{i}",
            benchmark_raw="Perf benchmark",
            score_raw=f"{i}.00",
            score_numeric=float(i),
            score_unit="percent",
            evidence_location={"type": "json_path_v1", "fields": {}},
            capture_method="fake",
            capture_confidence=1.0,
            capture_status="needs_review",  # ensures full-window rows are eligible
            scientific_status="unknown",
            officialness_level="O5",
            claim_fingerprint=_fingerprint(1000 + i),
            created_at=t,
        )
        session.add(claim)
        objects.append((claim, t))
    session.flush()  # assigns id (client default) to each claim
    return {claim.id: t for claim, t in objects}


def test_microsecond_created_at_roundtrip_no_dup_or_omission(seeded_perf_db):
    """Distinct microsecond created_at values page with no duplicate/omission.

    Regression guard for exact cursor precision: if the cursor truncated
    microseconds (e.g. to whole seconds) the ``(created_at, id)`` boundary would
    have to lean on ``id`` alone, and two rows sharing a second but differing in
    microseconds would risk a duplicate or omission. Inserting claims with
    explicitly distinct microsecond ``created_at`` and draining every page must
    emit each id exactly once; and a live cursor must carry the full-precision
    boundary back into the next page.
    """
    import base64
    import json as _json
    from app.db.engine import _SessionLocal

    base = datetime(2026, 8, 10, 12, 0, 0)
    times = [base + timedelta(microseconds=i * 173) for i in range(20)]  # distinct micros
    assert len({t.microsecond for t in times}) == 20  # all distinct microseconds

    with _SessionLocal() as session:
        expected_by_id = _prepare_claims_at_times(session, times)
        assert len(expected_by_id) == 20
        # Descending datetime order (page 1 = the 6 newest, no id tie-break needed
        # since microseconds are strictly decreasing with i).
        desc_ids = [
            c_id for c_id, _ in sorted(
                expected_by_id.items(), key=lambda kv: (kv[1], kv[0]), reverse=True
            )
        ]
        page = repo.list_review_queue_page(session, limit=6)
        assert [item.claim.id for item in page.items] == desc_ids[:6]
        assert page.next_cursor is not None
        first_page_cursor = page.next_cursor
        seen: set[str] = {item.claim.id for item in page.items}
        cursor = first_page_cursor
        guard = 0
        while not page.exhausted and guard < 20:
            guard += 1
            page = repo.list_review_queue_page(session, limit=6, cursor=cursor)
            for item in page.items:
                assert item.claim.id not in seen, "duplicate across microsecond pagination"
                seen.add(item.claim.id)
            if not page.exhausted:
                assert page.next_cursor is not None
                cursor = page.next_cursor
        # No omission, no extras: exactly the 20 inserted ids, each once.
        assert seen == set(expected_by_id)
        # Exact precision survived every cursor: each stored created_at must equal
        # the exact datetime supplied — never a second-truncated approximation.
        stored = {
            c.id: c.created_at
            for c in session.scalars(select(models.ResultClaim))
        }
        assert set(stored) == set(expected_by_id)
        for c_id, expected in expected_by_id.items():
            assert stored[c_id] == expected, (
                f"created_at precision lost for {c_id}: got {stored[c_id]} but "
                f"expected {expected} (cursor must not truncate microseconds)"
            )
        # The first full page's cursor carries the exact microsecond boundary of
        # the 6th-descending (newest index 5) row, not a whole-second truncation.
        boundary = desc_ids[5]
        boundary_raw = expected_by_id[boundary].isoformat(sep=" ")
        first_body = first_page_cursor[len(repo._REVIEW_CURSOR_PREFIX):]
        raw = base64.urlsafe_b64decode(
            first_body + "=" * (-len(first_body) % 4)
        ).decode("utf-8")
        decoded = _json.loads(raw)
        assert decoded["created_at"] == boundary_raw, (
            f"cursor boundary created_at {decoded['created_at']!r} != {boundary_raw!r} "
            "(cursor lost microsecond precision)"
        )
        assert decoded["id"] == boundary
