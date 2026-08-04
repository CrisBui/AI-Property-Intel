# ERD — AI Property Intelligence

Tài liệu mô tả schema dữ liệu hiện tại (PostgreSQL + Chroma).  
Cập nhật theo migration Alembic `001` → `005`.

---

## Tổng quan

| Store | Vai trò |
|-------|---------|
| **PostgreSQL** (`property_intel@localhost:5433`) | Tin thô + tin có cấu trúc |
| **Chroma** (`./data/chroma/`, collection `listings`) | Vector index cho hybrid search |
| **SQLite** (`data/app.db`) | Legacy — không dùng khi `DATABASE_URL` trỏ Postgres |

**Quan hệ chính:** `raw_listings.source_id` ↔ `listings.source_id` (1 : 0..1, **không có FK** trong DB).

---

 

## Luồng dữ liệu (pipeline)

```mermaid
flowchart LR
    subgraph ingest [Ingest / Crawl]
        SEED[seed .txt] --> RAW
        CRAWL[Firecrawl] --> RAW[(raw_listings)]
    end

    subgraph extract [Extract]
        RAW -->|LLM + parser| LST[(listings)]
    end

    subgraph index [Index]
        LST -->|index.py| CHR[(Chroma)]
    end

    subgraph api [API]
        LST --> UI[Search / Detail]
        RAW -->|fallback body, images| UI
        CHR -->|chroma_rerank| MATCH[Match / Chat]
        LST --> MATCH
    end
```

---

## Bảng `raw_listings`

Nguồn: migration `001`, `002` · Model: `src/property_intel/db/models.py` → `RawListingRow`

| Cột | Kiểu | Null | Mô tả |
|-----|------|------|-------|
| `id` | SERIAL | NO | PK surrogate |
| `source_id` | VARCHAR(128) | NO | **UK** — khóa nghiệp vụ (`phongtot_abc`, `nhatot_xyz`) |
| `body` | TEXT | NO | Nội dung crawl (markdown/HTML đã strip) |
| `source_platform` | VARCHAR(32) | NO | `seed_file` \| `phongtot` \| `nhatot` |
| `source_url` | VARCHAR(1024) | YES | URL tin gốc |
| `crawled_at` | TIMESTAMPTZ | YES | Thời điểm crawl lần cuối (body đổi) |
| `last_seen_at` | TIMESTAMPTZ | YES | Thấy lại URL khi crawl (P5 freshness) |
| `ingested_at` | TIMESTAMPTZ | NO | default `now()` |
| `extracted` | BOOLEAN | NO | default `false` |
| `extract_status` | VARCHAR(32) | YES | `pending`, `success`, … |

**Index / constraint:** PK(`id`), UNIQUE(`source_id`).

---

## Bảng `listings`

Nguồn: migration `001`, `003`, `004`, `005` · Model: `ListingRow`

### Scalar columns

| Cột | Kiểu | Null | Mô tả |
|-----|------|------|-------|
| `id` | SERIAL | NO | PK surrogate |
| `source_id` | VARCHAR(128) | NO | **UK** — trùng `raw_listings.source_id` |
| `title` | VARCHAR(512) | NO | Tiêu đề hiển thị |
| `description_raw` | TEXT | NO | Mô tả rút gọn cho index/LLM |
| `price_vnd` | **BIGINT** | YES | Giá thuê/tháng (VND) — migration `003` |
| `area_m2` | FLOAT | YES | Diện tích đơn (legacy) |
| `area_min_m2` | FLOAT | YES | Diện tích min |
| `area_max_m2` | FLOAT | YES | Diện tích max |
| `district` | VARCHAR(128) | YES | Quận Hà Nội (chuẩn hóa) |
| `address_text` | VARCHAR(512) | YES | Địa chỉ text |
| `lat` / `lng` | FLOAT | YES | Tọa độ (nếu có) |
| `source_url` | VARCHAR(1024) | YES | Link nguồn |
| `contact_phone` | VARCHAR(32) | YES | SĐT |
| `short_description` | TEXT | YES | Tóm tắt card |
| `description_long` | TEXT | YES | Mô tả chi tiết (UI drawer) |
| `price_note` | VARCHAR(512) | YES | Ghi chú giá (`Từ X`, …) |
| `sentiment_notes` | TEXT | YES | Ghi chú LLM |
| `extract_confidence` | FLOAT | NO | default `0` |
| `posted_at` | TIMESTAMPTZ | YES | Parse từ “Cập nhật X giờ trước” (P5) |
| `indexed_at` | TIMESTAMPTZ | YES | Lần embed Chroma gần nhất |

### JSONB columns (embedded, không tách bảng)

| Cột | Default | Nội dung |
|-----|---------|----------|
| `amenities_json` | `[]` | Tiện ích phòng: `bep`, `dieu_hoa`, `may_giat`, … |
| `near_landmarks_json` | `[]` | Landmark gần: `bach_khoa`, `me_tri`, … |
| `common_amenities_json` | `[]` | Tiện ích chung / nội thất (text VN) |
| `room_layout_tags_json` | `[]` | `studio`, `1_ngu_1_khach`, `co_bep`, … |
| `service_fees_json` | `{}` | Phí dịch vụ — xem schema bên dưới |
| `building_json` | `{}` | Thông tin tòa nhà — xem schema bên dưới |
| `images_json` | `[]` | Danh sách URL ảnh (migration `005`) |

**Index / constraint:** PK(`id`), UNIQUE(`source_id`).

---

## Schema JSONB — `service_fees_json`

Tham chiếu: `src/property_intel/pipeline/service_fees_utils.py`, `match_query.py`

