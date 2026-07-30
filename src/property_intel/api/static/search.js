const AMENITY_LABELS = {
  bep: "Bếp",
  dieu_hoa: "Điều hòa",
  may_giat: "Máy giặt",
  nong_lanh: "Nóng lạnh",
  ban_cong: "Ban công",
};

const PLATFORM_LABELS = {
  phongtot: "PhongTot",
  nhatot: "NhaTot",
};

function platformFromUrl(url) {
  if (!url) return null;
  const u = String(url).toLowerCase();
  if (u.includes("nhatot.com") || u.includes("chotot.com")) return "nhatot";
  if (u.includes("phongtot.com")) return "phongtot";
  return null;
}

function resolvePlatform(item) {
  const fromUrl = platformFromUrl(item?.source_url);
  if (fromUrl) return fromUrl;
  if (item?.source_platform) return item.source_platform;
  const id = item?.source_id || "";
  if (id.startsWith("nhatot_")) return "nhatot";
  if (id.startsWith("phongtot_")) return "phongtot";
  return "web";
}

function platformLabel(item) {
  return PLATFORM_LABELS[resolvePlatform(item)] || "Nguồn";
}

function sourceLinkButtonHtml(item) {
  if (!item?.source_url) return "";
  const platform = resolvePlatform(item);
  const label = PLATFORM_LABELS[platform] || "Xem tin";
  return `<a class="btn btn-platform btn-platform-${platform}" href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${escapeHtml(label)}</a>`;
}

function formatPriceLabel(item) {
  if (item.price_vnd == null) return "Liên hệ";
  const price = formatVnd(item.price_vnd);
  if (resolvePlatform(item) === "phongtot") {
    return `Từ ${price}`;
  }
  return `${price}/tháng`;
}

function commonAmenitiesLabel(item) {
  return resolvePlatform(item) === "phongtot" ? "Tòa nhà" : "Nội thất";
}

function platformBadgeHtml(item) {
  const platform = resolvePlatform(item);
  if (!PLATFORM_LABELS[platform]) return "";
  return `<span class="platform-badge platform-badge-${platform}">${escapeHtml(platformLabel(item))}</span>`;
}

window.resolvePlatform = resolvePlatform;
window.platformLabel = platformLabel;

const LAYOUT_LABELS = {
  studio: "Studio",
  "1_ngu_1_khach": "1 phòng ngủ",
  "2_phong_ngu": "2 phòng ngủ",
  co_bep: "Có bếp",
};

let lastSearchBody = null;
let lastSearchResultIds = [];

function searchBodyToMatchFilters(body) {
  return {
    districts: body.districts || [],
    price_min: body.price_min || null,
    price_max: body.price_max || null,
    area_min_m2: body.area_min_m2 || null,
    area_max_m2: body.area_max_m2 || null,
    amenities_required: body.amenities_required || [],
    room_layout_tags: body.room_layout_tags || [],
    common_amenities_required: body.common_amenities_required || [],
    electricity_max_vnd_per_kwh: body.electricity_max_vnd_per_kwh || null,
    water_max_vnd_per_m3: body.water_max_vnd_per_m3 || null,
    water_max_vnd_per_person: body.water_max_vnd_per_person || null,
    internet_max_vnd_per_room: body.internet_max_vnd_per_room || null,
    soft_prefs: body.q || null,
  };
}

function buildFiltersSummary(body) {
  const parts = [];
  if (body.districts?.length) parts.push(body.districts.join(", "));
  if (body.price_max) parts.push(`≤ ${Math.round(body.price_max / 1e6)} tr`);
  if (body.price_min) parts.push(`≥ ${Math.round(body.price_min / 1e6)} tr`);
  if (body.q) parts.push(`"${body.q}"`);
  if (body.amenities_required?.length) parts.push(body.amenities_required.join(", "));
  return parts.length ? parts.join(" · ") : "Hà Nội";
}
let state = {
  districts: [],
  priceMin: 0,
  priceMax: null,
  areaMin: null,
  areaMax: null,
  roomLayouts: [],
  amenities: [],
  q: "",
  sort: "price_asc",
  page: 1,
  size: 20,
  pricePreset: "all",
  areaPreset: "all",
};

