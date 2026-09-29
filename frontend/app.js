const DEFAULT_API_URL = "http://localhost:8082";
const API_URL_KEY = "techguide.apiUrl";
const CHAT_KEY = "techguide.chat";

const conversation = document.querySelector("#conversation");
const welcome = document.querySelector("#welcome");
const form = document.querySelector("#chat-form");
const messageInput = document.querySelector("#message");
const sendButton = document.querySelector("#send");
const notice = document.querySelector("#notice");
const settings = document.querySelector("#api-settings");
const apiInput = document.querySelector("#api-url");
const chatView = document.querySelector("#chat-view");
const catalogView = document.querySelector("#catalog-view");
const catalogForm = document.querySelector("#catalog-form");
const catalogQuery = document.querySelector("#catalog-query");
const catalogResults = document.querySelector("#catalog-results");
const productDialog = document.querySelector("#product-dialog");

let apiURL = localStorage.getItem(API_URL_KEY) || DEFAULT_API_URL;
let chat = readStoredChat();
let busy = false;
let catalogMode = "browse";
let catalogPage = 1;
let catalogMeta = null;
let catalogActiveParams = null;
let catalogRequestID = 0;
let metadataLoaded = false;
let healthRequestID = 0;
let detailRequestID = 0;

apiInput.value = apiURL;
chat.turns.forEach((turn) => renderTurn(turn));
if (chat.turns.length) welcome.remove();

function readStoredChat() {
  try {
    const value = JSON.parse(sessionStorage.getItem(CHAT_KEY));
    if (value && Array.isArray(value.turns) && typeof value.sessionID === "string" && value.apiURL === apiURL) {
      return value;
    }
  } catch (_) {
    // A stale or malformed local display cache is safe to discard.
  }
  return { apiURL, sessionID: "", turns: [] };
}

function saveChat() {
  sessionStorage.setItem(CHAT_KEY, JSON.stringify(chat));
}

function showNotice(text) {
  notice.textContent = text;
  notice.hidden = !text;
}

function setBusy(value) {
  busy = value;
  sendButton.disabled = value;
  messageInput.disabled = value;
  document.querySelectorAll(".suggestion").forEach((button) => { button.disabled = value; });
}

function scrollToBottom() {
  conversation.scrollTop = conversation.scrollHeight;
}

function safeHTTPURL(value) {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch (_) {
    return "";
  }
}

function formatMoney(amount, currency) {
  if (amount === null || amount === undefined || amount === "") return "Price unavailable";
  const number = Number(amount);
  const display = Number.isFinite(number)
    ? new Intl.NumberFormat("en-EG", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number)
    : String(amount ?? "");
  return `${display} ${currency || "EGP"}`;
}

function appendFormattedText(parent, value) {
  const parts = String(value).split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  for (const part of parts) {
    if (!part) continue;
    if (part.startsWith("**") && part.endsWith("**")) {
      const strong = document.createElement("strong");
      strong.textContent = part.slice(2, -2);
      parent.append(strong);
    } else if (part.startsWith("`") && part.endsWith("`")) {
      const code = document.createElement("code");
      code.textContent = part.slice(1, -1);
      parent.append(code);
    } else {
      parent.append(document.createTextNode(part));
    }
  }
}

function renderAssistantMessage(message) {
  const content = document.createElement("div");
  content.className = "answer-content";
  const lines = String(message || "").replace(/\r\n?/g, "\n").split("\n");
  let paragraph = null;
  let list = null;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) { paragraph = null; list = null; continue; }
    const heading = line.match(/^#{1,3}\s+(.+)$/);
    const bullet = line.match(/^[-*•]\s+(.+)$/);
    const numbered = line.match(/^\d+[.)]\s+(.+)$/);
    if (heading) {
      paragraph = null;
      list = null;
      const title = document.createElement("h3");
      appendFormattedText(title, heading[1]);
      content.append(title);
    } else if (bullet || numbered) {
      paragraph = null;
      const kind = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== kind) {
        list = document.createElement(kind);
        content.append(list);
      }
      const item = document.createElement("li");
      appendFormattedText(item, (bullet || numbered)[1]);
      list.append(item);
    } else {
      list = null;
      if (!paragraph) {
        paragraph = document.createElement("p");
        content.append(paragraph);
      } else {
        paragraph.append(document.createElement("br"));
      }
      appendFormattedText(paragraph, line);
    }
  }
  return content;
}

