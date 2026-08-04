# Lộ trình chuyển BE sang Java/Spring — Plan A (Hybrid)

Tài liệu này dành cho việc **tự migrate từng bước**, không rewrite một lần.  
**Plan A:** Spring Boot làm API + business read/search; **Python giữ** pipeline AI (chat, match, extract, crawl CLI).

> Trạng thái repo Python: **chưa đổi gì** — file này chỉ là kế hoạch.

---

## 1. Mục tiêu Plan A

| Thành phần | Sau migrate | Công nghệ |
|------------|-------------|-----------|
| REST API chính (search, listing, meta, market, health, static UI) | **Spring Boot** | Java 17+, Spring Web, JPA |
| Chat agent, Match NL, Extract LLM | **Python service** (FastAPI riêng hoặc port cắt từ `app.py`) | Giữ LangGraph hiện tại |
| Crawl / discover / index CLI | **Python worker** (giữ `cli.py`) | Typer + Firecrawl |
| Database | **Chung** PostgreSQL `:5433` | Không đổi schema lúc đầu |
| Vector index | **Chung** `./data/chroma` | Python index job; Spring **chưa** cần Chroma ở Phase 1–3 |

**Nguyên tắc:** JSON contract API **giữ nguyên** để FE (`search.js`, `chat.js`) không phải sửa nhiều.

---

## 2. Kiến trúc đích

```mermaid
flowchart LR
  subgraph browser [Browser]
    UI[app.html + search.js + chat.js]
  end

  subgraph spring [Spring Boot :8080]
    SC[SearchController]
    LC[ListingController]
    MC[MarketController]
    CC[ChatProxyController]
    SS[SearchService]
    JPA[(JPA → Postgres)]
  end

  subgraph python [Python AI Service :8001]
    CHAT[/api/chat]
    MATCH[/api/match]
    EXT[CLI extract/crawl/index]
  end

  UI --> spring
  CC -->|HTTP proxy| python
  spring --> JPA
  python --> JPA
  EXT --> JPA
  EXT --> Chroma[(Chroma)]
```

**Luồng người dùng:**

1. Tìm phòng / xem chi tiết → **Spring** đọc Postgres trực tiếp.
2. Chat / match NL → **Spring** nhận request → forward sang **Python AI** → trả JSON y hệt hiện tại.
3. Crawl/extract/index → chạy CLI Python như cũ (cron hoặc tay).

---

## 3. Cấu trúc repo đề xuất

Hai cách (chọn một):

### Cách 1 — Monorepo (khuyên khi học)

```
ai-property-intelligence/
├── docs/
│   └── spring-migration-plan-a.md   ← file này
├── src/property_intel/              ← Python (giữ nguyên, thu gọn sau)
├── property-intel-spring/           ← NEW: Maven/Gradle Spring Boot
│   ├── pom.xml
│   └── src/main/java/com/propertyintel/
│       ├── PropertyIntelApplication.java
│       ├── controller/
│       ├── service/
│       ├── repository/
│       ├── entity/
│       ├── dto/
│       ├── config/
│       └── client/                  ← PythonAiClient (RestClient)
│   └── src/main/resources/
│       ├── application.yml
│       └── static/                  ← copy từ api/static (Phase 4)
└── docker-compose.yml               ← thêm service spring (Phase 5, tùy chọn)
```

### Cách 2 — Repo Spring riêng

Clone repo mới, copy static + contract từ repo Python. Postgres/Chroma mount volume chung.

---

## 4. Map Python → Spring (tham chiếu khi code)