```json
{
  "electricity_vnd_per_kwh": 4000,
  "water_vnd_per_m3": 35000,
  "water_vnd_per_person": 100000,
  "water_unit": "per_m3 | per_person | included | unknown",
  "water_raw": "string fallback",
  "internet_vnd_per_room": 50000,
  "laundry_vnd_per_person": 50000,
  "sanitation_vnd_per_person": 100000,
  "other_vnd_per_person": 100000
}
```

---

## Schema JSONB — `building_json`

```json
{
  "floor_count": 6,
  "room_count": 15,
  "renovation_year": 2024,
  "deposit_vnd": 2900000
}
```

---

## Schema JSONB — arrays

**`amenities_json`** — snake_case enum:

`bep`, `dieu_hoa`, `may_giat`, `nong_lanh`, `ban_cong`, …

**`room_layout_tags_json`:**

`studio`, `1_ngu_1_khach`, `2_phong_ngu`, `co_bep`, `gan_thang_may`, …

**`images_json`:**

```json
["https://cdn.chotot.com/...", "https://www.phongtot.com/imgs/..."]
```

---

## ERD — JSONB value objects (logical)

```mermaid
erDiagram
    LISTINGS ||--|| SERVICE_FEES : "service_fees_json"
    LISTINGS ||--|| BUILDING : "building_json"
    LISTINGS ||--|| AMENITY_TAGS : "amenities_json"
    LISTINGS ||--|| IMAGE_URLS : "images_json"

    SERVICE_FEES {
        int electricity_vnd_per_kwh
        int water_vnd_per_m3
        int water_vnd_per_person
        string water_unit
        int internet_vnd_per_room
        int laundry_vnd_per_person
    }

    BUILDING {
        int floor_count
        int room_count
        int renovation_year
        int deposit_vnd
    }

    AMENITY_TAGS {
        string array
    }

    IMAGE_URLS {
        string array
    }
```

---

## Chroma (ngoài Postgres)

File: `src/property_intel/pipeline/index.py`

| Field | Giá trị |
|-------|---------|
| Collection | `listings` |
| Document ID | `source_id` (trùng listings) |
| Document text | Ghép title, district, address, descriptions, amenities, … |
| Metadata | `source_id`, `price_vnd`, `district`, `amenities`, `near_landmarks` |

**Quan hệ:** `listings.indexed_at IS NOT NULL` ⇒ có doc tương ứng trong Chroma (best-effort; purge có thể xóa riêng).

---

## Cardinality & ví dụ

```
raw_listings (1) ──source_id──► (0..1) listings (1) ──source_id──► (0..1) chroma

• Mỗi raw có tối đa 1 listing (khi extract success).
• Listing có thể không có raw (seed cũ / purge một phần) — hiếm.
• Listing chưa index: indexed_at = NULL, Chroma không có doc.
```

Query kiểm tra nhanh:

```sql
-- Số lượng theo nguồn
SELECT source_platform, extracted, COUNT(*)
FROM raw_listings
GROUP BY 1, 2;

-- Raw chưa extract
SELECT source_id, source_platform
FROM raw_listings
WHERE extracted = false;

-- Listing chưa index
SELECT source_id, title
FROM listings
WHERE indexed_at IS NULL;

-- Join raw + listing
SELECT r.source_platform, l.title, l.price_vnd, r.last_seen_at
FROM listings l
JOIN raw_listings r ON l.source_id = r.source_id
LIMIT 20;
```

Kết nối: `postgresql://property_intel:property_intel@localhost:5433/property_intel`

---

## Bảng hệ thống

| Bảng | Mô tả |
|------|-------|
| `alembic_version` | Revision migration hiện tại (Alembic) |

---

## Lịch sử migration

| Revision | File | Thay đổi |
|----------|------|----------|
| `001` | `001_initial_schema.py` | Tạo `raw_listings`, `listings` |
| `002` | `002_crawl_metadata.py` | `source_platform`, `source_url`, `crawled_at`, `last_seen_at` |
| `003` | `003_price_vnd_bigint.py` | `price_vnd` INT → BIGINT |
| `004` | `004_listing_phongtot_fields.py` | PhongTot/NhaTot fields + JSONB mở rộng |
| `005` | `005_listing_images.py` | `images_json` |

---

## Map code ↔ DB

| Layer | File |
|-------|------|
| SQLAlchemy entities | `src/property_intel/db/models.py` |
| API DTO | `src/property_intel/api/schemas.py` |
| Search / detail map | `src/property_intel/pipeline/search_service.py` |
| SQL filter | `src/property_intel/pipeline/match_query.py` |
| Chroma index | `src/property_intel/pipeline/index.py` |
| Freshness (last_seen, posted_at) | `src/property_intel/pipeline/freshness.py` |

---

## Export diagram (PNG/SVG)

1. Copy block `mermaid` ở đầu file.
2. Dán vào [mermaid.live](https://mermaid.live) → Export PNG/SVG.
3. Hoặc dùng extension **Markdown Preview Mermaid** trong VS Code/Cursor.

---

## Ghi chú cho Spring migration (Plan A)

- JPA entity map 1:1 hai bảng `raw_listings`, `listings`.
- **Không cần tạo FK** — giữ join `source_id` như Python.
- JSONB → `@JdbcTypeCode(SqlTypes.JSON)` hoặc Hibernate 6 JSON type.
- Chroma **không** map JPA — Python worker `index` job giữ nguyên.

Xem thêm: [`docs/spring-migration-plan-a.md`](spring-migration-plan-a.md)
