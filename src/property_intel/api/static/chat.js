const STORAGE_KEY = "property_intel_chat_v1";

let chatState = {
  sessionId: null,
  messages: [],
  clientState: {
    last_filters: null,
    last_result_ids: [],
    focused_source_id: null,
    compared_listing_ids: [],
    user_preferences: {},
  },
};

let pageContext = {
  total: 0,
  page: 1,
  filters_summary: null,
  visible_listings: [],
};

let widgetOpen = false;
let widgetExpanded = false;

function loadChatFromStorage() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    chatState.sessionId = data.session_id || null;
    chatState.messages = data.messages || [];
    chatState.clientState = data.client_state || chatState.clientState;
  } catch {
    /* ignore corrupt storage */
  }
}

function saveChatToStorage() {
  sessionStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      session_id: chatState.sessionId,
      messages: chatState.messages,
      client_state: chatState.clientState,
      updated_at: new Date().toISOString(),
    })
  );
}

function formatVndChat(value) {
  if (value == null) return "—";
  return `${(value / 1e6).toFixed(1)} tr`;
}

function formatVndFull(value) {
  if (value == null) return "Liên hệ";
  return `${value.toLocaleString("vi-VN")}đ`;
}

function escapeHtmlChat(text) {
  const d = document.createElement("div");
  d.textContent = text;
  return d.innerHTML;
}

function formatAreaChat(min, max) {
  if (min == null && max == null) return "—";
  if (min != null && max != null && min !== max) return `${min}–${max}`;
  return String(min ?? max);
}

function amenityShort(list) {
  if (!list?.length) return "—";
  const short = {
    bep: "Bếp",
    dieu_hoa: "ĐH",
    may_giat: "MG",
    nong_lanh: "NL",
    ban_cong: "BC",
  };
  return list.map((a) => short[a] || a).join(", ");
}

function isCompareMessage(msg) {
  return (
    msg.toolCalls?.includes("compare_results") &&
    msg.cards?.length >= 2
  );
}

function formatAssistantContent(text) {
  const labels = ["Gợi ý", "Kết luận", "Ưu điểm", "Nhược điểm", "Tóm lại", "Lưu ý"];
  const labelPattern = new RegExp(`^(${labels.join("|")}):`, "gm");

  return text
    .split(/\n\n+/)
    .map((block) => {
      const raw = block.trim();
      if (!raw) return "";

      const lines = raw.split("\n");
      const bulletLines = lines.filter((l) => /^[-•]\s/.test(l.trim()));
      const numberedLines = lines.filter((l) => /^\d+\.\s/.test(l.trim()));

      if (bulletLines.length >= 2 || (bulletLines.length === lines.length && bulletLines.length > 0)) {
        const items = bulletLines.map((l) => escapeHtmlChat(l.replace(/^[-•]\s*/, "").trim()));
        return `<ul class="msg-list">${items.map((i) => `<li>${i}</li>`).join("")}</ul>`;
      }
      if (numberedLines.length >= 2 || (numberedLines.length === lines.length && numberedLines.length > 0)) {
        const items = numberedLines.map((l) => escapeHtmlChat(l.replace(/^\d+\.\s*/, "").trim()));
        return `<ol class="msg-list">${items.map((i) => `<li>${i}</li>`).join("")}</ol>`;
      }

      let safe = escapeHtmlChat(raw);
      safe = safe.replace(/\*\*(.+?)\*\*/g, '<strong class="msg-strong">$1</strong>');
      safe = safe.replace(labelPattern, '<span class="msg-label">$1:</span>');
      safe = safe.replace(/\n/g, "<br>");
      return `<p class="msg-para">${safe}</p>`;
    })
    .join("");
}

function formatMessageContent(text, role) {
  if (role === "user") {
    return escapeHtmlChat(text).replace(/\n/g, "<br>");
  }
  return formatAssistantContent(text);
}

function renderComparisonTable(cards) {
  const rows = cards
    .map((card, i) => {
      const fees = card.service_fees_summary?.slice(0, 2).join("; ") || "—";
      return `
        <tr class="cmp-row" data-source-id="${escapeHtmlChat(card.source_id)}" tabindex="0" role="button">
          <td class="cmp-num">${i + 1}</td>
          <td class="cmp-title">${escapeHtmlChat(card.title)}</td>
          <td>${escapeHtmlChat(card.district || "—")}</td>
          <td class="cmp-price">${formatVndFull(card.price_vnd)}</td>
          <td>${formatAreaChat(card.area_min_m2, card.area_max_m2)} m²</td>
          <td>${escapeHtmlChat(amenityShort(card.amenities))}</td>
          <td class="cmp-fees">${escapeHtmlChat(fees)}</td>
        </tr>`;
    })
    .join("");

  return `
    <div class="cmp-table-wrap">
      <div class="cmp-table-title">Bảng so sánh ${cards.length} phòng</div>
      <table class="cmp-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Phòng</th>
            <th>Quận</th>
            <th>Giá</th>
            <th>DT</th>
            <th>Tiện ích</th>
            <th>Phí DV</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <p class="cmp-hint">Bấm dòng để xem chi tiết phòng</p>
    </div>`;
}