function renderProducts(products) {
  const grid = document.createElement("div");
  grid.className = "products";
  for (const product of products) {
    const card = document.createElement("article");
    card.className = "product-card";
    const visual = document.createElement("div");
    visual.className = "product-image";
    const imageURL = safeHTTPURL(product.image_url);
    if (imageURL) {
      const img = document.createElement("img");
      img.src = imageURL;
      img.alt = "";
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.onerror = () => { visual.replaceChildren(document.createTextNode("✳")); };
      visual.append(img);
    } else {
      visual.textContent = "✳";
    }
    const info = document.createElement("div");
    info.className = "product-info";
    const provider = document.createElement("div");
    provider.className = "product-provider";
    provider.textContent = product.provider || "Catalog listing";
    const name = document.createElement("div");
    name.className = "product-name";
    name.textContent = product.name || `Product #${product.id}`;
    const bottom = document.createElement("div");
    bottom.className = "product-bottom";
    const price = document.createElement("span");
    price.className = "product-price";
    price.textContent = formatMoney(product.price, product.currency);
    const stock = document.createElement("span");
    stock.className = `stock${product.in_stock === false ? " out" : ""}`;
    stock.textContent = product.in_stock === true ? "In stock" : product.in_stock === false ? "Out of stock" : "Stock unknown";
    bottom.append(price, stock);
    info.append(provider, name, bottom);
    const purchaseURL = safeHTTPURL(product.canonical_product_url);
    if (purchaseURL) {
      const link = document.createElement("a");
      link.className = "product-link";
      link.href = purchaseURL;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View at store ↗";
      info.append(link);
    }
    card.append(visual, info);
    grid.append(card);
  }
  return grid;
}

function renderTurn(turn) {
  const row = document.createElement("div");
  row.className = `turn ${turn.role === "user" ? "user" : "assistant"}`;
  if (turn.role !== "user") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.setAttribute("aria-hidden", "true");
    avatar.textContent = "✳";
    row.append(avatar);
  }
  const body = document.createElement("div");
  body.className = "turn-body";
  const label = document.createElement("div");
  label.className = "turn-label";
  label.textContent = turn.role === "user" ? "You" : "Assistant";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (turn.role === "user") bubble.textContent = turn.message;
  else bubble.append(renderAssistantMessage(turn.message));
  body.append(label, bubble);
  if (turn.role !== "user" && Array.isArray(turn.products) && turn.products.length) {
    const recommendations = document.createElement("section");
    recommendations.className = "recommendations";
    const heading = document.createElement("h3");
    heading.textContent = "Catalog matches";
    recommendations.append(heading, renderProducts(turn.products));
    body.append(recommendations);
  }
  if (turn.estimated_total?.amount) {
    const total = document.createElement("div");
    total.className = "total";
    total.textContent = `Estimated total: ${formatMoney(turn.estimated_total.amount, turn.estimated_total.currency)}`;
    body.append(total);
  }
  row.append(body);
  conversation.append(row);
  scrollToBottom();
  return row;
}

function clearChat() {
  chat = { apiURL, sessionID: "", turns: [] };
  saveChat();
  conversation.replaceChildren(welcome);
  showNotice("");
  messageInput.focus();
}

