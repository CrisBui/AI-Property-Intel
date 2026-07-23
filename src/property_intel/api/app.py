from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from property_intel.agents.matching_graph import run_matching_agent
from property_intel.config import get_settings
from property_intel.db.session import get_engine
from property_intel.pipeline.market_intel import compute_market_report, format_market_report

app = FastAPI(title="AI Property Intelligence", version="0.2.0")

_STATIC_DIR = Path(__file__).parent / "static"


class MatchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)


class MatchResponse(BaseModel):
    query: str
    answer: str


class MarketResponse(BaseModel):
    landmark: str | None
    report_text: str
    total_listings: int


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    html_path = _STATIC_DIR / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc
    return {"status": "ok"}


@app.post("/api/match", response_model=MatchResponse)
def api_match(body: MatchRequest) -> MatchResponse:
    settings = get_settings()
    if not settings.has_llm_credentials():
        raise HTTPException(
            status_code=503,
            detail=f"Missing API key for LLM provider '{settings.llm_provider}'",
        )
    answer = run_matching_agent(body.query)
    return MatchResponse(query=body.query, answer=answer)


@app.get("/api/market", response_model=MarketResponse)
def api_market(
    landmark: str | None = Query(default=None, description="e.g. bach_khoa, dhbk, kim_lien"),
) -> MarketResponse:
    report = compute_market_report(landmark=landmark)
    return MarketResponse(
        landmark=landmark,
        report_text=format_market_report(report),
        total_listings=report.total_listings,
    )
