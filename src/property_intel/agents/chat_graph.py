import logging
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from property_intel.api.schemas import ChatClientState, ChatMessage, ListingCard, SearchPageContext
from property_intel.config import get_settings
from property_intel.llm import (
    augment_system_prompt_for_structured,
    get_chat_model,
    with_structured_output_compat,
)
from property_intel.models.listing import MatchFilters
from property_intel.pipeline.chat_tools import (
    format_compact_listings,
    format_listing_detail_lines,
    format_messages_for_prompt,
    format_page_context_for_prompt,
    format_user_preferences,
    is_follow_up_advise,
    is_page_scoped_request,
    listing_ids_from_page,
    load_listings_for_comparison,
    match_result_to_card,
    merge_match_filters,
    resolve_listing_result_ids,
    resolve_source_id,
    should_query_full_db,
)
from property_intel.pipeline.match_query import chroma_rerank, parse_match_filters, sql_filter_listings
from property_intel.pipeline.search_service import get_listing_by_source_id

logger = logging.getLogger(__name__)

PLANNER_PROMPT = """You plan the next action for a Vietnamese rental-room assistant embedded in a search UI.

Choose ONE intent:

- search: Query the FULL database for listings matching district, price, area, amenities, or free text.
  Use for: "các trọ Nam Từ Liêm", "phòng dưới 4 triệu Cầu Giấy", "tìm trọ gần ĐHBK", any new filter/area question.
  The UI page may show only 20 results — search MUST ignore that limit and query all stored listings.

- compare_results: Side-by-side comparison ONLY when user refers to listings already in context:
  "so sánh 3 phòng đang xem", "ưu nhược điểm các căn trên màn hình".
  Do NOT use for district-wide questions — use search instead.

- advise: Recommendation/ranking after user stated preferences (budget, occupants, lifestyle).
  Use last search results or compared listings — not limited to the UI page if a DB search ran earlier.

- listing_detail: ONE specific listing by index ("căn thứ 2") or name from recent results.

- general: greeting without listing data.

Rules:
- District / price / area / "tìm trọ" questions → search (full DB), even if the UI page shows other filters.
- compare_results ONLY when user clearly means current visible page ("đang hiển thị", "các phòng này").
- For search, set search_text as self-contained Vietnamese query.
- For listing_detail, set result_index (1-based) for "căn thứ 2".
- Do NOT invent listing IDs."""


REPLY_PROMPT = """You are a sharp Vietnamese rental advisor (helpful friend, not a brochure).

Rules:
- Reply ONLY in Vietnamese.
- Use ONLY facts from tool context.
- Use **bold** for **Kết luận:**, **Gợi ý:**, **Lưu ý:** only.
- Do NOT repeat full comparison of every listing if user already saw them — answer the NEW question.
- Do NOT ask vague questions if user already stated budget.
- Ask at most 1-2 SPECIFIC questions when critical info is missing.
- No markdown tables (UI renders separately)."""


class UserPreferencesExtract(BaseModel):
    budget_total_vnd: int | None = Field(default=None)
    budget_per_person_vnd: int | None = None
    occupants: int | None = None
    is_student: bool | None = None
    needs_study_space: bool | None = None
    required_amenities: list[str] = Field(default_factory=list)
    priority_notes: str | None = None


class ChatPlannerDecision(BaseModel):
    intent: Literal["search", "listing_detail", "compare_results", "advise", "general"] = "search"
    search_text: str | None = None
    result_index: int | None = Field(default=None, ge=1, le=30)
    source_id: str | None = None


class ChatState(TypedDict):
    messages: list[dict[str, str]]
    client_state: dict
    page_context: dict | None
    planner: ChatPlannerDecision | None
    filters: MatchFilters | None
    cards: list[ListingCard]
    tool_calls: list[str]
    candidates_count: int
    chroma_fallback: bool
    tool_context: str
    reply: str
    updated_client_state: dict


