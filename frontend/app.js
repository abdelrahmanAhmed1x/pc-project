const DEFAULT_API_URL = "http://localhost:8082";
const API_URL_KEY = "techguide.apiUrl";

const settings = document.querySelector("#api-settings");
const apiInput = document.querySelector("#api-url");
const catalogForm = document.querySelector("#catalog-form");
const catalogQuery = document.querySelector("#catalog-query");
const catalogResults = document.querySelector("#catalog-results");
const productDialog = document.querySelector("#product-dialog");

let apiURL = localStorage.getItem(API_URL_KEY) || DEFAULT_API_URL;
let catalogMode = "browse";
let catalogPage = 1;
let catalogMeta = null;
let catalogActiveParams = null;
let catalogRequestID = 0;
let metadataLoaded = false;
let healthRequestID = 0;
let detailRequestID = 0;

apiInput.value = apiURL;

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

async function requestJSON(path) {
  const response = await fetch(`${apiURL}${path}`);
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

document.querySelector("#api-settings-toggle").addEventListener("click", () => {
  settings.hidden = !settings.hidden;
  if (!settings.hidden) apiInput.focus();
});
settings.addEventListener("submit", (event) => {
  event.preventDefault();
  const url = safeHTTPURL(apiInput.value.trim());
  if (!url) { showCatalogNotice("Enter a valid http or https backend URL."); return; }
  apiURL = url.replace(/\/+$/, "");
  localStorage.setItem(API_URL_KEY, apiURL);
  apiInput.value = apiURL;
  settings.hidden = true;
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
  loadCatalogMetadata();
  if (catalogMode === "browse") loadCatalog(1);
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
    showCatalogNotice("Some filter options could not be loaded. Retry by saving the API settings.");
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

document.querySelector("#mode-search").addEventListener("click", () => setCatalogMode("search"));
document.querySelector("#mode-browse").addEventListener("click", () => { setCatalogMode("browse"); if (!catalogMeta) loadCatalog(1); });
catalogForm.addEventListener("submit", (event) => { event.preventDefault(); loadCatalog(1); });
document.querySelector("#catalog-prev").addEventListener("click", () => { if (catalogMeta && catalogPage > 1) loadCatalog(catalogPage - 1, true); });
document.querySelector("#catalog-next").addEventListener("click", () => { if (catalogMeta && catalogPage < catalogMeta.total_pages) loadCatalog(catalogPage + 1, true); });
document.querySelector("#product-dialog-close").addEventListener("click", () => productDialog.close());
productDialog.addEventListener("close", () => { detailRequestID++; });
document.querySelector("#health-check").addEventListener("click", checkHealth);
setCatalogMode("browse");
loadCatalogMetadata();
loadCatalog(1);
checkHealth();
