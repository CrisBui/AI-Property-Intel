# AI Property Intelligence

Learning MVP — hệ thống thông minh thị trường & gợi ý phòng trọ quanh khu **Hà Nội**, kết hợp:

- **PostgreSQL** — lưu tin thô + dữ liệu có cấu trúc, filter cứng (giá, tiện ích)
- **ChromaDB** — vector search rerank
- **LLM (Groq/Gemini/OpenAI/Grok)** — trích xuất tin đăng & parse câu hỏi tự nhiên
- **LangGraph** — agent matching 4 bước
- **Firecrawl** — crawl tin thật từ **PhongTot.com**

> Dự án học tập (script-first), chưa production. Roadmap: Postgres ✅ → Crawl PhongTot ✅ → Port Java/Spring (chưa làm).

---

## Tính năng chính

| Tính năng | Mô tả |
|-----------|-------|
| **Ingest seed** | 33 file tin đăng thô tiếng Việt (`data/raw/`) |
| **Crawl PhongTot** | Tự discover link từ trang quận → crawl → lưu DB |
| **Extract (LLM)** | Trích xuất giá, quận, tiện ích, landmark |
| **Hybrid search** | SQL filter trước, vector rerank sau |
| **Match agent** | Hỏi tiếng Việt → top phòng + giải thích |
| **Market analyze** | Thống kê giá/tiện ích cho chủ trọ (không LLM) |
| **Web UI** | FastAPI + form đơn giản tại `:8000` |

---

## Kiến trúc

```
data/raw/*.txt ──ingest──► raw_listings (Postgres)
data/crawl/*.txt ─discover/crawl─► raw_listings
                                        │
                                        ▼ extract (LLM)
                                    listings (Postgres)
                                        │
                                        ▼ index
                                    Chroma (vectors)
                                        │
              Query NL ──match (LangGraph)──► Kết quả + giải thích
```

**Hybrid search:** giá và tiện ích lọc bằng **SQL**; Chroma chỉ xếp hạng trong tập đã lọc.

Chi tiết kỹ thuật: [`docs/summarize.md`](docs/summarize.md)  
Danh sách lệnh terminal: [`docs/commands.md`](docs/commands.md)

---

## Yêu cầu

- Python **3.11+**
- Docker (PostgreSQL)
- API keys (tùy bước):
  - **Groq** (hoặc Gemini/OpenAI/Grok) — `extract`, `match`
  - **Firecrawl** — `discover`, `crawl --source firecrawl`

---

## Cài đặt nhanh

```bash
git clone <repo-url> ai-property-intelligence
cd ai-property-intelligence

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# Sửa .env: GROQ_API_KEY, FIRECRAWL_API_KEY, DATABASE_URL

docker compose up -d
alembic upgrade head
```

---

## Chạy pipeline

### Seed data (lần đầu)

```bash
python -m property_intel.cli ingest
python -m property_intel.cli extract
python -m property_intel.cli index
```

### Crawl PhongTot (tin thật)

```bash
# 1. Cấu hình trang quận trong data/crawl/search_urls.txt
# 2. Discover link tin → data/crawl/urls.txt
python -m property_intel.cli discover --max-links 10

# 3. Crawl nội dung từng tin
python -m property_intel.cli crawl --source firecrawl

# 4. Extract + index
python -m property_intel.cli extract --platform phongtot --rate-limit 6
python -m property_intel.cli index
```

### Tìm kiếm & phân tích

```bash
python -m property_intel.cli match "Tìm trọ dưới 5 triệu gần Cầu Giấy có điều hòa"
python -m property_intel.cli analyze --landmark bach_khoa
python -m property_intel.cli serve    # http://127.0.0.1:8000
```

---

## Cấu trúc thư mục

