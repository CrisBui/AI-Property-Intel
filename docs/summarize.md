# Tổng quan dự án AI Property Intelligence (trạng thái hiện tại)

Learning MVP — pipeline **script-first**, bọc **LangGraph** cho matching, **crawl adapter** (Firecrawl / URL fetch), **không production**.

---

## 1. Toàn bộ những gì dự án đã có

### Cấu trúc thư mục

```
ai-property-intelligence/
├── .env / .env.example          # config + API keys
├── .gitignore
├── docker-compose.yml           # Postgres 16 (port 5433)
├── alembic.ini + alembic/       # DB migrations
├── pyproject.toml               # deps + entry point
├── data/
│   ├── raw/                     # 33 file seed .txt (tin đăng thô)
│   ├── crawl/                   # URL list cho crawl (urls.txt)
│   ├── app.db                   # SQLite legacy (gitignore)
│   └── chroma/                  # vector index runtime (gitignore)
└── src/property_intel/
    ├── config.py                # Settings từ .env
    ├── llm.py                   # Factory LLM multi-provider
    ├── cli.py                   # 8 lệnh CLI
    ├── models/
    │   ├── listing.py           # Listing, MatchFilters, MatchResult
    │   └── market.py            # MarketReport, AreaMarketStats
    ├── db/
    │   ├── models.py            # SQLAlchemy: raw_listings, listings
    │   ├── session.py           # Engine Postgres/SQLite + pool
    │   ├── migrate_sqlite.py    # One-shot SQLite → Postgres
    │   └── json_utils.py        # JSONB / Text compat
    ├── pipeline/
    │   ├── ingest.py            # Đọc .txt → raw_listings
    │   ├── extract.py           # LLM → listings structured
    │   ├── index.py             # DB → Chroma embeddings
    │   ├── match_query.py       # Hybrid SQL + Chroma
    │   ├── market_intel.py      # Thống kê thị trường (chủ trọ)
    │   └── crawl/               # Crawl adapter (Firecrawl, url-fetch)
    ├── agents/
    │   └── matching_graph.py    # LangGraph 4 node
    └── api/
        ├── app.py               # FastAPI REST + UI
        └── static/index.html    # Form web đơn giản
```

### 8 lệnh CLI

| Lệnh | Cần LLM? | Mục đích |
|------|----------|----------|
| `ingest` | Không | Nạp file `.txt` seed → `raw_listings` |
| `crawl` | Không* | Crawl URL list → `raw_listings` (async job CLI) |
| `extract` | Có | LLM trích xuất field có cấu trúc |
| `index` | Không | Embed vào Chroma |
| `match "query"` | Có | Tìm phòng (hybrid + LangGraph + giải thích) |
| `analyze [--landmark]` | Không | Báo cáo thị trường cho chủ trọ |
| `migrate-sqlite` | Không | One-shot copy SQLite → Postgres |
| `serve` | Tùy endpoint | Web UI + API tại `:8000` |

\* `crawl --source firecrawl` cần `FIRECRAWL_API_KEY`

### API Web (FastAPI)

| Endpoint | Input | Output |
|----------|-------|--------|
| `GET /` | — | HTML form (Match + Analyze) |
| `GET /health` | — | `{"status":"ok"}` (+ ping DB) |
| `POST /api/match` | `{"query":"..."}` | `{"query","answer"}` |
| `GET /api/market?landmark=` | query param tùy chọn | `{"landmark","report_text","total_listings"}` |

**Không có** endpoint crawl sync — crawl chỉ qua CLI job.

### Dữ liệu seed

- **33 file** `data/raw/tr001_*.txt` → `tr033_*.txt`
- Tiếng Việt, lộn xộn, quanh khu ĐHBK/Bách Khoa/Kim Liên
- Filename stem = `source_id` (unique key xuyên suốt pipeline)
- **33 tin** đã ingest + extract + index trên Postgres

### Tech stack

| Thành phần | Vai trò |
|------------|---------|
| **Python 3.11+** | Ngôn ngữ chính |
| **Pydantic v2** | Schema validate (Listing, filters, market report) |
| **pydantic-settings** | Đọc `.env` |
| **SQLAlchemy 2 + PostgreSQL 16** | Lưu raw + structured; **SQL filter cứng** |
| **Alembic** | Schema migrations |
| **psycopg 3** | Postgres driver |
| **ChromaDB** | Vector local; **rerank mềm** |
| **LangChain** | Structured output LLM (extract + parse query) |
| **LangGraph** | Agent matching 4 node |
| **Typer** | CLI |
| **FastAPI + Uvicorn** | Web UI + REST API |
| **Firecrawl** (tùy chọn) | Crawl trang JS-heavy (Chợ Tốt, …) |
| **Groq** (hiện tại) | `llama-3.1-8b-instant` — cũng hỗ trợ OpenAI/Gemini/Grok |

---