async function requestJSON(path, options) {
  const response = await fetch(`${apiURL}${path}`, options);
  let payload;
  try {
    payload = await response.json();
  } catch (_) {
    throw new Error(`The API returned an invalid response (${response.status}).`);
  }
  if (!response.ok || payload?.success !== true) {
    const error = new Error(payload?.error?.message || `Request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function sendMessage(text) {
  const message = text.trim();
  if (!message || busy) return;
  if (welcome.isConnected) welcome.remove();
  showNotice("");
  const userTurn = { role: "user", message };
  chat.turns.push(userTurn);
  renderTurn(userTurn);
  saveChat();
  messageInput.value = "";
  messageInput.style.height = "auto";
  setBusy(true);
  const pending = renderTurn({ role: "assistant", message: "Thinking…" });
  const typing = document.createElement("span");
  typing.className = "typing";
  typing.setAttribute("aria-label", "Thinking");
  typing.append(document.createElement("span"), document.createElement("span"), document.createElement("span"));
  pending.querySelector(".bubble").replaceChildren(typing);

  try {
    const payload = await requestJSON("/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, ...(chat.sessionID ? { session_id: chat.sessionID } : {}) }),
    });
    const result = payload.data;
    if (!result || typeof result.session_id !== "string" || typeof result.message !== "string") {
      throw new Error("The backend returned an unexpected response.");
    }
    chat.sessionID = result.session_id;
    const assistantTurn = {
      role: "assistant",
      message: result.message,
      products: Array.isArray(result.products) ? result.products : [],
      estimated_total: result.estimated_total || null,
    };
    chat.turns.push(assistantTurn);
    pending.replaceWith(renderTurn(assistantTurn));
    saveChat();
  } catch (error) {
    pending.remove();
    if (error.status === 404 && chat.sessionID) {
      chat.sessionID = "";
      saveChat();
      showNotice("That conversation expired. Start a new chat and send your question again.");
    } else {
      showNotice(error instanceof TypeError ? "Could not reach the backend. Check the API URL and that the server is running." : error.message);
    }
  } finally {
    setBusy(false);
    messageInput.focus();
    scrollToBottom();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(messageInput.value);
});
messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});
messageInput.addEventListener("input", () => {
  messageInput.style.height = "auto";
  messageInput.style.height = `${Math.min(messageInput.scrollHeight, 140)}px`;
});
document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => sendMessage(button.dataset.prompt));
});
document.querySelector("#new-chat").addEventListener("click", () => {
  if (!busy) clearChat();
});
document.querySelector("#api-settings-toggle").addEventListener("click", () => {
  settings.hidden = !settings.hidden;
  if (!settings.hidden) apiInput.focus();
});
settings.addEventListener("submit", (event) => {
  event.preventDefault();
  if (busy) return;
  const url = safeHTTPURL(apiInput.value.trim());
  if (!url) { showNotice("Enter a valid http or https backend URL."); return; }
  apiURL = url.replace(/\/+$/, "");
  localStorage.setItem(API_URL_KEY, apiURL);
  apiInput.value = apiURL;
  settings.hidden = true;
  clearChat();
  metadataLoaded = false;
  catalogRequestID++;
  detailRequestID++;
  if (productDialog.open) productDialog.close();
  catalogMeta = null;
  catalogActiveParams = null;
  catalogResults.replaceChildren();
  document.querySelector("#catalog-count").textContent = "Search the catalog";
  document.querySelector("#catalog-summary").textContent = "Use a model name, or switch to Browse & filter.";
  document.querySelector("#catalog-page-label").textContent = "";
  document.querySelector("#catalog-pagination").hidden = true;
  document.querySelector("#catalog-submit").disabled = false;
  for (const id of ["filter-category", "filter-provider", "filter-brand"]) {
    const select = document.querySelector(`#${id}`);
    select.replaceChildren(select.firstElementChild);
  }
  checkHealth();
  if (!catalogView.hidden) {
    loadCatalogMetadata();
    if (catalogMode === "browse") loadCatalog(1);
  }
});

async function checkHealth() {
  const requestID = ++healthRequestID;
  const dot = document.querySelector("#health-dot");
  const status = document.querySelector("#health-status");
  dot.className = "online-dot checking";
  status.textContent = "Checking API…";
  try {
    const payload = await requestJSON("/health");
    if (requestID !== healthRequestID) return;
    if (payload.data?.status !== "ok") throw new Error("Unexpected health response");
    dot.className = "online-dot";
    status.textContent = "API responding";
  } catch (_) {
    if (requestID !== healthRequestID) return;
    dot.className = "online-dot offline";
    status.textContent = "API unreachable";
  }
}