function formatVnd(value) {
  if (value == null) return "Liên hệ";
  return `${value.toLocaleString("vi-VN")}đ`;
}

function formatArea(min, max) {
  if (min == null && max == null) return "";
  if (min != null && max != null && min !== max) return `${min}–${max} m²`;
  const v = min ?? max;
  return v != null ? `${v} m²` : "";
}

async function loadMeta() {
  const res = await fetch("/api/meta/search");
  if (!res.ok) throw new Error("Không tải được cấu hình filter");
  meta = await res.json();
  renderDistricts();
  renderPresets("price", meta.price_presets, "pricePresetList", applyPricePreset);
  renderPresets("area", meta.area_presets, "areaPresetList", applyAreaPreset);
  renderRoomLayouts();
  renderAmenities();
  renderSortOptions();
}

function renderDistricts() {
  const el = document.getElementById("districtChips");
  el.innerHTML = "";
  meta.districts.forEach((name) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip" + (state.districts.includes(name) ? " selected" : "");
    btn.textContent = name;
    btn.addEventListener("click", () => {
      if (state.districts.includes(name)) {
        state.districts = state.districts.filter((d) => d !== name);
      } else {
        state.districts.push(name);
      }
      btn.classList.toggle("selected");
    });
    el.appendChild(btn);
  });
}

function renderPresets(kind, presets, containerId, handler) {
  const el = document.getElementById(containerId);
  el.innerHTML = "";
  presets.forEach((p) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "preset-btn" + (state[kind + "Preset"] === p.id ? " active" : "");
    btn.textContent = p.label;
    btn.addEventListener("click", () => handler(p.id));
    el.appendChild(btn);
  });
}

function applyPricePreset(id) {
  state.pricePreset = id;
  const preset = meta.price_presets.find((p) => p.id === id);
  if (!preset) return;
  state.priceMin = preset.min ?? 0;
  state.priceMax = preset.max ?? null;
  document.getElementById("priceMin").value = state.priceMin;
  document.getElementById("priceMax").value = state.priceMax ?? "";
  renderPresets("price", meta.price_presets, "pricePresetList", applyPricePreset);
}

function applyAreaPreset(id) {
  state.areaPreset = id;
  const preset = meta.area_presets.find((p) => p.id === id);
  if (!preset) return;
  state.areaMin = preset.min;
  state.areaMax = preset.max;
  document.getElementById("areaMin").value = state.areaMin ?? "";
  document.getElementById("areaMax").value = state.areaMax ?? "";
  renderPresets("area", meta.area_presets, "areaPresetList", applyAreaPreset);
}

function renderRoomLayouts() {
  const el = document.getElementById("layoutChips");
  el.innerHTML = "";
  meta.room_layout_options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip" + (state.roomLayouts.includes(opt.id) ? " selected" : "");
    btn.textContent = opt.label;
    btn.addEventListener("click", () => {
      if (state.roomLayouts.includes(opt.id)) {
        state.roomLayouts = state.roomLayouts.filter((x) => x !== opt.id);
      } else {
        state.roomLayouts.push(opt.id);
      }
      btn.classList.toggle("selected");
    });
    el.appendChild(btn);
  });
}

function renderAmenities() {
  const el = document.getElementById("amenityChips");
  el.innerHTML = "";
  meta.amenity_options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "chip" + (state.amenities.includes(opt.id) ? " selected" : "");
    btn.textContent = opt.label;
    btn.addEventListener("click", () => {
      if (state.amenities.includes(opt.id)) {
        state.amenities = state.amenities.filter((x) => x !== opt.id);
      } else {
        state.amenities.push(opt.id);
      }
      btn.classList.toggle("selected");
    });
    el.appendChild(btn);
  });
}

function renderSortOptions() {
  const sel = document.getElementById("sortSelect");
  sel.innerHTML = "";
  meta.sort_options.forEach((opt) => {
    const o = document.createElement("option");
    o.value = opt.id;
    o.textContent = opt.label;
    sel.appendChild(o);
  });
  sel.value = state.sort;
}