## 2. Kiến trúc đã áp dụng

### Nguyên tắc thiết kế

1. **Script-first → Agent wrap** — logic nằm trong `pipeline/*.py`; LangGraph chỉ gọi lại, không duplicate.
2. **Hybrid search bắt buộc** — filter cứng (giá, tiện ích, landmark) qua **SQL trước**; vector **sau** (rerank / fallback).
3. **Schema sạch** — Pydantic contract tách khỏi DB; sau này port Java/Spring dễ hơn.
4. **Learning MVP** — seed file + crawl adapter; Postgres local Docker; không auth production.

### Phân lớp

```
┌─────────────────────────────────────────────────────────┐
│  Interface: CLI (Typer)  |  Web (FastAPI + HTML)        │
├─────────────────────────────────────────────────────────┤
│  Agent: matching_graph (LangGraph 4 nodes)              │
├─────────────────────────────────────────────────────────┤
│  Pipeline: crawl | ingest | extract | index | match     │
│            | market_intel                               │
├─────────────────────────────────────────────────────────┤
│  LLM: llm.py (provider factory)                         │
├─────────────────────────────────────────────────────────┤
│  Storage: PostgreSQL (structured) + Chroma (vectors)    │
├─────────────────────────────────────────────────────────┤
│  Input: data/raw/*.txt (seed) | crawl URLs (Firecrawl)  │
└─────────────────────────────────────────────────────────┘
```

### Schema dữ liệu chính

**Pydantic `Listing`** (sau extract):

- `source_id`, `title`, `description_raw`
- `price_vnd`, `area_m2`, `district`, `address_text`, `lat`, `lng`
- `amenities[]` — chuẩn hóa: `may_giat`, `bep`, `dieu_hoa`, `nong_lanh`, `ban_cong`
- `near_landmarks[]` — ví dụ: `bach_khoa`, `dhbk`, `kim_lien`
- `extract_confidence`, `posted_at`, `sentiment_notes`

**PostgreSQL `raw_listings`:**

- `source_id` (unique), `body`, `ingested_at`, `extracted`, `extract_status`
- `source_platform` — `seed_file` | `firecrawl` | `url_fetch`
- `source_url`, `crawled_at`, `last_seen_at`

**PostgreSQL `listings`:**

- Mirror Listing; `amenities_json` / `near_landmarks_json` = **JSONB**

**Chroma collection `listings`:**

- Document: `title + description_raw + amenities`
- Metadata: `source_id`, `price_vnd`, `district`, …
- Id = `source_id` (idempotent re-index)

---

## 3. Luồng hoạt động chính

### Pipeline A — Chuẩn bị dữ liệu (chạy tuần tự)

```
data/raw/*.txt
    → ingest        → raw_listings (Postgres, platform=seed_file)

data/crawl/urls.txt
    → crawl         → raw_listings (Postgres, platform=firecrawl|url_fetch)

raw_listings (chưa extracted)
    → extract       → listings (Postgres) via LLM
    → index         → Chroma collection "listings"
```

### Pipeline B — Matching người thuê

```
Query NL
    → parse_filters       (LLM → MatchFilters)
    → hybrid_search       (SQL filter + Chroma rerank)
    → format_answer       (Top-K + rationale)
    → explain_answer      (LLM grounded summary)
    → Output
```

**LangGraph 4 node:** `parse_filters` → `hybrid_search` → `format_answer` → `explain_answer`

### Pipeline C — Phân tích chủ trọ (không LLM)

```
listings (Postgres)
    → compute_market_report
    → Báo cáo text: giá min/avg/max, tiện ích phổ biến theo khu
```

---

## 4. Đầu vào — yêu cầu & định dạng

### 4.1 Seed file (`data/raw/*.txt`)

| Yêu cầu | Chi tiết |
|---------|----------|
| Định dạng | Plain text tiếng Việt, 1 file = 1 tin |
| Tên file | `{source_id}.txt` — ví dụ `tr001_bach_khoa_bep.txt` |
| Nội dung | Tin đăng thô: giá có/không rõ, tiện ích có/không, địa chỉ rõ/mơ hồ |

### 4.2 Crawl URL list (`data/crawl/urls.txt`)

| Yêu cầu | Chi tiết |
|---------|----------|
| Định dạng | 1 URL/dòng; dòng `#` = comment |
| Nguồn | Chợ Tốt, Batdongsan, … (trang JS → dùng Firecrawl) |
| `source_id` | `{platform}_{sha256(url)[:12]}` — dedup tự động |

### 4.3 Environment (`.env`)