| Python (hiện tại) | Spring (tạo mới) | Ghi chú |
|-------------------|------------------|---------|
| `api/app.py` | `*Controller` | 1 controller / nhóm endpoint |
| `api/schemas.py` | `dto/request`, `dto/response` | Field name JSON **snake_case** giống Pydantic |
| `search_service.py` | `SearchService`, `ListingService` | Port logic, không copy LangGraph |
| `match_query.py` → `sql_filter_listings` | `ListingRepository` + `ListingFilterSpec` | Phase 2–3; Phase 1 có thể `@Query` đơn giản |
| `db/models.py` → `ListingRow` | `entity/Listing.java` | `@Entity` map bảng `listings` |
| `db/models.py` → `RawListingRow` | `entity/RawListing.java` | Phase listing detail cần join raw body (ảnh) |
| `api/meta_data.py` | `SearchMetaService` | Hardcode presets như Python |
| `market_intel.py` | `MarketService` | SQL aggregate, không LLM |
| `agents/chat_graph.py` | **Không port** | Python `:8001` |
| `agents/matching_graph.py` | **Không port** | Python `:8001` |
| `cli.py` + `pipeline/*` | **Không port** | Giữ Python worker |

---

## 5. Database — dùng lại schema hiện tại

**Không tạo migration mới lúc đầu.** Spring `ddl-auto: validate` (hoặc `none`) + Flyway **chỉ khi** bạn muốn quản lý schema từ Java sau.

### Bảng `listings` (entity chính)

Tham chiếu: `src/property_intel/db/models.py` → class `ListingRow`.

Cột quan trọng cho API:

- `source_id` (PK business, unique)
- `title`, `price_vnd` (BIGINT), `district`, `address_text`
- `area_min_m2`, `area_max_m2`
- `amenities_json`, `common_amenities_json`, `room_layout_tags_json` → map `List<String>` hoặc `@JdbcTypeCode(SqlTypes.JSON)`
- `service_fees_json`, `building_json` → `Map` hoặc JSON column
- `images_json`, `description_long`, `posted_at`, `source_url`, `contact_phone`
- `indexed_at` (optional cho admin)

### Bảng `raw_listings`

Cần cho `ListingDetail.images` fallback (Python đọc `raw.body` khi `images_json` rỗng).

Spring port: `ListingService.getDetail(sourceId)` join hoặc query riêng `RawListingRepository`.

### Kết nối (application.yml)

```yaml
spring:
  datasource:
    url: jdbc:postgresql://localhost:5433/property_intel
    username: property_intel
    password: property_intel
  jpa:
    hibernate:
      ddl-auto: validate
    properties:
      hibernate:
        dialect: org.hibernate.dialect.PostgreSQLDialect
```

---

## 6. API contract — giữ nguyên path & JSON

Tham chiếu: `src/property_intel/api/app.py`, `api/schemas.py`.

| Method | Path | Spring Phase | Python sau migrate |
|--------|------|--------------|-------------------|
| GET | `/health` | 1 | — |
| GET | `/api/meta/search` | 1 | — |
| POST | `/api/search` | 1–2 | — |
| GET | `/api/listings/{source_id}` | 2 | — |
| GET | `/api/market?landmark=` | 3 | — |
| POST | `/api/chat` | 4 (proxy) | Python AI |
| POST | `/api/match` | 4 (proxy) | Python AI |
| GET | `/`, static | 4 | — |

**Lưu ý JSON:** Pydantic dùng `snake_case`. Spring mặc định Jackson cũng serialize bean field `priceVnd` → `priceVnd`.  
→ Dùng `@JsonProperty("price_vnd")` trên DTO **hoặc** `spring.jackson.property-naming-strategy=SNAKE_CASE`.

---

## 7. Lộ trình theo Phase (tự làm tuần tự)

Mỗi phase có: **mục tiêu**, **việc làm**, **file Python đọc**, **cách verify**, **xong khi nào**.

---

### Phase 0 — Chuẩn bị môi trường (0.5 ngày)

**Mục tiêu:** Spring project chạy được, connect Postgres, Python vẫn chạy song song.

**Việc làm:**