def _last_user_message(messages: list[dict[str, str]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return (msg.get("content") or "").strip()
    return ""


def _execute_db_search(
    search_text: str,
    client: ChatClientState,
    top_k: int,
) -> tuple[list[ListingCard], MatchFilters, int, bool, str, ChatClientState]:
    new_filters = parse_match_filters(search_text)
    filters = merge_match_filters(client.last_filters, new_filters)
    candidates = sql_filter_listings(filters)
    results, used_fallback = chroma_rerank(search_text, candidates, filters, top_k=top_k)
    cards = [match_result_to_card(r) for r in results]
    context_lines = [
        f"Search text: {search_text}",
        f"Filters: {filters.model_dump()}",
        f"Total matching in database: {len(candidates)}",
        f"Chroma rerank fallback: {used_fallback}",
        f"Top results shown to user: {len(cards)} (max {top_k})",
        "Important: Tell the user how many listings match in total, then summarize the top results.",
        "Listings:",
    ]
    for i, card in enumerate(cards, start=1):
        context_lines.append(
            f"  {i}. {card.source_id} | {card.title} | {card.district} | "
            f"price={card.price_vnd} | area={card.area_min_m2}-{card.area_max_m2} | "
            f"fees={'; '.join(card.service_fees_summary)} | phone={card.contact_phone}"
        )
    updated = client.model_copy(
        update={
            "last_filters": filters,
            "last_result_ids": [c.source_id for c in cards],
            "focused_source_id": None,
            "compared_listing_ids": [],
        }
    )
    return cards, filters, len(candidates), used_fallback, "\n".join(context_lines), updated


def _plan_node(state: ChatState) -> ChatState:
    settings = get_settings()
    llm = get_chat_model(settings)
    structured = with_structured_output_compat(llm, ChatPlannerDecision, settings)
    client = state.get("client_state") or {}
    page_ctx = state.get("page_context")
    history = format_messages_for_prompt(state.get("messages") or [])
    page_summary = format_page_context_for_prompt(
        SearchPageContext.model_validate(page_ctx) if page_ctx else None
    )
    prompt = (
        f"Conversation:\n{history}\n\n"
        f"Client state:\n"
        f"- last_filters: {client.get('last_filters')}\n"
        f"- last_result_ids: {client.get('last_result_ids')}\n"
        f"- compared_listing_ids: {client.get('compared_listing_ids')}\n"
        f"- user_preferences: {client.get('user_preferences')}\n"
        f"- focused_source_id: {client.get('focused_source_id')}\n\n"
        f"Current search page:\n{page_summary}"
    )
    decision = structured.invoke(
        [
            {
                "role": "system",
                "content": augment_system_prompt_for_structured(PLANNER_PROMPT, settings),
            },
            {"role": "user", "content": prompt},
        ]
    )
    # Override: follow-up with same listings → advise, not repeat compare
    page_context = (
        SearchPageContext.model_validate(page_ctx) if page_ctx else None
    )
    current_ids = listing_ids_from_page(page_context)
    compared_ids = client.get("compared_listing_ids") or []
    messages = state.get("messages") or []
    last_user = _last_user_message(messages)
    if should_query_full_db(last_user, decision.intent) and decision.intent != "search":
        decision = decision.model_copy(
            update={"intent": "search", "search_text": decision.search_text or last_user}
        )
    if (
        decision.intent == "compare_results"
        and compared_ids
        and current_ids == compared_ids
        and (len(messages) > 1 or is_follow_up_advise(messages))
    ):
        decision = decision.model_copy(update={"intent": "advise"})
    if decision.intent == "compare_results" and is_follow_up_advise(messages) and current_ids:
        decision = decision.model_copy(update={"intent": "advise"})
    logger.info("Chat planner intent=%s", decision.intent)
    return {**state, "planner": decision}


def _tool_node(state: ChatState) -> ChatState:
    decision = state.get("planner")
    if decision is None:
        return {**state, "tool_context": "", "cards": [], "tool_calls": []}

    settings = get_settings()
    messages = state.get("messages") or []
    client = ChatClientState.model_validate(state.get("client_state") or {})
    page_context = (
        SearchPageContext.model_validate(state["page_context"])
        if state.get("page_context")
        else None
    )
    last_user = _last_user_message(messages)

    if decision.intent == "search":
        search_text = (decision.search_text or last_user).strip()
        if not search_text:
            return {
                **state,
                "tool_context": "No search text available.",
                "cards": [],
                "tool_calls": [],
            }
        top_k = settings.chat_search_top_k
        cards, filters, total, used_fallback, tool_context, updated = _execute_db_search(
            search_text, client, top_k
        )
        return {
            **state,
            "filters": filters,
            "cards": cards,
            "tool_calls": ["search_listings"],
            "candidates_count": total,
            "chroma_fallback": used_fallback,
            "tool_context": tool_context,
            "updated_client_state": updated.model_dump(),
        }

    if decision.intent == "compare_results":
        if should_query_full_db(last_user, "compare_results"):
            top_k = settings.chat_search_top_k
            cards, filters, total, used_fallback, tool_context, updated = _execute_db_search(
                last_user, client, top_k
            )
            return {
                **state,
                "filters": filters,
                "cards": cards,
                "tool_calls": ["search_listings"],
                "candidates_count": total,
                "chroma_fallback": used_fallback,
                "tool_context": tool_context,
                "updated_client_state": updated.model_dump(),
            }
        details, cards = load_listings_for_comparison(
            page_context, client.last_result_ids, last_user
        )
        if not details:
            return {
                **state,
                "tool_context": "No listings available to compare.",
                "cards": [],
                "tool_calls": [],
                "updated_client_state": client.model_dump(),
            }
        scope_label = (
            "visible on the user's search page"
            if is_page_scoped_request(last_user)
            else "from the latest database search"
        )
        context_lines = [
            f"Task: compare listings {scope_label}.",
            f"Filters on page: {page_context.filters_summary if page_context else 'unknown'}",
            f"Total search results on UI page: {page_context.total if page_context else 'n/a'}",
            f"Comparing {len(details)} listing(s):",
        ]
        for i, detail in enumerate(details, start=1):
            context_lines.extend(format_listing_detail_lines(detail, i))
        updated = client.model_copy(
            update={
                "last_result_ids": [d.source_id for d in details],
                "compared_listing_ids": [d.source_id for d in details],
                "focused_source_id": None,
            }
        )
        return {
            **state,
            "cards": cards,
            "tool_calls": ["compare_results"],
            "tool_context": "\n".join(context_lines),
            "updated_client_state": updated.model_dump(),
        }

    if decision.intent == "advise":
        details, _cards = load_listings_for_comparison(
            page_context, client.last_result_ids, last_user
        )
        if not details and should_query_full_db(last_user, "advise"):
            top_k = settings.chat_search_top_k
            cards, filters, total, used_fallback, tool_context, updated = _execute_db_search(
                last_user, client, top_k
            )
            details, _cards = load_listings_for_comparison(
                page_context, updated.last_result_ids, last_user
            )
            if details:
                prefs = _extract_user_preferences(messages, client.user_preferences, settings)
                merged_prefs = {**client.user_preferences, **prefs}
                context_lines = [
                    "Task: ADVISE after database search.",
                    f"Total matching in database: {total}",
                    f"User preferences:\n{format_user_preferences(merged_prefs)}",
                    f"Listings (compact):\n{format_compact_listings(details)}",
                    "",
                    "Reply style: direct recommendation first, brief why, note tradeoffs.",
                ]
                updated = updated.model_copy(update={"user_preferences": merged_prefs})
                return {
                    **state,
                    "filters": filters,
                    "cards": cards[:5],
                    "tool_calls": ["search_listings", "advise"],
                    "candidates_count": total,
                    "chroma_fallback": used_fallback,
                    "tool_context": "\n".join(context_lines),
                    "updated_client_state": updated.model_dump(),
                }
        if not details:
            return {
                **state,
                "tool_context": "No listings available to advise about.",
                "cards": [],
                "tool_calls": [],
                "updated_client_state": client.model_dump(),
            }
        prefs = _extract_user_preferences(messages, client.user_preferences, settings)
        merged_prefs = {**client.user_preferences, **prefs}
        context_lines = [
            "Task: ADVISE — recommend best fit based on user preferences.",
            f"User preferences:\n{format_user_preferences(merged_prefs)}",
            f"Listings (compact):\n{format_compact_listings(details)}",
            "",
            "Budget guidance for 2 occupants with AC:",
            "- Estimate utilities ~400,000–700,000 VND/month (electricity 4000/kWh, water per listing).",
            "- Total cost ≈ rent + utilities. Compare against user's stated budget.",
            "",
            "Reply style: direct recommendation first, brief why, note tradeoffs, 1-2 specific questions max.",
        ]
        updated = client.model_copy(
            update={
                "last_result_ids": [d.source_id for d in details],
                "user_preferences": merged_prefs,
                "focused_source_id": None,
            }
        )
        return {
            **state,
            "cards": [],  # no table repeat on follow-up
            "tool_calls": ["advise"],
            "tool_context": "\n".join(context_lines),
            "updated_client_state": updated.model_dump(),
        }

    if decision.intent == "listing_detail":
        result_ids = resolve_listing_result_ids(
            client.last_result_ids, page_context, last_user
        )
        source_id = resolve_source_id(
            explicit_id=decision.source_id,
            result_index=decision.result_index,
            last_result_ids=result_ids,
            focused_source_id=client.focused_source_id,
            user_text=last_user,
        )
        if not source_id:
            return {
                **state,
                "tool_context": "Could not resolve which listing the user refers to.",
                "cards": [],
                "tool_calls": [],
                "updated_client_state": client.model_dump(),
            }
        detail = get_listing_by_source_id(source_id)
        if detail is None:
            return {
                **state,
                "tool_context": f"Listing not found: {source_id}",
                "cards": [],
                "tool_calls": ["get_listing"],
                "updated_client_state": client.model_dump(),
            }
        card = ListingCard.model_validate(detail.model_dump())
        context_lines = [
            f"Listing detail: {detail.source_id}",
            f"Title: {detail.title}",
            f"District: {detail.district}",
            f"Address: {detail.address_text}",
            f"Price: {detail.price_vnd}",
            f"Area: {detail.area_min_m2}-{detail.area_max_m2}",
            f"Amenities: {detail.amenities}",
            f"Common: {detail.common_amenities}",
            f"Fees: {'; '.join(detail.service_fees_summary)}",
            f"Building: {detail.building}",
            f"Phone: {detail.contact_phone}",
            f"URL: {detail.source_url}",
            f"Description: {(detail.description_long or detail.short_description or '')[:800]}",
        ]
        updated = client.model_copy(update={"focused_source_id": source_id})
        return {
            **state,
            "cards": [card],
            "tool_calls": ["get_listing"],
            "tool_context": "\n".join(context_lines),
            "updated_client_state": updated.model_dump(),
        }

    return {
        **state,
        "tool_context": "General conversation — no DB lookup.",
        "cards": [],
        "tool_calls": [],
        "updated_client_state": client.model_dump(),
    }


def _extract_user_preferences(
    messages: list[dict[str, str]],
    existing: dict,
    settings,
) -> dict:
    """Merge LLM-extracted preferences from recent user messages."""
    recent_user = [
        m.get("content", "")
        for m in messages[-6:]
        if m.get("role") == "user"
    ]
    if not recent_user:
        return {}
    llm = get_chat_model(settings)
    structured = with_structured_output_compat(llm, UserPreferencesExtract, settings)
    prompt = (
        f"Existing preferences: {existing}\n\n"
        f"Recent user messages:\n" + "\n".join(recent_user) + "\n\n"
        "Extract/update rental preferences. Parse Vietnamese budget like 2tr5 = 2500000 VND. "
        "If user says 2 people 5tr total, set budget_total_vnd=5000000 and occupants=2."
    )
    try:
        extracted = structured.invoke(
            [
                {
                    "role": "system",
                    "content": augment_system_prompt_for_structured(
                        "Extract structured user preferences from Vietnamese rental chat.",
                        settings,
                    ),
                },
                {"role": "user", "content": prompt},
            ]
        )
        data = extracted.model_dump()
        return {k: v for k, v in data.items() if v is not None and v != "" and v != []}
    except Exception:
        logger.warning("Preference extraction failed", exc_info=True)
        return {}


def _reply_node(state: ChatState) -> ChatState:
    llm = get_chat_model()
    history = format_messages_for_prompt(state.get("messages") or [])
    context = state.get("tool_context") or ""
    tool_calls = state.get("tool_calls") or []
    extra = ""
    if "search_listings" in tool_calls:
        extra = (
            "\n\nSEARCH mode (full database). Rules:\n"
            "- State total matching listings from tool context (e.g. 'Có 12 căn Nam Từ Liêm').\n"
            "- Summarize top results; do not claim you only see the UI page.\n"
            "- If total > shown, mention that only the best matches are listed.\n"
            "- Use **Gợi ý:** for next steps (filter tighter, compare, ask detail)."
        )
    elif "compare_results" in tool_calls:
        extra = (
            "\n\nFIRST comparison (show once). Structure:\n"
            "1) One-line intro\n"
            "2) **Căn N:** 2-3 sentences each (pros/cons)\n"
            "3) **Kết luận:** preliminary ranking\n"
            "4) ONE specific question about what matters most to the user"
        )
    elif "advise" in tool_calls:
        extra = (
            "\n\nADVISE mode (follow-up). Rules:\n"
            "- Do NOT repeat the full 3-room comparison paragraph block.\n"
            "- Answer directly: which room fits BEST and which to avoid.\n"
            "- Do simple budget math: rent + estimated utilities vs stated budget.\n"
            "- Rank top 1-2 options with clear tradeoffs (area vs price vs amenities).\n"
            "- If none fit budget, say so honestly and suggest closest option or widening search.\n"
            "- Ask 1-2 concrete questions only if truly needed (not generic budget questions)."
        )
    prompt = (
        f"Conversation:\n{history}\n\nTool context:\n{context}{extra}\n\n"
        "Write the assistant reply in Vietnamese."
    )
    response = llm.invoke(
        [
            SystemMessage(content=REPLY_PROMPT),
            HumanMessage(content=prompt),
        ]
    )
    reply = response.content if isinstance(response.content, str) else str(response.content)
    return {**state, "reply": reply.strip()}


def build_chat_graph():
    graph = StateGraph(ChatState)
    graph.add_node("plan", _plan_node)
    graph.add_node("tools", _tool_node)
    graph.add_node("reply", _reply_node)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "tools")
    graph.add_edge("tools", "reply")
    graph.add_edge("reply", END)
    return graph.compile()


def run_chat_agent(
    messages: list[ChatMessage],
    client_state: ChatClientState | None = None,
    page_context: SearchPageContext | None = None,
) -> tuple[str, list[ListingCard], MatchFilters | None, ChatClientState, list[str]]:
    app = build_chat_graph()
    cs = client_state or ChatClientState()
    msg_dicts = [{"role": m.role, "content": m.content} for m in messages[-50:]]
    final = app.invoke(
        {
            "messages": msg_dicts,
            "client_state": cs.model_dump(),
            "page_context": page_context.model_dump() if page_context else None,
            "planner": None,
            "filters": None,
            "cards": [],
            "tool_calls": [],
            "candidates_count": 0,
            "chroma_fallback": False,
            "tool_context": "",
            "reply": "",
            "updated_client_state": cs.model_dump(),
        }
    )
    updated = ChatClientState.model_validate(final.get("updated_client_state") or cs.model_dump())
    return (
        final.get("reply") or "",
        final.get("cards") or [],
        final.get("filters"),
        updated,
        final.get("tool_calls") or [],
    )