| Biến | Bắt buộc | Mô tả |
|------|----------|-------|
| `LLM_PROVIDER` | Có (extract/match) | `groq` / `gemini` / `openai` / `grok` |
| `GROQ_API_KEY` | Nếu dùng Groq | API key |
| `DATABASE_URL` | Có | `postgresql+psycopg://...@localhost:5433/property_intel` |
| `CHROMA_PATH` | Có | `./data/chroma` |
| `FIRECRAWL_API_KEY` | Nếu crawl Firecrawl | API key Firecrawl |
| `CRAWL_RATE_LIMIT_SECONDS` | Khuyến nghị | Delay giữa các request (mặc định 2.0) |

### 4.4 Query matching / Analyze

Giữ nguyên như trước — xem CLI `match`, `analyze`.

---

## 5. Xử lý — từng bước làm gì

### `ingest` (idempotent)

1. Đọc `data/raw/*.txt`
2. `source_id` = tên file (stem); `source_platform = seed_file`
3. Upsert `raw_listings`: insert / update body / skip

### `crawl` (CLI job, không sync HTTP)

1. Đọc URL list từ `--urls-file` (mặc định `data/crawl/urls.txt`)
2. Adapter `CrawlSource`: `firecrawl` hoặc `url-fetch`
3. Rate limit giữa requests; log lỗi từng URL, tiếp tục batch
4. Upsert `raw_listings` by `source_id`; cập nhật `last_seen_at`
5. Body đổi → `extracted=false`, `extract_status=pending`

### `extract` / `index` / `match` / `analyze`

Logic giữ nguyên; storage = Postgres thay SQLite.

### Postgres setup

```bash
docker compose up -d
alembic upgrade head
python -m property_intel.cli migrate-sqlite   # one-shot từ SQLite cũ
```

---

## 6. Đầu ra — mỗi bước trả gì

| Bước | Output | Ví dụ |
|------|--------|-------|
| **ingest** | Stats CLI | `inserted=0 updated=0 skipped=33` |
| **crawl** | Stats CLI | `inserted=5 updated=1 skipped=2 failed=0` |
| **extract** | Stats CLI | `success=8 failed=0` |
| **index** | Stats CLI | `indexed=33` |
| **match** | Text block | Filters + Top 5 + `Giải thích:` |
| **analyze** | Báo cáo text | Giá min/avg/max theo khu |
| **migrate-sqlite** | Stats CLI | `raw_listings=33 listings=33` |
| **serve** | HTTP | UI + JSON API |

---

## 7. Map file ↔ chức năng

| File | Pipeline |
|------|----------|
| `pipeline/ingest.py` | Ingest seed files |
| `pipeline/crawl/base.py` | CrawlSource adapter |
| `pipeline/crawl/firecrawl.py` | Firecrawl scrape |
| `pipeline/crawl/url_fetch.py` | Simple HTTP fetch |
| `pipeline/crawl/runner.py` | Upsert + rate limit |
| `pipeline/extract.py` | Extract |
| `pipeline/index.py` | Index |
| `pipeline/match_query.py` | Parse + SQL + Chroma |
| `agents/matching_graph.py` | LangGraph |
| `pipeline/market_intel.py` | Analyze |
| `db/migrate_sqlite.py` | SQLite → Postgres |
| `api/app.py` | Web/API |
| `docker-compose.yml` | Postgres 16 |

---

## 8. Chưa có (đã hoãn theo spec)

- Apify actor Chợ Tốt (phase 2 crawl)
- Crawl Facebook (ToS / phức tạp)
- Pinecone / production deploy
- Auth, dashboard production
- Port Java/Spring
- Test suite pytest (verify bằng CLI/E2E)

---

## 9. Trạng thái runtime hiện tại

| Thành phần | Trạng thái |
|------------|------------|
| Postgres (Docker :5433) | Running |
| Seed files | 33 file |
| `raw_listings` | 33 bản ghi (Postgres) |
| `listings` | 33 extracted |
| Chroma index | 33 documents |
| Crawl | Adapter sẵn sàng; cần URL list + API key |

---

## 10. Cách chạy nhanh

```bash
cd ~/Documents/ai-property-intelligence
source .venv/bin/activate
cp .env.example .env   # điền API keys

# Postgres
docker compose up -d
alembic upgrade head

# Pipeline seed
python -m property_intel.cli ingest
python -m property_intel.cli extract
python -m property_intel.cli index

# Crawl (optional — cần urls.txt + FIRECRAWL_API_KEY)
python -m property_intel.cli crawl --source firecrawl
python -m property_intel.cli extract
python -m property_intel.cli index

# Matching
python -m property_intel.cli match "Tìm trọ dưới 3.5 triệu gần Bách Khoa có sẵn bếp"
python -m property_intel.cli analyze --landmark bach_khoa
python -m property_intel.cli serve   # http://127.0.0.1:8000
```

---

## 11. Hybrid search — tóm tắt

```
Query → parse_filters → sql_filter_listings (Postgres)
      → chroma_rerank → format_answer → explain_answer
```

**Nguyên tắc:** Giá và tiện ích **không** dùng vector — chỉ SQL. Chroma chỉ xếp hạng trong tập đã lọc.
