# Tổng hợp lệnh Terminal — AI Property Intelligence

Tài liệu tham chiếu nhanh mọi lệnh dùng trong dự án.  
Chạy từ thư mục gốc dự án sau khi kích hoạt virtualenv:

```bash
cd ~/Documents/ai-property-intelligence
source .venv/bin/activate
```
// 9router --skip-update --no-browser --host 127.0.0.1
Cú pháp chung cho CLI:

python -m property_intel.cli serve
python -m property_intel.cli serve --host 0.0.0.0 --port 8000
```bash
python -m property_intel.cli <lệnh> [tùy-chọn]
# hoặc (sau pip install -e .)
property-intel <lệnh>
```

---

## 1. Thiết lập môi trường (chạy một lần)

| Lệnh | Tác dụng |
|------|----------|
| `python3 -m venv .venv` | Tạo virtualenv Python |
| `source .venv/bin/activate` | Kích hoạt virtualenv |
| `pip install -e .` | Cài dependencies + package `property_intel` |
| `cp .env.example .env` | Tạo file cấu hình local (điền API keys) |
| `docker compose up -d` | Khởi động PostgreSQL 16 (port **5433**) |
| `docker compose ps` | Kiểm tra container Postgres đang chạy |
| `docker compose down` | Dừng Postgres (giữ volume data) |
| `alembic upgrade head` | Áp dụng migration DB mới nhất |
| `alembic current` | Xem revision migration hiện tại |
| `alembic history` | Xem lịch sử migration |

---

## 2. Pipeline dữ liệu — lệnh chính

Luồng chuẩn:

```
ingest / discover → crawl → extract → index → match
```

### `ingest` — Nạp file seed

```bash
python -m property_intel.cli ingest
```

| | |
|---|---|
| **Input** | `data/raw/*.txt` (1 file = 1 tin đăng thô) |
| **Output** | Ghi vào bảng `raw_listings` (`source_platform = seed_file`) |
| **Cần LLM?** | Không |
| **Idempotent** | Có — file không đổi thì `skipped` |

---

### `discover` — Tự lấy link tin từ trang danh sách

```bash
python -m property_intel.cli discover
python -m property_intel.cli discover --max-links 10
python -m property_intel.cli discover -f data/crawl/search_urls.txt -o data/crawl/urls.txt
```

| Option | Mặc định | Tác dụng |
|--------|----------|----------|
| `--urls-file`, `-f` | `data/crawl/search_urls.txt` | File chứa URL **trang quận/khu** (search page) |
| `--output`, `-o` | `data/crawl/urls.txt` | File ghi **link tin chi tiết** |
| `--max-links` | `30` | Số link tối đa **mỗi trang search** |

| | |
|---|---|
| **Cách hoạt động** | Firecrawl mở từng URL trong `search_urls.txt` → lọc link PhongTot khớp pattern `...-tn123` → ghi vào `urls.txt` |
| **Cần LLM?** | Không |
| **Cần API key** | `FIRECRAWL_API_KEY` |

**Ví dụ `search_urls.txt`:**

```
https://phongtot.com/cho-thue-phong-tro-hn/quan-cau-giay
https://phongtot.com/cho-thue-phong-tro-hn/quan-nam-tu-liem
```

Với `--max-links 10` → tối đa 10 link/trang → thường ra ~10–20 URL trong `urls.txt`.

---

### `crawl` — Tải nội dung từng tin

```bash
python -m property_intel.cli crawl --source firecrawl
python -m property_intel.cli crawl --source firecrawl --rate-limit 3
python -m property_intel.cli crawl --source firecrawl --discover --max-links 10
python -m property_intel.cli crawl --source url-fetch -f data/crawl/urls.txt
```

| Option | Mặc định | Tác dụng |
|--------|----------|----------|
| `--source`, `-s` | `firecrawl` | `firecrawl` (JS-heavy) hoặc `url-fetch` (HTTP đơn giản) |
| `--urls-file`, `-f` | `data/crawl/urls.txt` | File danh sách URL tin chi tiết |
| `--rate-limit` | `CRAWL_RATE_LIMIT_SECONDS` (2s) | Delay giữa các request |
| `--discover` | `false` | Chạy `discover` trước rồi mới crawl |
| `--max-links` | `30` | Dùng với `--discover` |

