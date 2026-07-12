from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from app.config import get_settings
from app.db.engine import get_session, init_db
from app.db import repositories as repo
from app.export.official_json import export_official_json
from app.ingestion.runner import run_ingestion
from app.registry.seed_loader import seed_registry

app = typer.Typer(name="benchmark-ledger", help="Official benchmark result capture ledger", no_args_is_help=True)
claims_app = typer.Typer(help="Inspect result claims")
snapshots_app = typer.Typer(help="Inspect source snapshots")
review_app = typer.Typer(help="Review queue")
aliases_app = typer.Typer(help="Alias management")
app.add_typer(claims_app, name="claims")
app.add_typer(snapshots_app, name="snapshots")
app.add_typer(review_app, name="review")
app.add_typer(aliases_app, name="aliases")


def _default_registry_dir() -> Path:
    return Path(__file__).resolve().parent / "registry"


@app.command("init-db")
def init_db_cmd() -> None:
    """Create ledger tables."""
    init_db()
    typer.echo(f"Initialized database: {get_settings().database_url}")


@app.command("seed-registry")
def seed_registry_cmd(
    benchmarks: Path = typer.Option(_default_registry_dir() / "benchmarks.yaml", exists=True),
    models: Path = typer.Option(_default_registry_dir() / "models.yaml", exists=True),
    sources: Path = typer.Option(_default_registry_dir() / "official_sources.yaml", exists=True),
) -> None:
    """Load curated registry YAML files."""
    init_db()
    with get_session() as session:
        counts = seed_registry(
            session,
            benchmarks_path=benchmarks,
            models_path=models,
            sources_path=sources,
        )
    typer.echo(f"Seeded: {counts}")


