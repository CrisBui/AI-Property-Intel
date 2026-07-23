import logging
from typing import Literal

import typer

from property_intel.agents.matching_graph import run_matching_agent
from property_intel.config import get_settings
from property_intel.pipeline.crawl.runner import run_crawl
from property_intel.pipeline.crawl.discovery import run_discover
from property_intel.pipeline.crawl.purge import purge_legacy_data, purge_nhatot, reset_phongtot_for_recrawl
from property_intel.pipeline.extract import extract_listings
from property_intel.pipeline.index import index_listings
from property_intel.pipeline.ingest import ingest_raw_listings
from property_intel.pipeline.market_intel import compute_market_report, format_market_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = typer.Typer(help="AI Property Intelligence CLI")

CrawlSourceOption = Literal["firecrawl", "url-fetch"]


@app.command()
def ingest() -> None:
    """Ingest raw listing files from data/raw."""
    stats = ingest_raw_listings()
    typer.echo(
        f"Ingest done: inserted={stats['inserted']} updated={stats['updated']} "
        f"skipped={stats['skipped']}"
    )


@app.command()
def discover(
    urls_file: str | None = typer.Option(
        None,
        "--urls-file",
        "-f",
        help="Search/category page URLs (default: data/crawl/search_urls.txt)",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output listing URL file (default: data/crawl/urls.txt)",
    ),
    max_links: int = typer.Option(
        30,
        "--max-links",
        help="Max listing URLs per search page",
    ),
) -> None:
    """Discover listing URLs from search pages → write urls.txt."""
    stats = run_discover(
        search_urls_file=urls_file,
        output_file=output,
        max_links_per_page=max_links,
    )
    typer.echo(
        f"Discover done: search_pages={stats['search_pages']} "
        f"discovered={stats['discovered']} output={stats['output']}"
    )


@app.command()
def crawl(
    source: str = typer.Option(
        "firecrawl",
        "--source",
        "-s",
        help="Crawl adapter: firecrawl | url-fetch",
    ),
    urls_file: str | None = typer.Option(
        None,
        "--urls-file",
        "-f",
        help="Listing URL file, or search pages when --discover",
    ),
    rate_limit: float | None = typer.Option(
        None,
        "--rate-limit",
        help="Seconds between URL requests (default from CRAWL_RATE_LIMIT_SECONDS)",
    ),
    discover: bool = typer.Option(
        False,
        "--discover",
        help="Discover listing URLs from search pages first (Chợ Tốt)",
    ),
    max_links: int = typer.Option(
        30,
        "--max-links",
        help="Max listing URLs per search page (with --discover)",
    ),
) -> None:
    """Crawl listing URLs into raw_listings (CLI job, not HTTP)."""
    if source not in ("firecrawl", "url-fetch"):
        typer.echo(f"Unknown source '{source}'. Use firecrawl or url-fetch.", err=True)
        raise typer.Exit(code=1)

    stats = run_crawl(
        source_name=source,  # type: CrawlSourceOption
        urls_file=urls_file,
        rate_limit_seconds=rate_limit,
        discover_first=discover,
        search_urls_file=urls_file,
        max_links_per_page=max_links,
    )
    discovered = stats.get("discovered", "")
    extra = f" discovered={discovered}" if discover else ""
    typer.echo(
        f"Crawl done: inserted={stats['inserted']} updated={stats['updated']} "
        f"skipped={stats['skipped']} failed={stats['failed']} "
        f"total_urls={stats['total_urls']}{extra}"
    )


@app.command("purge-legacy")
def purge_legacy_cmd() -> None:
    """Remove seed, firecrawl, url_fetch, nhatot — keep only PhongTot data."""
    stats = purge_legacy_data()
    typer.echo(
        f"Purge legacy done: raw_deleted={stats['raw_deleted']} "
        f"listings_deleted={stats['listings_deleted']} "
        f"chroma_deleted={stats['chroma_deleted']}"
    )