1. Cài JDK 17+, IntelliJ hoặc VS Code + Extension Pack for Java.
2. [start.spring.io](https://start.spring.io):
   - Project: Maven
   - Java 17
   - Dependencies: **Spring Web**, **Spring Data JPA**, **PostgreSQL Driver**, **Validation**, **Spring Boot Actuator** (optional)
3. Tạo folder `property-intel-spring/` trong monorepo (hoặc repo riêng).
4. `docker compose up -d` — Postgres `:5433` đang chạy.
5. Chạy Python API cũ để so sánh: `python -m property_intel.cli serve` → `:8000`.

**Verify:**

```bash
# Spring
./mvnw spring-boot:run   # port 8080 mặc định

curl http://localhost:8080/actuator/health   # nếu bật Actuator
```

**Xong khi:** Spring Boot start không lỗi, `application.yml` trỏ đúng Postgres.

---

### Phase 1 — Health + Search Meta (1–2 ngày)

**Mục tiêu:** Học Controller → Service; FE có thể gọi meta từ Spring.

**Port từ Python:**

- `GET /health` → `app.py`
- `GET /api/meta/search` → `api/meta_data.py`

**Spring classes gợi ý:**

```
controller/HealthController.java
controller/SearchMetaController.java
service/SearchMetaService.java
dto/response/SearchMetaResponse.java
dto/response/RangePresetDto.java
...
```

**Logic:** Copy danh sách quận, price/area presets, layout, amenities từ `meta_data.py` (hardcode — không cần DB).

**Verify:**

```bash
curl http://localhost:8080/health
curl http://localhost:8080/api/meta/search
# So sánh JSON với:
curl http://localhost:8000/api/meta/search
```

**Xong khi:** Response structure giống Python (dùng diff JSON hoặc mắt).

---

### Phase 2 — POST /api/search (3–5 ngày) — **core học JPA**

**Mục tiêu:** Danh sách card giống Python; chưa cần Chroma (UI search hiện tại cũng chỉ SQL + sort).

**Port từ Python:**

- `search_service.py` → `search_listings`, `listing_row_to_card`
- `match_query.py` → `sql_filter_listings`, filter giá/quận/amenities, freshness P5
- `pipeline/freshness.py` → `is_listing_fresh` (đọc `raw_listings.last_seen_at`)

**Spring classes:**

```
controller/SearchController.java
service/SearchService.java
service/ListingMapper.java          # Entity → ListingCardDto
repository/ListingRepository.java
repository/RawListingRepository.java
entity/Listing.java
entity/RawListing.java
dto/request/SearchRequest.java
dto/response/SearchResponse.java
dto/response/ListingCardDto.java
config/SearchProperties.java        # searchMaxAgeDays = 7
```

**Gợi ý implement filter (theo thứ tự học):**

1. **Mức 1:** JPA `findAll` + filter in-memory (≤100 listings — OK cho MVP học).
2. **Mức 2:** `Specification<Listing>` hoặc `@Query` native cho price/district.
3. **Mức 3:** Port đủ logic `match_query.py` (amenities JSON, service fees, text `q` LIKE).

**Sort:** `price_asc`, `price_desc`, `area_asc`, `area_desc` — port `sort_listing_rows` từ `search_service.py`.

**Pagination:** `page`, `size` — `subList` sau filter hoặc Pageable.

**Verify:**

```bash
curl -X POST http://localhost:8080/api/search \
  -H "Content-Type: application/json" \
  -d '{"districts":["Nam Từ Liêm"],"sort":"price_asc","page":1,"size":20}'
```

So sánh `total` và `items[0].source_id` với Python `:8000`.

**Xong khi:** Cùng filter → cùng `total` (±0) và cùng thứ tự top 5.

---

### Phase 3 — GET /api/listings/{source_id} + Market (2–3 ngày)

**Mục tiêu:** Drawer chi tiết + market report.

**Port listing detail:**

- `search_service.py` → `get_listing_by_source_id`, `listing_row_to_detail`
- `pipeline/listing_media.py` → `parse_description_sections`, `extract_image_urls` (port Java **hoặc** gọi Python internal — khuyên port sau; Phase 3 có thể trả `description_long` raw trước)

**Port market:**

- `market_intel.py` → `compute_market_report`, `format_market_report`

**Spring classes:**

```
controller/ListingController.java
controller/MarketController.java
service/ListingDetailService.java
service/MarketService.java
dto/response/ListingDetailDto.java
dto/response/DescriptionSectionDto.java
```

**Verify:**

```bash
curl http://localhost:8080/api/listings/nhatot_XXXXX
curl "http://localhost:8080/api/market?landmark=bach_khoa"
```

**Xong khi:** Detail có đủ field; market text hợp lý.

**Ghi chú học tập:** Parser mô tả (`description_sections`) phức tạp — có thể **Phase 3b** riêng: port regex từ `listing_media.py` hoặc tạm proxy 1 endpoint Python `GET /internal/listings/{id}/detail-enriched`.

---

### Phase 4 — Tách Python AI Service + Proxy Chat/Match (2 ngày)

**Mục tiêu:** Spring là cổng duy nhất cho browser; AI vẫn Python.

**Bước 4a — Tách FastAPI AI (Python)**

Tạo `src/property_intel/ai_app.py` (file mới, **chưa bắt buộc làm ngay** — có thể tạm chạy full `app.py` port 8001):

```python
# Chỉ mount:
# POST /api/chat
# POST /api/match
# GET /health
# (Không serve static)
```

Chạy:

```bash
uvicorn property_intel.ai_app:app --port 8001
```

**Bước 4b — Spring proxy**

```
client/PythonAiClient.java    # RestClient / WebClient
controller/ChatController.java
controller/MatchController.java
config/PythonAiProperties.java   # base-url: http://localhost:8001
```

`ChatController` nhận `ChatRequest` → POST forward → trả `ChatResponse` nguyên xi.

**Verify:**

1. Tắt chat trên Python `:8000` (nếu đã chuyển UI sang Spring).
2. UI → Spring `:8080` → chat hoạt động qua proxy.

**Xong khi:** Chat widget hoạt động; log Spring thấy forward tới `:8001`.

---

### Phase 5 — Static UI + cutover (1 ngày)

**Mục tiêu:** User chỉ mở Spring; Python AI + CLI chạy nền.

1. Copy `src/property_intel/api/static/` → `property-intel-spring/src/main/resources/static/`.
2. Spring:

```java
@Configuration
public class WebConfig implements WebMvcConfigurer {
  @Override
  public void addViewControllers(ViewControllerRegistry registry) {
    registry.addViewController("/").setViewName("forward:/static/app.html");
  }
}
```

Hoặc serve `classpath:/static/app.html` tại `/`.

3. **Không đổi** path API trong JS (`/api/search`...) — cùng origin `:8080`.

**Verify:** Mở `http://localhost:8080/` — search, detail, chat đều OK.

**Cutover checklist:**

- [ ] Spring `:8080` — search, detail, meta, market, static
- [ ] Python `:8001` — chat, match only
- [ ] CLI Python — crawl, extract, index unchanged
- [ ] Postgres + Chroma dùng chung

---

### Phase 6 — (Tùy chọn) Docker Compose full stack

Thêm service `spring-api` + `python-ai` vào `docker-compose.yml`.  
Phase học có thể **bỏ qua** — chạy local 2 process là đủ.

---

## 8. Python AI Service — spec tối thiểu

Khi tách (Phase 4), Python service chỉ cần:

| Endpoint | Body | Response |
|----------|------|----------|
| POST `/api/chat` | `ChatRequest` | `ChatResponse` |
| POST `/api/match` | `{"query":"..."}` | `{"query","answer"}` |
| GET `/health` | — | `{"status":"ok"}` |

Env giữ nguyên `.env` (LLM, DATABASE_URL, CHROMA_PATH).  
Chat vẫn cần Postgres + Chroma → **cùng DB** với Spring.

---

## 9. Những thứ **cố ý không port** sang Java (Plan A)

| Thành phần | Lý do |
|------------|--------|
| LangGraph chat/match | Đã ổn Python; port tốn tháng |
| `extract.py`, LLM structured | Phụ thuộc LangChain |
| Firecrawl crawl runner | Script batch, Python phù hợp |
| Chroma index job | Python `index.py` 20 dòng; gọi CLI sau extract |
| `parse_match_filters` (LLM) | Chỉ cần cho chat/match Python |

---

## 10. Checklist kỹ năng Java học được mỗi Phase

| Phase | Kỹ năng Spring |
|-------|----------------|
| 0 | Project setup, `application.yml`, run config |
| 1 | `@RestController`, DTO, `@ConfigurationProperties` |
| 2 | JPA Entity, Repository, Service, Validation, pagination |
| 3 | Join query, aggregate SQL, exception `@ControllerAdvice` |
| 4 | `RestClient`, timeout, error mapping proxy |
| 5 | Static resources, CORS (nếu tách FE sau) |
| 6 | Docker multi-service |

---

## 11. Rủi ro & cách tránh

| Rủi ro | Cách tránh |
|--------|------------|
| JSON field lệch (`price_vnd` vs `priceVnd`) | Bật SNAKE_CASE hoặc `@JsonProperty` trên mọi DTO |
| Filter SQL khác Python → total lệch | So sánh curl song song từng phase |
| Hibernate đổi schema | `ddl-auto: validate`, không `update` trên DB prod |
| Chat 429 Groq | Python AI giữ rate limit; Spring chỉ proxy |
| 2 app ghi cùng lúc | Phase 1–5 **read-heavy** Spring; ghi DB vẫn Python CLI |
| `images_json` / `description_sections` khó port | Phase 3 trả partial; enrich sau |

---

## 12. Lệnh vận hành sau cutover (tham khảo)

```bash
# Terminal 1 — Postgres
docker compose up -d

# Terminal 2 — Python AI (chat/match)
source .venv/bin/activate
uvicorn property_intel.ai_app:app --host 127.0.0.1 --port 8001

# Terminal 3 — Spring (UI + search API)
cd property-intel-spring && ./mvnw spring-boot:run

# Terminal 4 — Pipeline (khi cần)
property-intel crawl --source firecrawl
property-intel extract --force
property-intel index
```

---

## 13. Thứ tự file Python nên đọc khi port

1. `api/schemas.py` — contract DTO
2. `search_service.py` — business map row → card/detail
3. `match_query.py` — `sql_filter_listings` (filter phức tạp)
4. `pipeline/freshness.py` — P5
5. `pipeline/listing_media.py` — detail enrich (Phase 3b)
6. `api/meta_data.py` — meta hardcode
7. `market_intel.py` — market

**Không cần đọc sâu lúc đầu:** `chat_graph.py`, `matching_graph.py`, `extract.py`, `crawl/*`.

---

## 14. Tiêu chí hoàn thành Plan A

Coi migrate **xong Phase 5** khi:

- [ ] Browser truy cập Spring `:8080` — full UI
- [ ] Search + detail + market do Spring + JPA
- [ ] Chat/match qua Spring proxy → Python `:8001`
- [ ] Crawl/extract/index vẫn CLI Python
- [ ] Cùng Postgres, không duplicate schema
- [ ] FastAPI `:8000` có thể **tắt hẳn** (hoặc chỉ dev)

---

## 15. Bước tiếp theo đề xuất (hôm nay)

1. Làm **Phase 0** — tạo project Spring trên start.spring.io.
2. Làm **Phase 1** — `/health` + `/api/meta/search`.
3. Ghi journal ngắn: JSON diff Python vs Spring sau mỗi endpoint.

Khi xong Phase 2, có thể thêm file `property-intel-spring/README.md` riêng cho lệnh Maven — không bắt buộc lúc này.

---

*Tài liệu sync với repo Python tại commit gần nhất — schema `listings` / `raw_listings`, API v0.4.x.*
