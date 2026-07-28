# Tenant Search UI + AI Chat — Design Spec

**Date:** 2026-07-28  
**Status:** Draft — pending user review  
**Decision:** Option B (filter UI + AI tab) + chatbot multi-turn; session storage Option C (browser MVP, `session_id` ready for server later)

---

## 1. Goals

Build a complete tenant-facing web experience for finding rental rooms in Hanoi:

1. **Tab “Tìm phòng”** — PhongTot-style filter search (district, price, area, room type) with card results. No LLM on this path (fast, deterministic).
2. **Tab “Trợ lý AI”** — Multi-turn chatbot that understands context, calls search/detail tools, returns grounded answers + inline listing cards.
3. **Backward compatibility** — Keep `POST /api/match` for CLI/dev; gradually superseded by `/api/chat`.

**Primary users:** Tenants searching for rooms (students, workers near ĐHBK and central Hanoi districts).

**Non-goals (v1):**

- User accounts / login
- Saved favorites persistence (v2)
- Map view (v2)
- Server-side chat history (v2 — API designed for it)
- Image gallery from crawl (placeholder in v1; parser enhancement in P4)

---

## 2. Information Architecture

```
/  (single-page app or multi-page static)
├── Tab: Tìm phòng
│   ├── Filter bar (district, price, area, room type, text q)
│   ├── Advanced filters (collapse): room amenities, building amenities, utility caps
│   ├── Sort + result count + pagination
│   └── Listing cards → detail drawer | external PhongTot link | “Hỏi AI”
└── Tab: Trợ lý AI
    ├── Chat thread (bubbles)
    ├── Inline listing cards in assistant messages
    └── Optional seed context from Tab 1 (filters / focused listing)
```

**Cross-tab flows:**

| From | Action | To |
|------|--------|-----|
| Search results | “Hỏi AI phân tích thêm” | Chat tab with `last_filters` + `last_results` in client state |
| Card | “Hỏi AI về tin này” | Chat tab with `focused_source_id` |
| Chat | Search tool returns listings | Same card component as Tab 1 |

---

## 3. Backend Architecture

### 3.1 Reuse existing pipeline

| Layer | Existing code | Role in new UI |
|-------|---------------|----------------|
| SQL hard filter | `sql_filter_listings()` in `match_query.py` | Core of `/api/search` |
| Chroma rerank | `chroma_rerank()` | Optional when `q` or `soft_rank=true` |
| Filter schema | `MatchFilters` in `models/listing.py` | Shared by search + chat tools |
| Listing row | `ListingRow` / Postgres | Source of truth |
| LLM | `llm.py` + 9Router | Chat agent only (not filter search) |

### 3.2 New modules (planned)

```
src/property_intel/
  api/
    app.py              # register new routes
    search.py           # SearchRequest/Response, search_listings handler
    listings.py         # GET /api/listings/{source_id}
    meta.py             # GET /api/meta/districts, presets
    chat.py             # POST /api/chat
    schemas/            # Pydantic DTOs for API (ListingCard, etc.)
  agents/
    chat_graph.py       # LangGraph multi-turn agent + tools
  pipeline/
    search_service.py   # sql filter + sort + paginate + optional chroma
```

### 3.3 API Endpoints

#### `GET /api/meta/districts`

Returns filter metadata for UI bootstrapping.

```json
{
  "districts": ["Ba Đình", "Cầu Giấy", "Nam Từ Liêm", ...],
  "price_presets": [
    {"id": "under_3m", "label": "Dưới 3 triệu", "min": null, "max": 3000000},
    {"id": "3_5m", "label": "3 - 5 triệu", "min": 3000000, "max": 5000000}
  ],
  "area_presets": [
    {"id": "under_20", "label": "Dưới 20m²", "min": null, "max": 20},
    {"id": "20_30", "label": "20 - 30m²", "min": 20, "max": 30}
  ],
  "room_layout_options": [
    {"id": "studio", "label": "Studio", "tags": ["studio"]},
    {"id": "1bed", "label": "1 phòng ngủ", "tags": ["1_ngu_1_khach"]},
    {"id": "2bed", "label": "2 phòng ngủ", "tags": ["2_phong_ngu"]}
  ],
  "amenity_options": [
    {"id": "bep", "label": "Bếp"},
    {"id": "dieu_hoa", "label": "Điều hòa"}
  ]
}
```

#### `POST /api/search`

Structured search — **no LLM**.

**Request:**

```json
{
  "districts": ["Cầu Giấy", "Ba Đình"],
  "price_min": 0,
  "price_max": 5000000,
  "area_min_m2": 20,
  "area_max_m2": 40,
  "room_layout_tags": ["studio"],
  "amenities_required": ["bep"],
  "common_amenities_required": ["thang máy"],
  "electricity_max_vnd_per_kwh": 4000,
  "water_max_vnd_per_person": 150000,
  "water_max_vnd_per_m3": null,
  "q": "ĐHBK",
  "sort": "price_asc",
  "page": 1,
  "size": 20,
  "soft_rank": false
}
```