function collectLayoutTags() {
  const tags = [];
  state.roomLayouts.forEach((id) => {
    const opt = meta.room_layout_options.find((o) => o.id === id);
    if (opt) tags.push(...opt.tags);
  });
  return [...new Set(tags)];
}

function buildSearchBody() {
  const priceMin = parseInt(document.getElementById("priceMin").value, 10);
  const priceMaxRaw = document.getElementById("priceMax").value;
  const areaMinRaw = document.getElementById("areaMin").value;
  const areaMaxRaw = document.getElementById("areaMax").value;

  return {
    districts: state.districts,
    price_min: Number.isFinite(priceMin) ? priceMin : 0,
    price_max: priceMaxRaw ? parseInt(priceMaxRaw, 10) : null,
    area_min_m2: areaMinRaw ? parseFloat(areaMinRaw) : null,
    area_max_m2: areaMaxRaw ? parseFloat(areaMaxRaw) : null,
    room_layout_tags: collectLayoutTags(),
    amenities_required: [...state.amenities],
    q: document.getElementById("qInput").value.trim() || null,
    sort: document.getElementById("sortSelect").value,
    page: state.page,
    size: state.size,
  };
}

function renderCardThumb(item) {
  const url = item.thumbnail_url;
  if (!url) {
    return '<div class="card-thumb card-thumb-empty">Chưa có ảnh</div>';
  }
  return `<div class="card-thumb"><img src="${escapeHtml(url)}" alt="" loading="lazy" /></div>`;
}

const SERVICE_FEE_ROWS = [
  { key: "electricity_vnd_per_kwh", label: "Điện", unit: "đ/kWh" },
  { key: "internet_vnd_per_room", label: "Internet", unit: "đ/phòng" },
  { key: "laundry_vnd_per_person", label: "Giặt sấy", unit: "đ/người" },
  { key: "sanitation_vnd_per_person", label: "Vệ sinh", unit: "đ/người" },
  { key: "other_vnd_per_person", label: "Phí DV chung", unit: "đ/người" },
];

function formatWaterFeeRow(fees) {
  if (!fees) return null;
  const unit = fees.water_unit
    || (fees.water_vnd_per_m3 != null ? "per_m3" : null)
    || (fees.water_vnd_per_person != null ? "per_person" : null);
  if (unit === "per_m3" && fees.water_vnd_per_m3 != null) {
    return { label: "Nước", value: `${formatVnd(fees.water_vnd_per_m3)}/m³` };
  }
  if (unit === "per_person" && fees.water_vnd_per_person != null) {
    return { label: "Nước", value: `${formatVnd(fees.water_vnd_per_person)}/người` };
  }
  if (unit === "included") {
    return { label: "Nước", value: "Miễn phí" };
  }
  if (fees.water_raw) {
    return { label: "Nước", value: String(fees.water_raw) };
  }
  return null;
}

function renderServiceFeesTable(fees) {
  if (!fees || typeof fees !== "object") return "";
  const rows = [];
  const water = formatWaterFeeRow(fees);
  if (water) rows.push(water);
  SERVICE_FEE_ROWS.forEach(({ key, label, unit }) => {
    const value = fees[key];
    if (value != null && typeof value === "number") {
      rows.push({ label, value: `${formatVnd(value)}/${unit.replace("đ/", "")}` });
    }
  });
  if (!rows.length) return "";
  return `
    <div class="fee-grid">
      ${rows.map((row) => `
        <div class="fee-row">
          <span class="fee-label">${escapeHtml(row.label)}</span>
          <span class="fee-value">${escapeHtml(row.value)}</span>
        </div>`).join("")}
    </div>`;
}

function renderDescriptionSections(item) {
  const sections = item.description_sections || [];
  if (sections.length) {
    return `
      <div class="desc-blocks">
        ${sections.map((section) => `
          <div class="desc-block">
            ${section.label ? `<div class="desc-block-label">${escapeHtml(section.label)}</div>` : ""}
            <div class="desc-block-body">${formatDescBody(section.body)}</div>
          </div>`).join("")}
      </div>`;
  }
  const desc = item.description_long || item.short_description || "";
  if (!desc) return "";
  return `<div class="desc-blocks"><div class="desc-block"><div class="desc-block-body">${formatDescBody(desc)}</div></div></div>`;
}