| | |
|---|---|
| **Input** | `data/crawl/urls.txt` |
| **Output** | Bảng `raw_listings` (`source_platform = phongtot`, `source_url`, `body`) |
| **Lưu ý** | Chỉ crawl URL **phongtot.com** / **nhatot.com**; URL khác bị bỏ qua |
| **Ảnh** | Firecrawl lấy thêm `html` + `links` để gắn URL ảnh vào `body`. **Cần crawl lại** (không chỉ extract) nếu DB cũ chưa có ảnh |
| **Cần API key** | `firecrawl` cần `FIRECRAWL_API_KEY` |

---

### `extract` — LLM trích xuất field có cấu trúc

```bash
python -m property_intel.cli extract
python -m property_intel.cli extract --platform phongtot
python -m property_intel.cli extract --platform phongtot --rate-limit 10
```

| Option | Mặc định | Tác dụng |
|--------|----------|----------|
| `--platform`, `-p` | (tất cả) | Chỉ extract nguồn cụ thể: `phongtot`, `seed_file`, … |
| `--rate-limit` | `EXTRACT_RATE_LIMIT_SECONDS` (6s) | Delay trước mỗi lần gọi LLM (tránh Groq 429) |

| | |
|---|---|
| **Input** | `raw_listings` có `extracted = false` |
| **Output** | Bảng `listings` (title, price_vnd, district, amenities, …) |
| **Cần LLM?** | Có — `LLM_PROVIDER` + API key tương ứng |
| **`success=0`** | Không có tin pending — thường nghĩa là đã extract xong |

**Sau khi crawl lại để có ảnh:**

```bash
python -m property_intel.cli extract --platform nhatot --force
python -m property_intel.cli extract --platform phongtot --force
python -m property_intel.cli index
```

---

### Freshness (P5) — Ẩn tin cũ / hết hạn

Search UI và chat chỉ hiển thị tin **còn fresh** theo `last_seen_at` (crawl gần nhất) hoặc `posted_at` (NhaTot: *Cập nhật X giờ trước*).

| Biến `.env` | Mặc định | Tác dụng |
|-------------|----------|----------|
| `SEARCH_MAX_AGE_DAYS` | `7` | Ẩn tin không thấy lại / quá cũ hơn N ngày. `0` = tắt lọc |

**Luồng giữ tin mới:**

```bash
# 1. Crawl lại để cập nhật last_seen_at (+ ảnh nếu body cũ thiếu)
python -m property_intel.cli crawl --source firecrawl --rate-limit 3

# 2. Extract lại để cập nhật posted_at + images_json
python -m property_intel.cli extract --force

# 3. Re-index
python -m property_intel.cli index
```

Tin không xuất hiện trong crawl ≥ 7 ngày sẽ biến mất khỏi kết quả tìm kiếm (vẫn còn trong DB cho tới khi xóa thủ công).

---

### `index` — Embed vào Chroma

```bash
python -m property_intel.cli index
```

| | |
|---|---|
| **Input** | Bảng `listings` |
| **Output** | Vector index tại `data/chroma/`, cập nhật `indexed_at` |
| **Cần LLM?** | Không |
| **Bắt buộc trước** | `match` (hybrid search dùng Chroma) |

---

### `match` — Tìm phòng bằng ngôn ngữ tự nhiên

```bash
python -m property_intel.cli match "Tìm trọ dưới 5 triệu gần Cầu Giấy có điều hòa"
python -m property_intel.cli match "Phòng trọ Nam Từ Liêm dưới 4 triệu gần Mễ Trì"
```

| | |
|---|---|
| **Luồng** | Parse query (LLM) → SQL filter → Chroma rerank → giải thích (LLM) |
| **Cần LLM?** | Có |
| **Cần index?** | Có — chạy `index` trước |