```
ai-property-intelligence/
├── README.md                 # File này
├── docs/
│   ├── commands.md           # Tổng hợp lệnh terminal
│   └── summarize.md          # Tổng quan kỹ thuật chi tiết
├── docker-compose.yml        # PostgreSQL :5433
├── alembic/                  # DB migrations
├── data/
│   ├── raw/                  # 33 seed files .txt
│   ├── crawl/
│   │   ├── search_urls.txt   # URL trang quận (input discover)
│   │   └── urls.txt          # URL tin chi tiết (input crawl)
│   └── chroma/               # Vector index (runtime)
├── src/property_intel/
│   ├── cli.py                # Typer CLI
│   ├── config.py             # Settings từ .env
│   ├── llm.py                # LLM factory
│   ├── db/                   # SQLAlchemy models, session, migrations
│   ├── pipeline/
│   │   ├── ingest.py
│   │   ├── extract.py
│   │   ├── index.py
│   │   ├── match_query.py
│   │   ├── market_intel.py
│   │   └── crawl/            # discover, crawl, purge
│   ├── agents/
│   │   └── matching_graph.py # LangGraph 4 nodes
│   └── api/                  # FastAPI + static UI
└── pyproject.toml
```

---

## CLI — tóm tắt

| Lệnh | Mục đích |
|------|----------|
| `ingest` | Nạp seed `.txt` |
| `discover` | Trang quận → link tin PhongTot |
| `crawl` | Crawl URL → `raw_listings` |
| `extract` | LLM → `listings` |
| `index` | Embed Chroma |
| `match "..."` | Tìm phòng |
| `analyze` | Thống kê thị trường |
| `purge-nhatot` | Xóa dữ liệu NhaTot |
| `reset-phongtot` | Xóa PhongTot để crawl lại |
| `migrate-sqlite` | Migrate SQLite → Postgres |
| `serve` | Web UI |

Xem đầy đủ option và ví dụ: [`docs/commands.md`](docs/commands.md)

---

## API Web

| Method | Path | Mô tả |
|--------|------|-------|
| `GET` | `/` | Giao diện web |
| `GET` | `/health` | Health + ping DB |
| `POST` | `/api/match` | `{"query": "..."}` |
| `GET` | `/api/market?landmark=` | Báo cáo thị trường |

Crawl **không** có REST endpoint — chỉ chạy qua CLI job.

---

## Cấu hình (`.env`)

```env
LLM_PROVIDER=groq
GROQ_API_KEY=...
GROQ_MODEL=llama-3.1-8b-instant

DATABASE_URL=postgresql+psycopg://property_intel:property_intel@localhost:5433/property_intel
CHROMA_PATH=./data/chroma

FIRECRAWL_API_KEY=...
CRAWL_RATE_LIMIT_SECONDS=2.0
EXTRACT_RATE_LIMIT_SECONDS=6.0
EXTRACT_MAX_RETRIES=6
```

---

## Tech stack

| Thành phần | Vai trò |
|------------|---------|
| Python 3.11+, Pydantic v2 | Core |
| SQLAlchemy 2 + PostgreSQL 16 | Structured storage |
| Alembic | Migrations |
| ChromaDB | Local vector index |
| LangChain + LangGraph | LLM + matching agent |
| Typer | CLI |
| FastAPI + Uvicorn | Web API |
| Firecrawl | JS-heavy crawl |
| Groq | LLM inference (mặc định) |

---

## Schema dữ liệu (tóm tắt)

**`raw_listings`** — tin thô  
`source_id`, `body`, `source_platform` (`seed_file` | `phongtot`), `source_url`, `extracted`

**`listings`** — sau extract  
`title`, `price_vnd` (BIGINT), `district`, `amenities_json`, `near_landmarks_json`, …

**Chroma** — collection `listings`, id = `source_id`

---

## Roadmap

- [x] SQLite → PostgreSQL + Alembic
- [x] Crawl adapter Firecrawl
- [x] Discover + crawl PhongTot.com
- [ ] Mở rộng quận / tăng volume crawl
- [ ] Port API sang Java/Spring Boot (production)

---

## License & ghi chú

Dự án học tập nội bộ. Tuân thủ ToS của các nền tảng crawl (PhongTot, Firecrawl, Groq).  
Không commit file `.env` — chỉ dùng `.env.example` làm mẫu.