function formatDescBody(text) {
  if (!text) return "";
  return escapeHtml(text)
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("<br>");
}

function renderDetailGallery(item) {
  const images = item.images || [];
  if (!images.length) return "";
  const main = images[0];
  const thumbs = images.slice(1, 8);
  return `
    <div class="detail-gallery">
      <div class="gallery-main">
        <img id="galleryMainImg" src="${escapeHtml(main)}" alt="" />
      </div>
      ${thumbs.length ? `
      <div class="gallery-thumbs">
        ${[main, ...thumbs].map((url, idx) => `
          <button type="button" class="gallery-thumb${idx === 0 ? " active" : ""}" data-url="${escapeHtml(url)}" aria-label="Ảnh ${idx + 1}">
            <img src="${escapeHtml(url)}" alt="" loading="lazy" />
          </button>`).join("")}
      </div>` : ""}
    </div>`;
}

function bindGalleryHandlers(root) {
  const mainImg = root.querySelector("#galleryMainImg");
  if (!mainImg) return;
  root.querySelectorAll(".gallery-thumb").forEach((btn) => {
    btn.addEventListener("click", () => {
      mainImg.src = btn.dataset.url;
      root.querySelectorAll(".gallery-thumb").forEach((el) => el.classList.remove("active"));
      btn.classList.add("active");
    });
  });
}

function renderCard(item) {
  const layouts = item.room_layout_tags.map((t) => LAYOUT_LABELS[t] || t).join(", ");
  const amenities = item.amenities.map((a) => AMENITY_LABELS[a] || a).join(", ");
  const common = item.common_amenities.slice(0, 3).join(", ");
  const fees = item.service_fees_summary.join("; ");
  const area = formatArea(item.area_min_m2, item.area_max_m2);

  return `
    <article class="card card-clickable" data-source-id="${escapeHtml(item.source_id)}" tabindex="0" role="button" aria-label="Xem chi tiết ${escapeHtml(item.title)}">
      ${renderCardThumb(item)}
      <div class="card-body">
        <div class="card-title-row">
          <h3>${escapeHtml(item.title)}</h3>
          ${platformBadgeHtml(item)}
        </div>
        <div class="card-meta">${escapeHtml(item.district || "")}${item.address_text ? " · " + escapeHtml(item.address_text) : ""}</div>
        <div class="card-meta">${area}${layouts ? " · " + escapeHtml(layouts) : ""}</div>
        ${item.short_description ? `<p class="card-tags">${escapeHtml(item.short_description.slice(0, 160))}</p>` : ""}
        ${amenities ? `<div class="card-tags">Phòng: ${escapeHtml(amenities)}</div>` : ""}
        ${common ? `<div class="card-tags">${escapeHtml(commonAmenitiesLabel(item))}: ${escapeHtml(common)}</div>` : ""}
        ${fees ? `<div class="card-tags">${escapeHtml(fees)}</div>` : ""}
      </div>
      <div class="card-side">
        <div class="card-price">${formatPriceLabel(item)}</div>
        <button type="button" class="btn btn-secondary btn-detail" data-source-id="${escapeHtml(item.source_id)}">Chi tiết</button>
        ${sourceLinkButtonHtml(item)}
        ${item.contact_phone ? `<div class="card-tags" style="margin-top:0.5rem">${escapeHtml(item.contact_phone)}</div>` : ""}
      </div>
    </article>
  `;
}

function bindCardHandlers() {
  document.querySelectorAll(".card-clickable").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest("a, button")) return;
      openDetail(card.dataset.sourceId);
    });
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openDetail(card.dataset.sourceId);
      }
    });
  });
  document.querySelectorAll(".btn-detail").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      openDetail(btn.dataset.sourceId);
    });
  });
}