---

### `analyze` — Thống kê thị trường (chủ trọ)

```bash
python -m property_intel.cli analyze
python -m property_intel.cli analyze --landmark bach_khoa
python -m property_intel.cli analyze -l kim_lien
```

| | |
|---|---|
| **Output** | Báo cáo text: giá min/avg/max, tiện ích phổ biến theo khu |
| **Cần LLM?** | Không — thuần SQL/thống kê |

---

### `serve` — Web UI + REST API

```bash
python -m property_intel.cli serve
python -m property_intel.cli serve --host 0.0.0.0 --port 8000
```

| Endpoint | Mô tả |
|----------|-------|
| `http://127.0.0.1:8000/` | Form web Match + Analyze |
| `GET /health` | Health check + ping DB |
| `POST /api/match` | `{"query": "..."}` |
| `GET /api/market?landmark=` | Báo cáo thị trường JSON |

---

## 3. Lệnh bảo trì / dọn dữ liệu

### `purge-nhatot` — Xóa dữ liệu NhaTot/Chotot

```bash
python -m property_intel.cli purge-nhatot
```

Xóa `raw_listings`, `listings`, và vector Chroma liên quan NhaTot/Chotot.  
**Giữ nguyên** seed file và PhongTot.

---

### `reset-phongtot` — Xóa PhongTot để crawl lại

```bash
python -m property_intel.cli reset-phongtot
```

Xóa toàn bộ dòng PhongTot trong DB + Chroma. Dùng khi body crawl sai và cần crawl lại từ đầu.

---

### `migrate-sqlite` — Copy SQLite → PostgreSQL (one-shot)

```bash
python -m property_intel.cli migrate-sqlite
python -m property_intel.cli migrate-sqlite --sqlite-url sqlite:///./data/app.db
```

Chỉ dùng khi migrate từ DB SQLite cũ sang Postgres.

---

## 4. Quy trình chạy mẫu

### A. Lần đầu — seed data

```bash
docker compose up -d
alembic upgrade head
cp .env.example .env          # điền GROQ_API_KEY, FIRECRAWL_API_KEY

python -m property_intel.cli ingest
python -m property_intel.cli extract
python -m property_intel.cli index
python -m property_intel.cli match "Tìm trọ dưới 3.5 triệu gần Bách Khoa"
```

### B. Crawl PhongTot (Cầu Giấy + Nam Từ Liêm)

```bash
# Bước 1: Lấy link tin từ trang quận
python -m property_intel.cli discover --max-links 10

# Bước 2: Crawl từng tin
python -m property_intel.cli crawl --source firecrawl

# Bước 3: Extract chỉ PhongTot (tránh queue NhaTot cũ)
python -m property_intel.cli extract --platform phongtot --rate-limit 6

# Bước 4: Index + test
python -m property_intel.cli index
python -m property_intel.cli match "Tìm trọ dưới 5 triệu gần Cầu Giấy có điều hòa"
```

### C. Gộp discover + crawl một lệnh

```bash
python -m property_intel.cli crawl --source firecrawl --discover --max-links 10
python -m property_intel.cli extract --platform phongtot
python -m property_intel.cli index
```

### C2. Crawl NhaTot (Hà Nội)

```bash
# Discover + crawl (search_urls.txt đã có trang NhaTot + PhongTot)
python -m property_intel.cli crawl --source firecrawl --discover --max-links 20

# Extract chỉ NhaTot (parser + LLM)
python -m property_intel.cli extract --platform nhatot --rate-limit 8

python -m property_intel.cli index
```

NhaTot listing URL dạng `.../thue-phong-tro-quan-<quận>-ha-noi/<id>.htm`. Dedup admin-review là phase sau — hiện không auto-merge trùng.

### D. Crawl lại PhongTot (body sai)

```bash
python -m property_intel.cli reset-phongtot
python -m property_intel.cli crawl --source firecrawl
python -m property_intel.cli extract --platform phongtot
python -m property_intel.cli index
```

---