**Response:**

```json
{
  "total": 12,
  "page": 1,
  "size": 20,
  "filters_applied": { ... },
  "items": [ /* ListingCard[] */ ]
}
```

**`ListingCard` fields:**

| Field | Source |
|-------|--------|
| `source_id` | listings |
| `title`, `district`, `address_text` | listings |
| `price_vnd`, `area_min_m2`, `area_max_m2` | listings |
| `room_layout_tags`, `amenities` | JSON columns |
| `common_amenities` | common_amenities_json |
| `service_fees_summary` | formatted strings |
| `contact_phone`, `source_url` | listings |
| `short_description` | listings |
| `thumbnail_url` | images_json[0] or null |
| `images` | images_json (v1 empty) |

**Sort options:** `price_asc`, `price_desc`, `area_desc`, `area_asc`, `relevance` (only when `soft_rank=true` + `q` set).

**Multi-district:** extend `sql_filter_listings` with `districts: list[str]` — row passes if district in list (OR). Single `district` on `MatchFilters` remains for chat/legacy.

#### `GET /api/listings/{source_id}`

Full detail for drawer/modal and chat tool.

Returns all `ListingCard` fields plus `description_long`, `building`, raw `service_fees`, `near_landmarks`, `price_note`.

#### `POST /api/chat`

Multi-turn assistant.

**Request:**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "messages": [
    {"role": "user", "content": "Tìm phòng Cầu Giấy dưới 5 triệu có bếp"}
  ],
  "client_state": {
    "last_filters": null,
    "last_result_ids": [],
    "focused_source_id": null
  }
}
```

**Response:**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "reply": "Có 8 phòng phù hợp...",
  "cards": [ /* ListingCard[] top 5 */ ],
  "filters_applied": { ... },
  "client_state": {
    "last_filters": { ... },
    "last_result_ids": ["phongtot_abc", ...],
    "focused_source_id": null
  },
  "tool_calls": ["search_listings"]
}
```

**Session model (Option C):**

- **MVP:** Server is stateless for chat. Client stores `messages[]` + `client_state` in `sessionStorage` under key `property_intel_chat_{session_id}`. Client generates `session_id` (UUID v4) on first message and sends full history each request.
- **v2:** Same API; server persists by `session_id` in `chat_sessions` table when user auth exists. Client can send only the latest message + `session_id`.

#### `POST /api/match` (unchanged)

Keep for CLI and existing `index.html` until Tab 2 replaces it.

---

## 4. Chat Agent Design

### 4.1 Graph nodes

```
entry → route_intent (LLM)
          ├─ need_search → run_search_tool → respond
          ├─ need_detail → run_get_listing_tool → respond
          ├─ compare (v2) → ...
          └─ chitchat / clarify → respond
```

### 4.2 Tools

| Tool | Input | Output |
|------|-------|--------|
| `search_listings` | Partial `MatchFilters` + optional `q` | `{ total, items[] }` |
| `get_listing` | `source_id` | Full listing detail |

**Filter merge rule:** New tool args merge over `client_state.last_filters` (e.g. user says “rẻ hơn” → lower `price_max` from previous).

**Reference resolution:** When user says “cái thứ 2”, “Happyhomes Hồ Tùng Mậu”, resolve against `client_state.last_result_ids` and titles before calling `get_listing`.

### 4.3 Grounding rules

Same as current `EXPLAIN_SYSTEM_PROMPT`:

- Only facts from tool results
- State district explicitly
- No invented listings or market stats
- If SQL returns 0 and fallback used, say so

### 4.4 LLM calls per chat turn

Typically 1–2 calls: intent/routing (optional) + final response. Tool execution is Python (no LLM).

---

## 5. Frontend Design

### 5.1 Stack

Extend FastAPI static assets (Option A):

- `static/app.html` — shell with tabs
- `static/css/app.css`
- `static/js/search.js`, `static/js/chat.js`, `static/js/components/cards.js`
- Shared fetch helpers

No new npm build step for v1.

### 5.2 Tab “Tìm phòng” layout

**Desktop:**

- Top: horizontal filter bar (district multi-select, price/area dropdowns with presets + slider in panel)
- Left sidebar (optional): price slider duplicate + “Bộ lọc nâng cao”
- Main: result header + sort dropdown + cards grid (1 col mobile, 2 col tablet+)

**Mobile:**

- Filter button → full-screen drawer
- Cards full width

**Empty state:** “Không tìm thấy phòng — thử nới rộng giá hoặc chọn thêm quận.”

### 5.3 Tab “Trợ lý AI” layout

- Message list (user right, assistant left)
- Assistant messages may embed 1–5 mini cards
- Input bar + send
- “Xóa hội thoại” clears sessionStorage

### 5.4 sessionStorage schema