function renderDetailContent(item) {
  const layouts = item.room_layout_tags.map((t) => LAYOUT_LABELS[t] || t).join(", ");
  const amenities = item.amenities.map((a) => AMENITY_LABELS[a] || a);
  const feeTable = renderServiceFeesTable(item.service_fees);
  const feeFallback = !feeTable && item.service_fees_summary?.length
    ? `<ul>${item.service_fees_summary.map((f) => `<li>${escapeHtml(f)}</li>`).join("")}</ul>`
    : "";
  const building = item.building || {};
  const buildingParts = [];
  if (building.floor_count != null) buildingParts.push(`${building.floor_count} tầng`);
  if (building.room_count != null) buildingParts.push(`${building.room_count} phòng`);
  if (building.renovation_year != null) buildingParts.push(`Cải tạo ${building.renovation_year}`);
  if (building.deposit_vnd != null) buildingParts.push(`Cọc ${formatVnd(building.deposit_vnd)}`);
  const isPhongTot = resolvePlatform(item) === "phongtot";
  const buildingTitle = isPhongTot ? "Tòa nhà" : "Thông tin thuê";
  const commonTitle = isPhongTot ? "Tiện ích chung" : "Nội thất / tiện ích";
  const descHtml = renderDescriptionSections(item);

  return `
    ${renderDetailGallery(item)}
    <div class="drawer-head-meta">
      ${platformBadgeHtml(item)}
      <div class="drawer-price">${formatPriceLabel(item)}</div>
    </div>
    ${item.price_note ? `<p class="card-tags">${escapeHtml(item.price_note)}</p>` : ""}
    <div class="detail-section">
      <h3>Vị trí</h3>
      <p>${escapeHtml(item.district || "—")}${item.address_text ? "<br>" + escapeHtml(item.address_text) : ""}</p>
    </div>
    <div class="detail-section">
      <h3>Thông tin phòng</h3>
      <p>
        ${formatArea(item.area_min_m2, item.area_max_m2) || "—"}
        ${layouts ? " · " + escapeHtml(layouts) : ""}
      </p>
    </div>
    ${buildingParts.length ? `
    <div class="detail-section">
      <h3>${escapeHtml(buildingTitle)}</h3>
      <p>${escapeHtml(buildingParts.join(" · "))}</p>
    </div>` : ""}
    ${amenities.length ? `
    <div class="detail-section">
      <h3>Tiện ích phòng</h3>
      <ul>${amenities.map((a) => `<li>${escapeHtml(a)}</li>`).join("")}</ul>
    </div>` : ""}
    ${item.common_amenities.length ? `
    <div class="detail-section">
      <h3>${escapeHtml(commonTitle)}</h3>
      <ul>${item.common_amenities.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>
    </div>` : ""}
    ${feeTable || feeFallback ? `
    <div class="detail-section">
      <h3>Phí dịch vụ</h3>
      ${feeTable || feeFallback}
    </div>` : ""}
    ${item.near_landmarks && item.near_landmarks.length ? `
    <div class="detail-section">
      <h3>Gần</h3>
      <p>${escapeHtml(item.near_landmarks.join(", "))}</p>
    </div>` : ""}
    ${descHtml ? `
    <div class="detail-section detail-section-desc">
      <h3>Mô tả chi tiết</h3>
      ${descHtml}
    </div>` : ""}
    <div class="detail-actions">
      ${item.contact_phone ? `<a class="btn btn-primary" href="tel:${escapeHtml(item.contact_phone.replace(/\s/g, ""))}">Gọi ${escapeHtml(item.contact_phone)}</a>` : ""}
      ${item.source_url ? `<a class="btn btn-outline btn-platform btn-platform-${resolvePlatform(item)}" href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener">Xem trên ${escapeHtml(PLATFORM_LABELS[resolvePlatform(item)] || "nguồn")}</a>` : ""}
    </div>
  `;
}

async function openDetail(sourceId) {
  const drawer = document.getElementById("detailDrawer");
  const backdrop = document.getElementById("drawerBackdrop");
  const body = document.getElementById("drawerBody");
  const title = document.getElementById("drawerTitle");

  drawer.classList.add("open");
  backdrop.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  backdrop.setAttribute("aria-hidden", "false");
  body.innerHTML = '<div class="loading">Đang tải...</div>';
  document.body.style.overflow = "hidden";

  try {
    const res = await fetch(`/api/listings/${encodeURIComponent(sourceId)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);
    title.textContent = data.title;
    body.innerHTML = renderDetailContent(data);
    bindGalleryHandlers(body);
  } catch (err) {
    body.innerHTML = `<div class="error">${escapeHtml(err.message)}</div>`;
  }
}