## 5. SQL kiểm tra nhanh (DBeaver / psql)

Kết nối: `postgresql://property_intel:property_intel@localhost:5433/property_intel`

```sql
-- Phân loại raw theo nguồn
SELECT source_platform, extracted, COUNT(*)
FROM raw_listings
GROUP BY 1, 2
ORDER BY 1, 2;

-- Tin PhongTot đã extract
SELECT l.title, l.price_vnd, l.district, r.source_url
FROM listings l
JOIN raw_listings r ON l.source_id = r.source_id
WHERE r.source_platform = 'phongtot';

-- Đã index chưa
SELECT l.source_id, l.indexed_at IS NOT NULL AS indexed
FROM listings l
JOIN raw_listings r ON l.source_id = r.source_id
WHERE r.source_platform = 'phongtot';
```

---

## 6. Biến môi trường quan trọng (`.env`)

| Biến | Bắt buộc | Mô tả |
|------|----------|-------|
| `LLM_PROVIDER` | extract, match | `groq` / `gemini` / `openai` / `grok` |
| `GROQ_API_KEY` | Nếu dùng Groq | API key Groq |
| `DATABASE_URL` | Luôn | Postgres: `postgresql+psycopg://...@localhost:5433/property_intel` |
| `CHROMA_PATH` | Luôn | `./data/chroma` |
| `FIRECRAWL_API_KEY` | crawl/discover | API key Firecrawl |
| `CRAWL_RATE_LIMIT_SECONDS` | Khuyến nghị | Delay giữa request crawl (mặc định 2s) |
| `EXTRACT_RATE_LIMIT_SECONDS` | Khuyến nghị | Delay giữa LLM call (mặc định 6s — tránh 429) |
| `EXTRACT_MAX_RETRIES` | Tùy chọn | Số lần retry khi LLM lỗi (mặc định 6) |
| `SEARCH_MAX_AGE_DAYS` | Tùy chọn | Ẩn tin cũ hơn N ngày trong search/chat (mặc định 7, `0` = tắt) |
| `CHAT_SEARCH_TOP_K` | Tùy chọn | Số tin tối đa chat agent trả về mỗi lần search DB (mặc định 15) |

---

## 7. Bảng tóm tắt tất cả lệnh CLI

| Lệnh | Cần LLM | Cần Firecrawl | Mục đích ngắn |
|------|---------|---------------|---------------|
| `ingest` | Không | Không | Nạp seed `.txt` → DB |
| `discover` | Không | Có | Trang quận → link tin → `urls.txt` |
| `crawl` | Không | Tùy `--source` | Link tin → `raw_listings` |
| `extract` | Có | Không | Raw → structured `listings` |
| `index` | Không | Không | DB → Chroma vectors |
| `match` | Có | Không | Tìm phòng hybrid search |
| `analyze` | Không | Không | Thống kê thị trường |
| `purge-nhatot` | Không | Không | Xóa dữ liệu NhaTot |
| `reset-phongtot` | Không | Không | Xóa PhongTot để crawl lại |
| `migrate-sqlite` | Không | Không | SQLite → Postgres |
| `serve` | Tùy endpoint | Không | Web UI + API |

---

## 8. Xử lý lỗi thường gặp

| Triệu chứng | Nguyên nhân | Cách xử lý |
|-------------|-------------|------------|
| `429 Too Many Requests` khi extract | Groq rate limit | `--rate-limit 8` hoặc tăng `EXTRACT_RATE_LIMIT_SECONDS` |
| `success=0` khi extract | Đã extract hết | Query SQL kiểm tra `extracted=true` |
| Log vẫn thấy NhaTot / giá tỷ | DB còn NhaTot cũ | `purge-nhatot` rồi `extract --platform phongtot` |
| `Connection refused :5433` | Postgres chưa chạy | `docker compose up -d` |
| Crawl body toàn menu nav | Firecrawl lấy sidebar | `reset-phongtot` + crawl lại (code đã dùng `onlyMainContent`) |
| `match` không ra PhongTot | Chưa index | Chạy `index` sau extract |