function renderMiniCard(card) {
  const area = formatAreaChat(card.area_min_m2, card.area_max_m2);
  const platform = typeof resolvePlatform === "function" ? resolvePlatform(card) : "";
  const badge =
    platform && typeof platformLabel === "function"
      ? `<span class="platform-badge platform-badge-${platform}">${escapeHtmlChat(platformLabel(card))}</span>`
      : "";
  return `
    <div class="chat-card" data-source-id="${escapeHtmlChat(card.source_id)}">
      <div class="chat-card-head">
        <div class="chat-card-title">${escapeHtmlChat(card.title)}</div>
        ${badge}
      </div>
      <div class="chat-card-meta">${escapeHtmlChat(card.district || "")} · ${formatVndFull(card.price_vnd)}${area !== "—" ? " · " + area + " m²" : ""}</div>
    </div>`;
}

function renderCardsBlock(msg) {
  if (!msg.cards?.length) return "";
  if (isCompareMessage(msg)) {
    return renderComparisonTable(msg.cards);
  }
  if (msg.cards.length === 1) {
    return `<div class="chat-cards">${renderMiniCard(msg.cards[0])}</div>`;
  }
  return `<div class="chat-cards">${msg.cards.map(renderMiniCard).join("")}</div>`;
}

function updateContextBar() {
  const bar = document.getElementById("chatContextBar");
  const badge = document.getElementById("chatFabBadge");
  const n = pageContext.visible_listings?.length || 0;
  if (n > 0) {
    const summary = pageContext.filters_summary ? ` · ${pageContext.filters_summary}` : "";
    bar.textContent = `Đang xem ${n}/${pageContext.total} phòng${summary}`;
    badge.textContent = String(n);
    badge.classList.remove("hidden");
  } else {
    bar.textContent = "Tìm phòng trước, rồi hỏi AI so sánh";
    badge.classList.add("hidden");
  }
  renderQuickActions();
}

function renderQuickActions() {
  const el = document.getElementById("chatQuickActions");
  if (!el) return;
  const n = pageContext.visible_listings?.length || 0;
  if (n < 2) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = `
    <button type="button" class="chat-quick-btn" data-prompt="So sánh ${n} phòng đang hiển thị, nêu ưu nhược điểm từng căn">So sánh ${n} phòng</button>
    <button type="button" class="chat-quick-btn" data-prompt="Trong ${n} phòng này căn nào phù hợp nhất? Gợi ý và hỏi thêm nếu cần">Gợi ý phù hợp</button>`;
  el.querySelectorAll(".chat-quick-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      openChatWidget();
      sendChatMessage(btn.dataset.prompt);
    });
  });
}

function renderChatMessages() {
  const el = document.getElementById("chatMessages");
  if (!el) return;
  if (!chatState.messages.length) {
    const n = pageContext.visible_listings?.length || 0;
    el.innerHTML = `
      <div class="chat-welcome">
        <div class="chat-welcome-icon">✨</div>
        <p><strong>Trợ lý AI tìm phòng</strong></p>
        ${n > 0
          ? `<p class="chat-hint">Đang thấy <strong>${n} phòng</strong> trên màn hình.<br>Thử: <em>So sánh ${n} kết quả này</em></p>`
          : `<p class="chat-hint">Lọc và tìm phòng, sau đó hỏi tôi so sánh hoặc gợi ý.</p>`}
      </div>`;
    return;
  }
  el.innerHTML = chatState.messages
    .map((msg) => {
      const wide = isCompareMessage(msg) ? " chat-bubble-wide" : "";
      return `
        <div class="chat-bubble chat-bubble-${msg.role}${wide}">
          <div class="chat-bubble-content msg-prose">${formatMessageContent(msg.content, msg.role)}</div>
          ${renderCardsBlock(msg)}
        </div>`;
    })
    .join("");
  el.scrollTop = el.scrollHeight;
}

function openChatWidget() {
  const widget = document.getElementById("chatWidget");
  const fab = document.getElementById("chatFabBtn");
  widget.classList.remove("hidden");
  widget.setAttribute("aria-hidden", "false");
  fab.setAttribute("aria-expanded", "true");
  widgetOpen = true;
  document.getElementById("chatInput").focus();
}

function closeChatWidget() {
  const widget = document.getElementById("chatWidget");
  const fab = document.getElementById("chatFabBtn");
  widget.classList.add("hidden");
  widget.setAttribute("aria-hidden", "true");
  fab.setAttribute("aria-expanded", "false");
  widgetOpen = false;
  if (widgetExpanded) {
    widgetExpanded = false;
    widget.classList.remove("chat-widget-expanded");
    const expandBtn = document.getElementById("chatExpandBtn");
    if (expandBtn) {
      expandBtn.setAttribute("aria-pressed", "false");
      expandBtn.title = "Phóng to";
    }
  }
}