function closeDetail() {
  document.getElementById("detailDrawer").classList.remove("open");
  document.getElementById("drawerBackdrop").classList.remove("open");
  document.getElementById("detailDrawer").setAttribute("aria-hidden", "true");
  document.getElementById("drawerBackdrop").setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
}

window.openDetail = openDetail;

function escapeHtml(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

async function runSearch(page = 1) {
  state.page = page;
  const resultsEl = document.getElementById("results");
  const metaEl = document.getElementById("resultsMeta");
  resultsEl.innerHTML = '<div class="loading">Đang tìm...</div>';
  metaEl.textContent = "";

  try {
    const body = buildSearchBody();
    state.sort = body.sort;
    lastSearchBody = body;
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);

    const districtLabel = state.districts.length ? state.districts.join(", ") : "Hà Nội";
    metaEl.textContent = `Cho thuê phòng trọ ${districtLabel} — ${data.total} kết quả`;
    lastSearchResultIds = data.items.map((item) => item.source_id);

    if (typeof window.syncSearchContext === "function") {
      window.syncSearchContext({
        total: data.total,
        page: data.page,
        filtersSummary: buildFiltersSummary(body),
        visibleListings: data.items,
        filters: searchBodyToMatchFilters(body),
      });
    }

    if (!data.items.length) {
      resultsEl.innerHTML = '<div class="empty">Không tìm thấy phòng phù hợp. Thử nới rộng giá hoặc chọn thêm quận.</div>';
      document.getElementById("pagination").innerHTML = "";
      return;
    }

    resultsEl.innerHTML = `<div class="cards">${data.items.map(renderCard).join("")}</div>`;
    bindCardHandlers();
    renderPagination(data.total, data.page, data.size);
  } catch (err) {
    resultsEl.innerHTML = `<div class="error">Lỗi: ${escapeHtml(err.message)}</div>`;
  }
}

function renderPagination(total, page, size) {
  const totalPages = Math.max(1, Math.ceil(total / size));
  const el = document.getElementById("pagination");
  el.innerHTML = "";

  const prev = document.createElement("button");
  prev.textContent = "← Trước";
  prev.disabled = page <= 1;
  prev.addEventListener("click", () => runSearch(page - 1));

  const label = document.createElement("span");
  label.textContent = `Trang ${page}/${totalPages}`;
  label.style.alignSelf = "center";

  const next = document.createElement("button");
  next.textContent = "Sau →";
  next.disabled = page >= totalPages;
  next.addEventListener("click", () => runSearch(page + 1));

  el.appendChild(prev);
  el.appendChild(label);
  el.appendChild(next);
}

function resetFilters() {
  state.districts = [];
  state.roomLayouts = [];
  state.amenities = [];
  state.page = 1;
  applyPricePreset("all");
  applyAreaPreset("all");
  document.getElementById("qInput").value = "";
  document.getElementById("sortSelect").value = "price_asc";
  renderDistricts();
  renderRoomLayouts();
  renderAmenities();
  runSearch(1);
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    await loadMeta();
    document.getElementById("searchBtn").addEventListener("click", () => runSearch(1));
    document.getElementById("resetBtn").addEventListener("click", resetFilters);
    document.getElementById("sortSelect").addEventListener("change", () => runSearch(1));
    document.getElementById("drawerClose").addEventListener("click", closeDetail);
    document.getElementById("drawerBackdrop").addEventListener("click", closeDetail);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeDetail();
    });
    runSearch(1);
  } catch (err) {
    document.getElementById("results").innerHTML = `<div class="error">${escapeHtml(err.message)}</div>`;
  }
});