```json
{
  "session_id": "uuid",
  "messages": [{"role": "user|assistant", "content": "...", "cards": []}],
  "client_state": {
    "last_filters": {},
    "last_result_ids": [],
    "focused_source_id": null
  },
  "updated_at": "ISO8601"
}
```

Key: `property_intel_chat_v1`

---

## 6. Database Changes

### 6.1 Required for v1

**None.** Existing `listings` schema supports filter search and chat tools.

### 6.2 Recommended (P4)

Migration `005_listing_images.py`:

```sql
ALTER TABLE listings ADD COLUMN images_json JSONB DEFAULT '[]';
```

Parser: extract `/imgs/` URLs from PhongTot markdown into `images_json`.

### 6.3 Future (v2 chat persistence)

```sql
CREATE TABLE chat_sessions (
  id UUID PRIMARY KEY,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  messages_json JSONB NOT NULL,
  client_state_json JSONB NOT NULL
);
```

Not implemented in MVP.

### 6.4 Multi-district filter

Code-only change to `MatchFilters`:

```python
districts: list[str] = Field(default_factory=list)  # new
district: str | None = None  # keep for NL parse / legacy
```

`sql_filter_listings`: if `districts` non-empty, match any; else use single `district`.

---

## 7. Filter Presets (UI constants)

**Price (VND/month):**

| Label | min | max |
|-------|-----|-----|
| Tất cả | 0 | 20_000_000 |
| Dưới 3 triệu | — | 3_000_000 |
| 3 - 5 triệu | 3_000_000 | 5_000_000 |
| 5 - 7 triệu | 5_000_000 | 7_000_000 |
| 7 - 10 triệu | 7_000_000 | 10_000_000 |
| 10 - 15 triệu | 10_000_000 | 15_000_000 |
| Trên 15 triệu | 15_000_000 | — |

**Area (m²):**

| Label | min | max |
|-------|-----|-----|
| Tất cả | — | — |
| Dưới 20m² | — | 20 |
| 20 - 30m² | 20 | 30 |
| 30 - 40m² | 30 | 40 |
| Trên 40m² | 40 | — |

**Districts:** subset of `HANOI_DISTRICT_SLUGS` values focused on central Hanoi (Cầu Giấy, Nam Từ Liêm, Ba Đình, Hà Đông, Đống Đa, Bắc Từ Liêm, Thanh Xuân, Tây Hồ, Hoàng Mai, Hai Bà Trung).

---

## 8. Text search (`q`)

**MVP:** SQL `ILIKE` on `title`, `address_text`, `short_description`, and joined `near_landmarks_json` text.

**Optional enhancement:** When `q` is non-empty and `soft_rank=true`, run Chroma rerank on SQL candidates (reuse `chroma_rerank` with empty extra filters).

---

## 9. Error Handling

| Case | UX |
|------|-----|
| DB down | 503 + “Hệ thống đang bảo trì” |
| LLM unavailable (chat only) | 503 on `/api/chat`; Tab 1 still works |
| 0 results | Empty state + suggest widening filters |
| Invalid filter values | 422 with field errors |
| Chat rate limit | Retry message + disable send briefly |

---

## 10. Implementation Phases

| Phase | Scope | Est. |
|-------|-------|------|
| **P1** | `search_service.py`, `POST /api/search`, `GET /api/meta/*`, Tab 1 UI | Core |
| **P2** | `GET /api/listings/{id}`, detail drawer, card component | Core |
| **P3** | `chat_graph.py`, `POST /api/chat`, Tab 2 UI, sessionStorage | Core |
| **P4** | images_json + parser, cross-tab “Hỏi AI”, compare tool | Enhancement |

**P1 acceptance criteria:**

- User selects Cầu Giấy + 3–5tr + Studio → sees paginated cards matching SQL filter
- No LLM invoked
- Response time dominated by DB (<500ms local)

**P3 acceptance criteria:**

- Multi-turn: search → “cái thứ 2 điện bao nhiêu?” → correct listing fee
- “Rẻ hơn” adjusts price and re-searches
- Refresh page restores chat from sessionStorage
- `session_id` in API ready for server persistence

---

## 11. Security & Limits

- Max `messages` per chat request: 50 (truncate oldest)
- Max message length: 2000 chars
- Rate limit chat: configurable (reuse extract rate limit pattern)
- No PII stored server-side in MVP
- `source_url` opens external PhongTot in new tab

---

## 12. Open Items (none blocking MVP)

- Duplex room type mapping (may map to custom tag when data exists)
- `vacant_rooms` badge — skip v1
- Deprecate old `index.html` after P3

---

## 13. Spec Self-Review

- [x] No TBD placeholders
- [x] Architecture consistent (search = no LLM, chat = LLM + tools)
- [x] Scoped to single implementation plan (phased)
- [x] Session Option C explicitly specified
- [x] DB migration optional deferred to P4

---

## 14. Approval

User selected **B + chatbot** and session storage **C**.

**Next step after approval:** Invoke `writing-plans` skill to produce file-level implementation plan.
