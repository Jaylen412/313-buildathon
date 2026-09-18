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
def ingest(since: str | None = typer.Option(None, help="YYYY-MM-DD, incremental pull")) -> None:
    """Pull all ArcGIS layers into data/raw/*.parquet and load raw_* tables."""
    from datetime import date

    from signals import ingest as ingest_mod

    con = connect()
    since_date = date.fromisoformat(since) if since else None
    ingest_mod.load_all(con, since=since_date)
    typer.echo("ingest complete")


@app.command()
def features() -> None:
    """Build sales_clean + bg_features from the raw tables."""
    from signals import features as features_mod
    from signals import geo as geo_mod

    con = connect()
    geo_mod.assign_block_groups(con)
    features_mod.build_features(con)
    typer.echo("features complete")


@app.command()
def train() -> None:
    """Train the forecast model (or fall back) and score every block group."""
    from signals import forecast as forecast_mod

    con = connect()
    df = con.execute("SELECT * FROM bg_features").fetchdf()
    settings = get_settings()
    if settings.model_mode.value == "fallback":
        scores = forecast_mod.fallback_index(df)
    else:
        model, report = forecast_mod.train(df)
        typer.echo(f"backtest: {report}")
        scores = forecast_mod.score(model, df)
    typer.echo(f"scored {len(scores)} block groups")


@app.command()
def score() -> None:
    """Re-score using the currently trained/fallback model without retraining."""
    typer.echo("not yet implemented — run `signals train` (see md/architecture.md §7)")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000, reload: bool = True) -> None:
    """Run the FastAPI app."""
    uvicorn.run("signals.api:app", host=host, port=port, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