function switchView(view) {
  const catalog = view === "catalog";
  catalogView.hidden = !catalog;
  chatView.hidden = catalog;
  document.querySelector("#tab-catalog").classList.toggle("active", catalog);
  document.querySelector("#tab-chat").classList.toggle("active", !catalog);
  document.querySelector("#tab-catalog").setAttribute("aria-current", catalog ? "page" : "false");
  document.querySelector("#tab-chat").setAttribute("aria-current", catalog ? "false" : "page");
  if (catalog) {
    loadCatalogMetadata();
    if (!catalogMeta && !catalogResults.childElementCount) loadCatalog(1);
  }
}

function setCatalogMode(mode) {
  if (catalogMode !== mode) {
    catalogRequestID++;
    catalogMeta = null;
    catalogActiveParams = null;
    catalogResults.replaceChildren();
    document.querySelector("#catalog-pagination").hidden = true;
    document.querySelector("#catalog-submit").disabled = false;
    document.querySelector("#catalog-count").textContent = "Search the catalog";
    document.querySelector("#catalog-summary").textContent = "Set a query or filters, then search.";
    document.querySelector("#catalog-page-label").textContent = "";
    showCatalogNotice("");
  }
  catalogMode = mode;
  const browse = mode === "browse";
  document.querySelector("#catalog-filters").hidden = !browse;
  document.querySelector("#mode-search").classList.toggle("active", !browse);
  document.querySelector("#mode-browse").classList.toggle("active", browse);
  document.querySelector("#mode-search").setAttribute("aria-pressed", String(!browse));
  document.querySelector("#mode-browse").setAttribute("aria-pressed", String(browse));
  document.querySelector("#catalog-route").textContent = browse ? "GET /products" : "GET /products/search";
  document.querySelector("#catalog-submit").textContent = browse ? "Apply filters" : "Search products";
  catalogQuery.required = !browse;
}

function showCatalogNotice(message) {
  const target = document.querySelector("#catalog-notice");
  target.textContent = message;
  target.hidden = !message;
}

function fillFilter(id, items, textKey) {
  const select = document.querySelector(`#${id}`);
  const current = select.value;
  select.replaceChildren(select.firstElementChild);
  for (const item of items) {
    const option = document.createElement("option");
    option.value = String(item.id);
    option.textContent = item[textKey];
    select.append(option);
  }
  select.value = current;
}

async function loadCatalogMetadata() {
  if (metadataLoaded) return;
  metadataLoaded = true;
  const currentURL = apiURL;
  const endpoints = [
    ["/products/categories", "filter-category", "slug"],
    ["/products/providers", "filter-provider", "name"],
    ["/products/brands", "filter-brand", "name"],
  ];
  const results = await Promise.allSettled(endpoints.map(([path]) => requestJSON(path)));
  if (apiURL !== currentURL) return;
  let failed = false;
  results.forEach((result, index) => {
    if (result.status === "fulfilled") {
      fillFilter(endpoints[index][1], Array.isArray(result.value.data) ? result.value.data : [], endpoints[index][2]);
    } else {
      failed = true;
    }
  });
  if (failed) {
    metadataLoaded = false;
    showCatalogNotice("Some filter options could not be loaded. Open this tab again to retry.");
  }
}

function catalogParams(page) {
  const query = catalogQuery.value.trim();
  const params = new URLSearchParams({ page: String(page), limit: document.querySelector("#catalog-limit").value });
  if (query) params.set("q", query);
  if (catalogMode === "browse") {
    const fields = [
      ["filter-category", "category_ids"], ["filter-provider", "provider_ids"],
      ["filter-brand", "brand_ids"], ["filter-stock", "in_stock"],
      ["filter-min-price", "min_price"], ["filter-max-price", "max_price"],
      ["filter-sort", "sort"],
    ];
    for (const [id, key] of fields) {
      const value = document.querySelector(`#${id}`).value.trim();
      if (value) params.set(key, value);
    }
  }
  return params;
}

