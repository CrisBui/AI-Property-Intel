import logging
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from property_intel.llm import get_chat_model
from property_intel.models.listing import MatchFilters, MatchResult
from property_intel.pipeline.match_query import (
    chroma_rerank,
    format_service_fee_summary,
    parse_match_filters,
    sql_filter_listings,
)

logger = logging.getLogger(__name__)

EXPLAIN_SYSTEM_PROMPT = """You summarize rental search results for a tenant in Vietnamese.

Rules:
- Use ONLY facts provided in the context (prices, districts, amenities, landmarks, scores).
- Always state each listing's district explicitly (e.g. "Cầu Giấy", "Nam Từ Liêm").
- If a listing's district differs from the filter district, mention that clearly.
- Do NOT invent market trends, demand percentages, or listings not in the context.
- Keep 2-4 short sentences: why top picks match the query, note fallback if SQL had zero candidates.
- If no results, say clearly no suitable room was found.
"""


class MatchingState(TypedDict):
    query: str
    filters: MatchFilters | None
    candidates_count: int
    chroma_fallback: bool
    results: list[MatchResult]
    answer: str
    explanation: str


def _parse_filters_node(state: MatchingState) -> MatchingState:
    filters = parse_match_filters(state["query"])
    return {**state, "filters": filters}


def _hybrid_search_node(state: MatchingState) -> MatchingState:
    filters = state["filters"]
    if filters is None:
        return {**state, "candidates_count": 0, "chroma_fallback": False, "results": []}

    candidates = sql_filter_listings(filters)
    results, used_fallback = chroma_rerank(state["query"], candidates, filters, top_k=5)
    return {
        **state,
        "candidates_count": len(candidates),
        "chroma_fallback": used_fallback,
        "results": results,
    }


def _format_answer_node(state: MatchingState) -> MatchingState:
    filters = state["filters"]
    results = state["results"]
    lines: list[str] = []

    if filters:
        lines.append(f"Filters: {filters.model_dump()}")
        lines.append(f"SQL candidates: {state.get('candidates_count', 0)}")
        if state.get("chroma_fallback"):
            lines.append(
                "Chroma mode: fallback (SQL=0 — kết quả chỉ xếp hạng mềm, có thể không thỏa filter cứng)"
            )
        else:
            lines.append("Chroma mode: rerank trong tập SQL candidates")

    if not results:
        lines.append("Không tìm thấy phòng phù hợp.")
        return {**state, "answer": "\n".join(lines), "explanation": ""}

    candidates_count = state.get("candidates_count", 0)
    if state.get("chroma_fallback"):
        lines.append(f"Top {len(results)} kết quả (Chroma fallback, không có SQL candidate):")
    elif candidates_count:
        lines.append(
            f"Top {len(results)}/{min(5, candidates_count)} "
            f"(trong {candidates_count} SQL candidates):"
        )
    else:
        lines.append(f"Top {len(results)} kết quả:")

    for i, item in enumerate(results, start=1):
        price = f"{item.price_vnd:,} VND" if item.price_vnd else "giá liên hệ"
        lines.append(
            f"{i}. [{item.source_id}] {item.title} — {price} — {item.district or 'N/A'}"
        )
        if item.area_min_m2 is not None or item.area_max_m2 is not None:
            if item.area_min_m2 is not None and item.area_max_m2 is not None and item.area_min_m2 != item.area_max_m2:
                lines.append(f"   Diện tích: {item.area_min_m2:g}–{item.area_max_m2:g} m²")
            elif item.area_min_m2 is not None:
                lines.append(f"   Diện tích: {item.area_min_m2:g} m²")
        if item.room_layout_tags:
            lines.append(f"   Loại phòng: {', '.join(item.room_layout_tags)}")
        if item.short_description:
            lines.append(f"   Mô tả: {item.short_description[:200]}")
        lines.append(f"   Tiện ích phòng: {', '.join(item.amenities) or '-'}")
        if item.common_amenities:
            lines.append(f"   Tiện ích chung: {', '.join(item.common_amenities)}")
        fee_summary = format_service_fee_summary(item.service_fees)
        if fee_summary:
            lines.append(f"   Phí DV: {'; '.join(fee_summary)}")
        if item.contact_phone:
            lines.append(f"   SĐT: {item.contact_phone}")
        if item.source_url:
            lines.append(f"   Link: {item.source_url}")
        lines.append(f"   {item.rationale}")

    return {**state, "answer": "\n".join(lines), "explanation": ""}


def _build_explain_context(state: MatchingState) -> str:
    filters = state.get("filters")
    results = state.get("results") or []
    lines = [
        f"Query: {state['query']}",
        f"Filters: {filters.model_dump() if filters else {}}",
        f"SQL candidates: {state.get('candidates_count', 0)}",
        f"Chroma fallback: {state.get('chroma_fallback', False)}",
        "Results:",
    ]
    for i, item in enumerate(results, start=1):
        price = item.price_vnd if item.price_vnd else "unknown"
        fee_summary = format_service_fee_summary(item.service_fees)
        lines.append(
            f"  {i}. {item.source_id} | {item.title} | district={item.district or 'N/A'} | "
            f"price={price} | area={item.area_min_m2}-{item.area_max_m2} | "
            f"layout={item.room_layout_tags} | amenities={item.amenities} | "
            f"common_amenities={item.common_amenities} | fees={fee_summary or item.service_fees} | "
            f"landmarks={item.near_landmarks if filters and filters.landmark else []} | "
            f"score={item.score:.3f}"
        )
    return "\n".join(lines)


def _explain_answer_node(state: MatchingState) -> MatchingState:
    if not state.get("results"):
        return state

    llm = get_chat_model()
    context = _build_explain_context(state)
    response = llm.invoke(
        [
            SystemMessage(content=EXPLAIN_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ]
    )
    explanation = response.content if isinstance(response.content, str) else str(response.content)
    logger.info("Generated grounded explanation (%d chars)", len(explanation))

    full_answer = state["answer"] + "\n\n---\nGiải thích:\n" + explanation.strip()
    return {**state, "explanation": explanation.strip(), "answer": full_answer}


def build_matching_graph():
    graph = StateGraph(MatchingState)
    graph.add_node("parse_filters", _parse_filters_node)
    graph.add_node("hybrid_search", _hybrid_search_node)
    graph.add_node("format_answer", _format_answer_node)
    graph.add_node("explain_answer", _explain_answer_node)

    graph.set_entry_point("parse_filters")
    graph.add_edge("parse_filters", "hybrid_search")
    graph.add_edge("hybrid_search", "format_answer")
    graph.add_edge("format_answer", "explain_answer")
    graph.add_edge("explain_answer", END)

    return graph.compile()


def run_matching_agent(query: str) -> str:
    app = build_matching_graph()
    final_state = app.invoke(
        {
            "query": query,
            "filters": None,
            "candidates_count": 0,
            "chroma_fallback": False,
            "results": [],
            "answer": "",
            "explanation": "",
        }
    )
    return final_state["answer"]
