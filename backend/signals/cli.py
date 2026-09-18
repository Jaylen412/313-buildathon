"""`signals` CLI: ingest | features | train | score | serve.

Each subcommand maps to one build-order milestone in md/architecture.md §7.
"""
from __future__ import annotations

import typer
import uvicorn

from signals.config import get_settings
from signals.db import connect

app = typer.Typer(help="Signals data pipeline and API server.")


@app.command()
def ingest(
    since: str | None = typer.Option(None, help="YYYY-MM-DD, incremental pull"),
    resume: bool = typer.Option(
        False, "--resume", help="Skip pulling layers whose data/raw/*.parquet already exists"
    ),
) -> None:
    """Pull all ArcGIS layers into data/raw/*.parquet and load raw_* tables."""
    from datetime import date

    from signals import ingest as ingest_mod

    con = connect()
    since_date = date.fromisoformat(since) if since else None
    ingest_mod.load_all(con, since=since_date, resume=resume)
    typer.echo("ingest complete")


@app.command()
def features() -> None:
    """Assign parcels to block groups, build sales_clean + bg_features, and
    cache the block-group polygons for the map."""
    from signals import features as features_mod
    from signals import geo as geo_mod

    con = connect()
    geo_mod.assign_block_groups(con)
    features_mod.build_features(con)
    geo_mod.export_blockgroups_geojson(con)
    typer.echo("features complete")


@app.command()
def train() -> None:
    """Train + backtest the forecast (or use the fallback index per MODEL_MODE),
    then score every block group into bg_scores."""
    from signals import forecast as forecast_mod
    from signals.config import ModelMode

    con = connect()
    features = con.execute("SELECT * FROM bg_features").fetchdf()
    settings = get_settings()

    if settings.model_mode == ModelMode.FALLBACK:
        typer.echo("MODEL_MODE=fallback: using the weighted index, no training")
        scores = forecast_mod.fallback_index(features)
    else:
        model, report = forecast_mod.train(features, settings)
        bt = report["backtest"]
        typer.echo(
            f"backtest on {report['holdout_year']} (train {report['train_years'][0]}-"
            f"{report['train_years'][1]}, {report['training_rows']} rows): "
            f"MAE {bt['mae']:.3f} vs predict-the-mean {bt['baseline_mae_predict_mean']:.3f}, "
            f"R2 {bt['r2']:.3f}, Spearman {bt['spearman']:.3f}"
        )
        top = list(report["permutation_importance"].items())[:5]
        typer.echo("top importances: " + ", ".join(f"{k}={v:.4f}" for k, v in top))
        mode = settings.model_mode if settings.model_mode != ModelMode.AUTO else forecast_mod.recommended_mode(report)
        if mode == ModelMode.FALLBACK:
            typer.echo("auto: backtest below threshold -> weighted index (fallback)")
            scores = forecast_mod.fallback_index(features)
        else:
            scores = forecast_mod.score(model, features)

    forecast_mod.write_scores(con, scores)
    _echo_scores(scores)


@app.command()
def score() -> None:
    """Re-score with the saved model (or the fallback index) without retraining."""
    from signals import forecast as forecast_mod
    from signals.config import ModelMode

    con = connect()
    features = con.execute("SELECT * FROM bg_features").fetchdf()
    settings = get_settings()
    mode = settings.model_mode
    if mode == ModelMode.AUTO:
        mode = forecast_mod.recommended_mode(forecast_mod.load_report(settings))
    if mode == ModelMode.FALLBACK:
        scores = forecast_mod.fallback_index(features)
    else:
        scores = forecast_mod.score(forecast_mod.load_model(settings), features)
    forecast_mod.write_scores(con, scores)
    _echo_scores(scores)


def _echo_scores(scores) -> None:
    mode = scores["model_mode"].iloc[0]
    hot = int((scores["heat_score"] >= 70).sum())
    typer.echo(f"scored {len(scores)} block groups ({mode}); {hot} at heat >= 70")


@app.command()
def rank(threshold: int = typer.Option(70, help="heat_score at or above which a block group is 'hot'")) -> None:
    """Precompute the gated household ranking (parcel_vulnerability) for every
    hot block group. The API also computes it live; this is for inspection."""
    from signals import vulnerability as vuln

    con = connect()
    counts = vuln.rank_all_hot(con, threshold)
    total = sum(counts.values())
    typer.echo(f"ranked {total} owner-occupied households across {len(counts)} hot block groups (heat >= {threshold})")


@app.command()
def brief(
    geoid: list[str] = typer.Argument(..., help="block-group GEOID(s) to pre-generate briefs for"),
    force: bool = typer.Option(False, "--force", help="regenerate even if cached"),
) -> None:
    """Pre-generate (and cache under data/briefs/) the outreach brief for the
    given block groups — run this for the demo corridors before the demo so
    it works without Wi-Fi (md/TODO.md E.4)."""
    from signals import brief as brief_mod
    from signals import forecast as forecast_mod

    con = connect()
    report = forecast_mod.load_report()
    for g in geoid:
        result = brief_mod.get_or_create_brief(con, g, report, force=force)
        if result is None:
            typer.echo(f"{g}: unknown block group")
            continue
        b, cached, summary = result
        typer.echo(f"{g} ({summary.neighborhood}): {'cached' if cached else 'generated'} — {b.headline}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = True) -> None:
    """Run the FastAPI app."""
    uvicorn.run("signals.api:app", host=host, port=port, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