@app.command("purge-nhatot")
def purge_nhatot_cmd() -> None:
    """Remove NhaTot/Chotot crawl data from DB and Chroma (keeps seed + PhongTot)."""
    stats = purge_nhatot()
    typer.echo(
        f"Purge NhaTot done: raw_deleted={stats['raw_deleted']} "
        f"listings_deleted={stats['listings_deleted']} "
        f"chroma_deleted={stats['chroma_deleted']}"
    )


@app.command("reset-phongtot")
def reset_phongtot_cmd() -> None:
    """Delete PhongTot crawl rows so you can re-crawl with fixed scrape settings."""
    stats = reset_phongtot_for_recrawl()
    typer.echo(
        f"Reset PhongTot done: raw_deleted={stats['raw_deleted']} "
        f"listings_deleted={stats['listings_deleted']} "
        f"chroma_deleted={stats['chroma_deleted']}"
    )


@app.command()
def extract(
    rate_limit: float | None = typer.Option(
        None,
        "--rate-limit",
        help="Seconds between LLM calls (default: EXTRACT_RATE_LIMIT_SECONDS, recommend 6+ for Groq free tier)",
    ),
    platform: str | None = typer.Option(
        None,
        "--platform",
        "-p",
        help="Only extract this source_platform, e.g. phongtot",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-extract even if already extracted (fixes bad LLM output)",
    ),
    no_summary: bool = typer.Option(
        False,
        "--no-summary",
        help="Skip LLM short_description; use template from parser fields",
    ),
) -> None:
    """Extract structured fields from raw listings via LLM."""
    settings = get_settings()
    if not settings.has_llm_credentials():
        typer.echo(
            f"Missing API key for LLM provider '{settings.llm_provider}'. "
            "Set credentials in .env then retry.",
            err=True,
        )
        raise typer.Exit(code=1)

    stats = extract_listings(
        rate_limit_seconds=rate_limit,
        platform=platform,
        force=force,
        enable_llm_summary=False if no_summary else None,
    )
    typer.echo(f"Extract done: success={stats['success']} failed={stats['failed']}")


@app.command()
def index() -> None:
    """Index listings into database and Chroma."""
    stats = index_listings()
    typer.echo(f"Index done: indexed={stats['indexed']}")


@app.command("migrate-sqlite")
def migrate_sqlite(
    sqlite_url: str = typer.Option(
        "sqlite:///./data/app.db",
        "--sqlite-url",
        help="Source SQLite DATABASE_URL",
    ),
) -> None:
    """One-shot copy data from SQLite to PostgreSQL (target = DATABASE_URL in .env)."""
    from property_intel.db.migrate_sqlite import migrate_sqlite_to_postgres

    stats = migrate_sqlite_to_postgres(sqlite_url=sqlite_url)
    typer.echo(
        f"Migrate done: raw_listings={stats['raw_listings']} listings={stats['listings']}"
    )


@app.command()
def match(
    query: str = typer.Argument(..., help="Natural language search query"),
) -> None:
    """Match listings using hybrid SQL + Chroma search via LangGraph agent."""
    settings = get_settings()
    if not settings.has_llm_credentials():
        typer.echo(
            f"Missing API key for LLM provider '{settings.llm_provider}'. "
            "Set credentials in .env then retry.",
            err=True,
        )
        raise typer.Exit(code=1)

    answer = run_matching_agent(query)
    typer.echo(answer)


@app.command()
def analyze(
    landmark: str | None = typer.Option(
        None,
        "--landmark",
        "-l",
        help="Filter by landmark slug, e.g. bach_khoa, dhbk, kim_lien",
    ),
) -> None:
    """Market stats for landlords from extracted listings (no LLM)."""
    report = compute_market_report(landmark=landmark)
    typer.echo(format_market_report(report))


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Start FastAPI web UI and JSON API."""
    import uvicorn

    typer.echo(f"Starting server at http://{host}:{port}")
    uvicorn.run("property_intel.api.app:app", host=host, port=port, reload=False)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