function catalogImage(product) {
  const visual = document.createElement("div");
  visual.className = "product-image";
  const url = safeHTTPURL(product.image_url);
  if (!url) { visual.textContent = "✳"; return visual; }
  const image = document.createElement("img");
  image.src = url;
  image.alt = "";
  image.loading = "lazy";
  image.referrerPolicy = "no-referrer";
  image.onerror = () => { visual.textContent = "✳"; };
  visual.append(image);
  return visual;
}

function catalogCard(product) {
  const card = document.createElement("article");
  card.className = "product-card";
  const info = document.createElement("div");
  info.className = "product-info";
  const provider = document.createElement("div");
  provider.className = "product-provider";
  provider.textContent = product.provider?.name || "Catalog listing";
  const name = document.createElement("div");
  name.className = "product-name";
  name.textContent = product.name || `Product #${product.id}`;
  const meta = document.createElement("div");
  meta.className = "product-meta";
  meta.textContent = [product.category?.slug, product.brand?.name].filter(Boolean).join(" · ");
  const bottom = document.createElement("div");
  bottom.className = "product-bottom";
  const price = document.createElement("span");
  price.className = "product-price";
  price.textContent = formatMoney(product.price, product.currency);
  const stock = document.createElement("span");
  stock.className = `stock${product.in_stock === false ? " out" : ""}`;
  stock.textContent = product.in_stock === true ? "In stock" : product.in_stock === false ? "Out of stock" : "Stock unknown";
  bottom.append(price, stock);
  const details = document.createElement("button");
  details.type = "button";
  details.className = "detail-button";
  details.textContent = "View details";
  details.addEventListener("click", () => showProductDetail(product.id));
  info.append(provider, name, meta, bottom, details);
  card.append(catalogImage(product), info);
  return card;
}

async function loadCatalog(page = 1, useActiveParams = false) {
  const min = document.querySelector("#filter-min-price").value;
  const max = document.querySelector("#filter-max-price").value;
  if (!useActiveParams && catalogMode === "browse" && min !== "" && max !== "" && Number(min) > Number(max)) {
    showCatalogNotice("Minimum price cannot exceed maximum price.");
    return;
  }
  if (!useActiveParams && catalogMode === "search" && !catalogQuery.value.trim()) {
    showCatalogNotice("Enter a product name or model to search.");
    return;
  }
  showCatalogNotice("");
  const requestID = ++catalogRequestID;
  const mode = catalogMode;
  const path = mode === "browse" ? "/products" : "/products/search";
  const params = useActiveParams && catalogActiveParams ? new URLSearchParams(catalogActiveParams) : catalogParams(page);
  params.set("page", String(page));
  const submit = document.querySelector("#catalog-submit");
  submit.disabled = true;
  document.querySelector("#catalog-pagination").hidden = true;
  document.querySelector("#catalog-count").textContent = "Loading products…";
  document.querySelector("#catalog-page-label").textContent = "";
  catalogResults.replaceChildren();
  const loading = document.createElement("div");
  loading.className = "catalog-empty";
  loading.textContent = "Loading products…";
  catalogResults.append(loading);
  try {
    const payload = await requestJSON(`${path}?${params}`);
    if (requestID !== catalogRequestID) return;
    const items = mode === "browse" ? payload.data?.items : payload.data;
    const meta = mode === "browse" ? payload.data?.meta : payload.meta;
    if (!Array.isArray(items) || !meta || !Number.isInteger(meta.page)) throw new Error("The catalog returned an unexpected response.");
    catalogPage = meta.page;
    catalogMeta = meta;
    catalogActiveParams = new URLSearchParams(params);
    catalogResults.replaceChildren();
    if (items.length) items.forEach((product) => catalogResults.append(catalogCard(product)));
    else {
      const empty = document.createElement("div");
      empty.className = "catalog-empty";
      empty.textContent = "No products match this search. Try a broader query or change the filters.";
      catalogResults.append(empty);
    }
    document.querySelector("#catalog-count").textContent = `${meta.total_items.toLocaleString()} product${meta.total_items === 1 ? "" : "s"} found`;
    document.querySelector("#catalog-summary").textContent = mode === "browse" ? "Filtered catalog results" : "Fuzzy search results";
    document.querySelector("#catalog-page-label").textContent = meta.total_pages ? `Page ${meta.page} of ${meta.total_pages}` : "";
    document.querySelector("#catalog-page-summary").textContent = `Page ${meta.page} of ${meta.total_pages}`;
    document.querySelector("#catalog-prev").disabled = meta.page <= 1;
    document.querySelector("#catalog-next").disabled = meta.page >= meta.total_pages;
    document.querySelector("#catalog-pagination").hidden = meta.total_pages <= 1;
  } catch (error) {
    if (requestID !== catalogRequestID) return;
    catalogMeta = null;
    catalogActiveParams = null;
    catalogResults.replaceChildren();
    document.querySelector("#catalog-count").textContent = "Could not load products";
    showCatalogNotice(error instanceof TypeError ? "Could not reach the backend. Check the API URL and that the server is running." : error.message);
  } finally {
    if (requestID === catalogRequestID) submit.disabled = false;
  }
}