function toggleChatWidget(e) {
  if (e) {
    e.preventDefault();
    e.stopPropagation();
  }
  if (widgetOpen) closeChatWidget();
  else openChatWidget();
}

function toggleChatExpand() {
  widgetExpanded = !widgetExpanded;
  const widget = document.getElementById("chatWidget");
  const btn = document.getElementById("chatExpandBtn");
  widget.classList.toggle("chat-widget-expanded", widgetExpanded);
  btn.setAttribute("aria-pressed", String(widgetExpanded));
  btn.textContent = widgetExpanded ? "⛶" : "⛶";
  btn.title = widgetExpanded ? "Thu nhỏ" : "Phóng to";
}

async function sendChatMessage(text) {
  const input = document.getElementById("chatInput");
  const sendBtn = document.getElementById("chatSendBtn");
  const content = (text || input.value).trim();
  if (!content) return;

  openChatWidget();
  chatState.messages.push({ role: "user", content });
  input.value = "";
  renderChatMessages();
  sendBtn.disabled = true;

  const messagesEl = document.getElementById("chatMessages");
  const typing = document.createElement("div");
  typing.className = "chat-bubble chat-bubble-assistant chat-typing";
  typing.textContent = "Đang phân tích...";
  messagesEl.appendChild(typing);
  messagesEl.scrollTop = messagesEl.scrollHeight;

  try {
    const payload = {
      session_id: chatState.sessionId,
      messages: chatState.messages.map((m) => ({ role: m.role, content: m.content })),
      client_state: chatState.clientState,
      page_context: pageContext,
    };
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || res.statusText);

    chatState.sessionId = data.session_id;
    chatState.clientState = data.client_state;
    chatState.messages.push({
      role: "assistant",
      content: data.reply,
      cards: data.cards || [],
      toolCalls: data.tool_calls || [],
    });
    if (data.tool_calls?.includes("compare_results") && !widgetExpanded) {
      toggleChatExpand();
    }
    // Don't re-show comparison table on advise follow-ups
    saveChatToStorage();
  } catch (err) {
    chatState.messages.push({
      role: "assistant",
      content: `Xin lỗi, có lỗi xảy ra: ${err.message}`,
      cards: [],
      toolCalls: [],
    });
  } finally {
    sendBtn.disabled = false;
    renderChatMessages();
  }
}

function clearChat() {
  chatState = {
    sessionId: null,
    messages: [],
    clientState: {
      last_filters: chatState.clientState.last_filters,
      last_result_ids: pageContext.visible_listings.map((x) => x.source_id),
      focused_source_id: null,
      compared_listing_ids: [],
      user_preferences: {},
    },
  };
  sessionStorage.removeItem(STORAGE_KEY);
  renderChatMessages();
}

function openListingFromClick(target) {
  const row = target.closest("[data-source-id]");
  if (row && typeof openDetail === "function") {
    openDetail(row.dataset.sourceId);
  }
}

window.syncSearchContext = function ({ total, page, filtersSummary, visibleListings, filters }) {
  pageContext = {
    total: total || 0,
    page: page || 1,
    filters_summary: filtersSummary || null,
    visible_listings: visibleListings || [],
  };
  chatState.clientState.last_result_ids = pageContext.visible_listings.map((x) => x.source_id);
  if (filters) chatState.clientState.last_filters = filters;
  updateContextBar();
  if (!chatState.messages.length) renderChatMessages();
};

window.seedChat = function ({ prompt }) {
  openChatWidget();
  if (prompt) setTimeout(() => sendChatMessage(prompt), 100);
};

function initChat() {
  loadChatFromStorage();
  updateContextBar();
  renderChatMessages();

  const fab = document.getElementById("chatFabBtn");
  if (!fab) {
    console.error("chatFabBtn not found");
    return;
  }

  fab.addEventListener("click", toggleChatWidget);
  document.getElementById("chatWidgetClose")?.addEventListener("click", closeChatWidget);
  document.getElementById("chatExpandBtn")?.addEventListener("click", toggleChatExpand);
  document.getElementById("chatSendBtn")?.addEventListener("click", () => sendChatMessage());
  document.getElementById("chatInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });
  document.getElementById("chatClearBtn")?.addEventListener("click", clearChat);
  document.getElementById("chatMessages")?.addEventListener("click", (e) => openListingFromClick(e.target));
  document.getElementById("chatMessages")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      const row = e.target.closest(".cmp-row");
      if (row) {
        e.preventDefault();
        openListingFromClick(row);
      }
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && widgetOpen) closeChatWidget();
  });
}

document.addEventListener("DOMContentLoaded", initChat);
