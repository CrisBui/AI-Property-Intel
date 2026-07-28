import logging
import uuid

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text

from property_intel.agents.chat_graph import run_chat_agent
from property_intel.agents.matching_graph import run_matching_agent
from property_intel.api.meta_data import get_search_meta
from property_intel.api.schemas import (
    ChatRequest,
    ChatResponse,
    ListingDetail,
    SearchMetaResponse,
    SearchRequest,
    SearchResponse,
)
from property_intel.config import get_settings
from property_intel.db.session import get_engine
from property_intel.pipeline.market_intel import compute_market_report, format_market_report
from property_intel.pipeline.search_service import get_listing_by_source_id, search_listings

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Property Intelligence", version="0.4.0")

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


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
    html_path = _STATIC_DIR / "app.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/legacy", response_class=HTMLResponse)
def legacy_home() -> str:
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


@app.get("/api/meta/search", response_model=SearchMetaResponse)
def api_search_meta() -> SearchMetaResponse:
    return get_search_meta()


@app.post("/api/search", response_model=SearchResponse)
def api_search(body: SearchRequest) -> SearchResponse:
    try:
        return search_listings(body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/listings/{source_id}", response_model=ListingDetail)
def api_listing_detail(source_id: str) -> ListingDetail:
    detail = get_listing_by_source_id(source_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Listing not found: {source_id}")
    return detail


@app.post("/api/chat", response_model=ChatResponse)
def api_chat(body: ChatRequest) -> ChatResponse:
    settings = get_settings()
    if not settings.has_llm_credentials():
        raise HTTPException(
            status_code=503,
            detail=f"Missing API key for LLM provider '{settings.llm_provider}'",
        )
    session_id = body.session_id or str(uuid.uuid4())
    try:
        reply, cards, filters, client_state, tool_calls = run_chat_agent(
            body.messages,
            body.client_state,
            body.page_context,
        )
    except Exception as exc:
        logger.exception("Chat agent failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        cards=cards,
        filters_applied=filters,
        client_state=client_state,
        tool_calls=tool_calls,
    )


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