async function showProductDetail(id) {
  const requestID = ++detailRequestID;
  const content = document.querySelector("#product-dialog-content");
  content.textContent = "Loading product details…";
  productDialog.showModal();
  const currentURL = apiURL;
  try {
    const payload = await requestJSON(`/products/${encodeURIComponent(id)}`);
    if (!productDialog.open || currentURL !== apiURL || requestID !== detailRequestID) return;
    const product = payload.data;
    if (!product || product.id !== id) throw new Error("The product detail response was invalid.");
    const title = document.createElement("h3");
    title.textContent = product.name;
    const tags = document.createElement("div");
    tags.className = "detail-tags";
    for (const label of [product.category?.slug, product.brand?.name, product.provider?.name]) {
      if (!label) continue;
      const tag = document.createElement("span");
      tag.textContent = label;
      tags.append(tag);
    }
    const price = document.createElement("div");
    price.className = "detail-price";
    price.textContent = formatMoney(product.price, product.currency);
    const stock = document.createElement("span");
    stock.className = `detail-stock${product.in_stock === false ? " out" : ""}`;
    stock.textContent = product.in_stock === true ? "In stock" : product.in_stock === false ? "Out of stock" : "Stock unknown";
    price.append(stock);
    const productID = document.createElement("div");
    productID.className = "detail-id";
    productID.textContent = `Catalog product #${product.id}`;
    content.replaceChildren(catalogImage(product), title, tags, price);
    const url = safeHTTPURL(product.canonical_product_url);
    if (url) {
      const link = document.createElement("a");
      link.className = "product-link";
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View at store ↗";
      content.append(link);
    }
    content.append(productID);
  } catch (error) {
    if (productDialog.open && requestID === detailRequestID) content.textContent = error instanceof TypeError ? "Could not reach the backend." : error.message;
  }
}

document.querySelector("#tab-chat").addEventListener("click", () => switchView("chat"));
document.querySelector("#tab-catalog").addEventListener("click", () => switchView("catalog"));
document.querySelector("#mode-search").addEventListener("click", () => setCatalogMode("search"));
document.querySelector("#mode-browse").addEventListener("click", () => { setCatalogMode("browse"); if (!catalogMeta) loadCatalog(1); });
catalogForm.addEventListener("submit", (event) => { event.preventDefault(); loadCatalog(1); });
document.querySelector("#catalog-prev").addEventListener("click", () => { if (catalogMeta && catalogPage > 1) loadCatalog(catalogPage - 1, true); });
document.querySelector("#catalog-next").addEventListener("click", () => { if (catalogMeta && catalogPage < catalogMeta.total_pages) loadCatalog(catalogPage + 1, true); });
document.querySelector("#product-dialog-close").addEventListener("click", () => productDialog.close());
productDialog.addEventListener("close", () => { detailRequestID++; });
document.querySelector("#health-check").addEventListener("click", checkHealth);
setCatalogMode("browse");
checkHealth();