@app.command("ingest")
def ingest_cmd(
    all_sources: bool = typer.Option(False, "--all", help="Ingest all active sources"),
    source: Optional[str] = typer.Option(None, "--source", help="Official source id"),
    benchmark: Optional[str] = typer.Option(None, "--benchmark", help="Benchmark id"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fail_fast: bool = typer.Option(False, "--fail-fast"),
    fixture: Optional[Path] = typer.Option(None, "--fixture", help="Fixture path for fake adapter"),
) -> None:
    """Run ingestion for selected sources."""
    if not all_sources and not source and not benchmark:
        raise typer.BadParameter("Provide --all, --source, or --benchmark")
    init_db()
    with get_session() as session:
        summary = run_ingestion(
            session,
            source_id=source,
            benchmark_id=benchmark,
            dry_run=dry_run,
            fail_fast=fail_fast,
            fixture_path=fixture,
        )
    typer.echo("Ingestion complete." + (" (dry-run)" if dry_run else ""))
    typer.echo(f"Sources checked: {summary.sources_checked}")
    typer.echo(f"Snapshots created: {summary.snapshots_created}")
    typer.echo(f"Snapshots reused: {summary.snapshots_reused}")
    typer.echo(f"Claims extracted: {summary.claims_extracted}")
    typer.echo(f"Claims inserted: {summary.claims_inserted}")
    typer.echo(f"Claims unchanged: {summary.claims_unchanged}")
    typer.echo(f"Claims needing review: {summary.claims_needing_review}")
    typer.echo(f"Errors: {len(summary.errors)}")
    for e in summary.errors:
        typer.echo(f"  - {e}")
    if dry_run and summary.dry_run_claims:
        typer.echo(f"Sample claims ({min(5, len(summary.dry_run_claims))}):")
        for c in summary.dry_run_claims[:5]:
            typer.echo(f"  {c['model_raw']} | {c['score_raw']} | {c['capture_status']}")


@claims_app.command("list")
def claims_list(benchmark: Optional[str] = typer.Option(None, "--benchmark"), limit: int = 20) -> None:
    with get_session() as session:
        rows = repo.list_claims(session, benchmark_id=benchmark, limit=limit)
        for c in rows:
            typer.echo(
                f"{c.id} | {c.benchmark_id or c.benchmark_raw} | {c.model_raw} | {c.score_raw} | {c.capture_status}"
            )


@claims_app.command("show")
def claims_show(claim_id: str) -> None:
    with get_session() as session:
        c = repo.get_claim(session, claim_id)
        if not c:
            raise typer.Exit(code=1)
        typer.echo(f"id: {c.id}")
        typer.echo(f"model_raw: {c.model_raw}")
        typer.echo(f"model_entity_id: {c.model_entity_id}")
        typer.echo(f"benchmark_raw: {c.benchmark_raw}")
        typer.echo(f"benchmark_id: {c.benchmark_id}")
        typer.echo(f"score_raw: {c.score_raw}")
        typer.echo(f"capture_status: {c.capture_status}")
        typer.echo(f"evidence_location: {c.evidence_location}")
        typer.echo(f"source_snapshot_id: {c.source_snapshot_id}")
        typer.echo(f"official_source_id: {c.official_source_id}")


@snapshots_app.command("list")
def snapshots_list(source: str = typer.Option(..., "--source")) -> None:
    with get_session() as session:
        rows = repo.list_snapshots(session, source)
        for s in rows:
            typer.echo(f"{s.id} | {s.content_hash[:12]} | {s.captured_at} | {s.raw_content_uri}")


@review_app.command("queue")
def review_queue(limit: int = 50) -> None:
    with get_session() as session:
        rows = repo.list_review_queue(session, limit=limit)
        if not rows:
            typer.echo("Review queue empty.")
            return
        for c in rows:
            reason = []
            if c.model_entity_id is None:
                reason.append("model_entity_id is null")
            if c.capture_status == "needs_review":
                reason.append("capture_status=needs_review")
            typer.echo(f"Claim ID: {c.id}")
            typer.echo(f"Benchmark: {c.benchmark_raw}")
            typer.echo(f"Model raw: {c.model_raw}")
            typer.echo(f"Score raw: {c.score_raw}")
            typer.echo(f"Reason: {', '.join(reason) or 'unspecified'}")
            typer.echo(f"Evidence: {c.evidence_location}")
            typer.echo("---")


@review_app.command("show")
def review_show(claim_id: str) -> None:
    claims_show(claim_id)


@review_app.command("auto-verify-matched")
def review_auto_verify() -> None:
    """Mark needs_review claims as parser_verified when their model_raw and
    benchmark_raw match a registered entity (alias-resolved). Bulk trust pass
    for machine-readable sources; human review still applies to the rest."""
    from app.matching.aliases import match_benchmark, match_model_entity

    with get_session() as session:
        rows = repo.list_review_queue(session, limit=10_000)
        verified = 0
        for c in rows:
            m = match_model_entity(session, c.model_raw)
            b = match_benchmark(session, c.benchmark_raw, c.benchmark_id)
            if m and b:
                repo.map_claim_model(session, c.id, m)
                repo.map_claim_benchmark(session, c.id, b)
                verified += 1
        typer.echo(f"Auto-verified (parser_verified): {verified} of {len(rows)}")
def review_map_model(claim_id: str, model_entity_id: str) -> None:
    with get_session() as session:
        c = repo.map_claim_model(session, claim_id, model_entity_id)
        if not c:
            raise typer.Exit(code=1)
        typer.echo(f"Mapped {claim_id} -> {model_entity_id} (model_raw unchanged: {c.model_raw})")


@review_app.command("mark-human-verified")
def review_human(claim_id: str) -> None:
    with get_session() as session:
        c = repo.mark_human_verified(session, claim_id)
        if not c:
            raise typer.Exit(code=1)
        typer.echo(f"Marked human_verified: {claim_id}")


@aliases_app.command("add")
def aliases_add(
    entity_type: str = typer.Option(..., "--entity-type"),
    entity_id: str = typer.Option(..., "--entity-id"),
    alias: str = typer.Option(..., "--alias"),
) -> None:
    with get_session() as session:
        row = repo.add_alias(
            session,
            entity_type=entity_type,
            entity_id=entity_id,
            alias_text=alias,
            is_official_alias=False,
            alias_source="cli",
        )
        typer.echo(f"Alias added: {row.id} {entity_type}/{entity_id} <- {alias}")


@app.command("export-official-json")
def export_cmd(
    out: Path = typer.Option(
        Path("../src/data/official/export.from-ledger.json"),
        "--out",
        help="Destination JSON consumed by the SPA Official mode",
    )
) -> None:
    with get_session() as session:
        payload = export_official_json(session, out)
    typer.echo(f"Wrote {out} ({len(payload.get('scores', []))} scores)")


if __name__ == "__main__":
    app()
