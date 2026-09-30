<script lang="ts">
  import { onMount } from 'svelte';
  import ProductCard from './ProductCard.svelte';
  import {
    catalogSearchParams,
    emptyFilters,
    fetchCatalog,
    fetchFacets,
    fetchProduct,
    formatPrice,
    safeExternalURL,
    type CatalogFilters,
    type Facet,
    type PageMeta,
    type Product,
    type ProductDetail,
  } from './lib/api';

  let filters = $state<CatalogFilters>({ ...emptyFilters });
  let applied = $state<CatalogFilters>({ ...emptyFilters });
  let categories = $state<Facet[]>([]);
  let providers = $state<Facet[]>([]);
  let brands = $state<Facet[]>([]);
  let items = $state<Product[]>([]);
  let meta = $state<PageMeta | null>(null);
  let page = $state(1);
  let loading = $state(true);
  let error = $state('');
  let queryError = $state('');
  let filterError = $state(false);
  let filtersOpen = $state(false);
  let detail = $state<ProductDetail | null>(null);
  let detailLoading = $state(false);
  let detailError = $state('');
  let detailDialog: HTMLDialogElement;
  let closeTimer: ReturnType<typeof setTimeout> | undefined;
  let catalogAbort: AbortController | undefined;
  let detailAbort: AbortController | undefined;
  let facetAbort: AbortController | undefined;

  function readLocation(): { filters: CatalogFilters; page: number } {
    const params = new URLSearchParams(window.location.search);
    const value = (key: string) => params.get(key) || '';
    const parsedPage = Number(value('page'));
    const parsedLimit = value('limit');
    return {
      filters: {
        q: value('q'),
        category: value('category_ids'),
        provider: value('provider_ids'),
        brand: value('brand_ids'),
        stock: value('in_stock'),
        minPrice: value('min_price'),
        maxPrice: value('max_price'),
        sort: value('sort'),
        limit: ['12', '24', '48'].includes(parsedLimit) ? parsedLimit : '12',
      },
      page: Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1,
    };
  }

  function updateLocation(nextPage: number) {
    const params = catalogSearchParams(applied, nextPage);
    window.history.pushState(null, '', `${window.location.pathname}?${params}`);
  }

  async function loadProducts(nextPage: number) {
    catalogAbort?.abort();
    const controller = new AbortController();
    catalogAbort = controller;
    loading = true;
    error = '';
    try {
      const result = await fetchCatalog(applied, nextPage, controller.signal);
      if (controller.signal.aborted) return;
      items = result.items;
      meta = result.meta;
      page = result.meta.page;
    } catch (reason) {
      if (controller.signal.aborted) return;
      items = [];
      meta = null;
      error = reason instanceof TypeError
        ? 'The catalog is unavailable. Check that the backend is running.'
        : reason instanceof Error ? reason.message : 'Could not load products.';
    } finally {
      if (!controller.signal.aborted) loading = false;
    }
  }

  async function loadFilters() {
    facetAbort?.abort();
    const controller = new AbortController();
    facetAbort = controller;
    filterError = false;
    try {
      const facets = await fetchFacets(controller.signal);
      if (controller.signal.aborted) return;
      categories = facets.categories;
      providers = facets.providers;
      brands = facets.brands;
    } catch {
      if (!controller.signal.aborted) filterError = true;
    }
  }

  function applyFilters() {
    const min = String(filters.minPrice ?? '').trim();
    const max = String(filters.maxPrice ?? '').trim();
    if ((min !== '' && (!Number.isFinite(Number(min)) || Number(min) < 0)) ||
        (max !== '' && (!Number.isFinite(Number(max)) || Number(max) < 0))) {
      error = 'Enter a valid non-negative price.';
      return;
    }
    if (min !== '' && max !== '' && Number(min) > Number(max)) {
      error = 'Minimum price cannot be higher than maximum price.';
      return;
    }
    applied = { ...filters, q: filters.q.trim(), minPrice: min, maxPrice: max };
    queryError = '';
    filtersOpen = false;
    updateLocation(1);
    void loadProducts(1);
  }

  function submitSearch() {
    if (!filters.q.trim()) {
      queryError = 'Enter a product name or model to search.';
      document.getElementById('hero-search')?.focus();
      return;
    }
    applyFilters();
  }

  function clearFilters() {
    filters = { ...emptyFilters };
    applyFilters();
  }

  function changePage(nextPage: number) {
    if (!meta || nextPage < 1 || nextPage > meta.total_pages) return;
    updateLocation(nextPage);
    void loadProducts(nextPage);
    document.getElementById('catalog')?.scrollIntoView({ behavior: 'smooth' });
  }

  async function openDetail(id: number) {
    detailAbort?.abort();
    const controller = new AbortController();
    detailAbort = controller;
    detail = null;
    detailError = '';
    detailLoading = true;
    detailDialog.showModal();
    try {
      const product = await fetchProduct(id, controller.signal);
      if (!controller.signal.aborted) detail = product;
    } catch (reason) {
      if (!controller.signal.aborted) {
        detailError = reason instanceof Error ? reason.message : 'Could not load product details.';
      }
    } finally {
      if (!controller.signal.aborted) detailLoading = false;
    }
  }

  function closeDetail() {
    if (closeTimer) return;
    detailAbort?.abort();
    detailDialog.classList.add('is-closing');
    const duration = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 180;
    closeTimer = setTimeout(() => {
      detailDialog.close();
      detailDialog.classList.remove('is-closing');
      closeTimer = undefined;
    }, duration);
  }

  function onPopState() {
    const location = readLocation();
    filters = { ...location.filters };
    applied = { ...location.filters };
    void loadProducts(location.page);
  }

  onMount(() => {
    const location = readLocation();
    filters = { ...location.filters };
    applied = { ...location.filters };
    void loadProducts(location.page);
    void loadFilters();
    return () => {
      catalogAbort?.abort();
      detailAbort?.abort();
      facetAbort?.abort();
      if (closeTimer) clearTimeout(closeTimer);
    };
  });
</script>

<svelte:window onpopstate={onPopState} />

<a href="#main" class="sr-only focus:not-sr-only focus:fixed focus:z-[100] focus:m-3 focus:rounded-lg focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-content">Skip to content</a>

<div class="catalog-page min-h-screen">
  <header class="site-header sticky top-0 z-30 border-b border-base-300">
    <div class="mx-auto flex h-15 max-w-[1400px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
      <a href="#main" class="brand-link flex shrink-0 items-center gap-2.5" aria-label="Tech Guide home">
        <span class="brand-mark grid size-7 place-items-center border border-primary text-[11px] font-bold text-primary" aria-hidden="true">TG</span>
        <span class="text-[15px] font-bold tracking-tight text-base-content">tech<span class="font-normal">guide</span></span>
      </a>
      <span class="font-price text-xs font-medium tracking-wide text-muted">EGP / EGYPT</span>
    </div>
  </header>

  <main id="main" class="mx-auto max-w-[1400px] px-4 pb-20 sm:px-6 lg:px-8">
    <section class="hero-panel border-b border-base-300 py-10 sm:py-12 lg:py-16" aria-labelledby="hero-title">
      <div class="max-w-3xl">
        <p class="hero-kicker mb-4 text-xs font-medium uppercase tracking-[0.18em] text-muted">Component catalog <span class="mx-2 text-primary">/</span> Egypt</p>
        <h1 id="hero-title" class="hero-title max-w-2xl text-[clamp(2.4rem,5vw,4.4rem)] leading-[1.04] font-semibold tracking-[-0.055em] text-base-content">
          Find the part you need.
        </h1>
        <p class="hero-copy mt-4 max-w-xl text-sm leading-relaxed text-muted sm:text-base">
          Search store listings, compare prices, and narrow the catalog by the details that matter.
        </p>
        <form class="search-form mt-8 flex max-w-2xl flex-col gap-2 sm:flex-row" onsubmit={(event) => { event.preventDefault(); submitSearch(); }} role="search">
          <label class="sr-only" for="hero-search">Search by product name or model</label>
          <div class="relative min-w-0 flex-1">
            <svg class="search-icon pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.3" stroke="currentColor" stroke-width="1.7"/><path d="m15.5 15.5 5 5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>
            <input id="hero-search" class="input input-lg w-full border-base-300 bg-base-200 pl-11 text-sm" type="search" bind:value={filters.q} oninput={() => { queryError = ''; }} aria-invalid={queryError ? 'true' : undefined} aria-describedby={queryError ? 'search-error' : undefined} placeholder="Part, model, or keyword" />
          </div>
          <button type="submit" class="btn btn-primary btn-lg search-button px-7">Search <span aria-hidden="true">→</span></button>
        </form>
        {#if queryError}<p id="search-error" class="mt-2 text-sm text-error" role="alert">{queryError}</p>{/if}
      </div>
    </section>

    <section id="catalog" class="mt-9 scroll-mt-24" aria-labelledby="catalog-title">
      <div class="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p class="section-index mb-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted">01 / Products</p>
          <h2 id="catalog-title" class="text-2xl font-semibold tracking-[-0.035em] text-base-content sm:text-[28px]">Browse components</h2>
        </div>
        <button type="button" class="btn btn-outline btn-sm filter-toggle lg:hidden" aria-expanded={filtersOpen} aria-controls="filters" onclick={() => { filtersOpen = !filtersOpen; }}>
          Filters <span aria-hidden="true">{filtersOpen ? '−' : '+'}</span>
        </button>
      </div>

      <div class="grid gap-6 lg:grid-cols-[250px_minmax(0,1fr)] xl:grid-cols-[270px_minmax(0,1fr)]">
        <aside id="filters" class:filter-open={filtersOpen} class="filter-shell h-fit scroll-mt-24 border border-base-300 p-5 lg:sticky lg:top-24" aria-label="Product filters">
          <div class="mb-5 flex items-center justify-between border-b border-base-300 pb-4">
            <h3 class="text-sm font-semibold">Filters</h3>
            <button type="button" class="btn btn-ghost btn-xs text-muted" onclick={clearFilters}>Clear all</button>
          </div>
          {#if filterError}
            <div class="alert alert-warning mb-4 text-xs" role="status">
              <span>Filter choices are unavailable.</span>
              <button type="button" class="btn btn-ghost btn-xs" onclick={() => void loadFilters()}>Retry</button>
            </div>
          {/if}
          <form class="space-y-5" onsubmit={(event) => { event.preventDefault(); applyFilters(); }}>
            <div>
              <label class="mb-2 block text-xs font-bold uppercase tracking-wider text-muted" for="category">Category</label>
              <select id="category" class="select w-full border-base-300 bg-base-100" bind:value={filters.category}>
                <option value="">All categories</option>
                {#each categories as category (category.id)}
                  <option value={String(category.id)}>{category.slug?.replaceAll('-', ' ') || category.name}</option>
                {/each}
              </select>
            </div>
            <div>
              <label class="mb-2 block text-xs font-bold uppercase tracking-wider text-muted" for="provider">Store</label>
              <select id="provider" class="select w-full border-base-300 bg-base-100" bind:value={filters.provider}>
                <option value="">All stores</option>
                {#each providers as provider (provider.id)}
                  <option value={String(provider.id)}>{provider.name}</option>
                {/each}
              </select>
            </div>
            <div>
              <label class="mb-2 block text-xs font-bold uppercase tracking-wider text-muted" for="brand">Brand</label>
              <select id="brand" class="select w-full border-base-300 bg-base-100" bind:value={filters.brand}>
                <option value="">All brands</option>
                {#each brands as brand (brand.id)}
                  <option value={String(brand.id)}>{brand.name}</option>
                {/each}
              </select>
            </div>
            <div>
              <label class="mb-2 block text-xs font-bold uppercase tracking-wider text-muted" for="stock">Availability</label>
              <select id="stock" class="select w-full border-base-300 bg-base-100" bind:value={filters.stock}>
                <option value="">Any stock status</option>
                <option value="true">In stock</option>
                <option value="false">Out of stock</option>
              </select>
            </div>
            <fieldset>
              <legend class="mb-2 text-xs font-bold uppercase tracking-wider text-muted">Price range · EGP</legend>
              <div class="grid grid-cols-2 gap-2">
                <div>
                  <label class="sr-only" for="min-price">Minimum price in EGP</label>
                  <input id="min-price" class="input w-full border-base-300 bg-base-100 text-sm" type="number" min="0" step="0.01" placeholder="Min" bind:value={filters.minPrice} />
                </div>
                <div>
                  <label class="sr-only" for="max-price">Maximum price in EGP</label>
                  <input id="max-price" class="input w-full border-base-300 bg-base-100 text-sm" type="number" min="0" step="0.01" placeholder="Max" bind:value={filters.maxPrice} />
                </div>
              </div>
            </fieldset>
            <button type="submit" class="btn btn-primary w-full">Apply filters <span aria-hidden="true">→</span></button>
          </form>
        </aside>

        <div class="min-w-0">
          <div class="results-bar relative mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-base-300 pb-4">
            {#if loading}<span class="loading-line" aria-hidden="true"></span>{/if}
            <div role="status" aria-live="polite">
              <strong class="font-price text-base text-base-content">
                {loading ? 'Loading products…' : error ? 'Catalog unavailable' : `${meta?.total_items.toLocaleString() || 0} products`}
              </strong>
              <p class="text-xs text-muted">{applied.q ? `Search: “${applied.q}”` : 'All listings'}</p>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <label class="flex items-center gap-2 text-xs text-muted">
                <span>Sort</span>
                <select class="select select-sm border-base-300 bg-base-100 text-xs text-base-content" aria-label="Sort products" bind:value={filters.sort} onchange={applyFilters}>
                  <option value="">Default</option>
                  <option value="price_asc">Price: low to high</option>
                  <option value="price_desc">Price: high to low</option>
                  <option value="id">Product ID</option>
                </select>
              </label>
              <label class="flex items-center gap-2 text-xs text-muted">
                <span>Show</span>
                <select class="select select-sm border-base-300 bg-base-100 text-xs text-base-content" aria-label="Products per page" bind:value={filters.limit} onchange={applyFilters}>
                  <option value="12">12</option>
                  <option value="24">24</option>
                  <option value="48">48</option>
                </select>
              </label>
            </div>
          </div>

          {#if error && !loading}
            <div class="state-panel border border-error/35 bg-error/10 p-8 text-center" role="alert">
              <h3 class="text-xl font-semibold">Could not load products</h3>
              <p class="mt-2 text-sm text-muted">{error}</p>
              <button type="button" class="btn btn-outline mt-5" onclick={() => void loadProducts(page)}>Try again</button>
            </div>
          {:else if loading}
            <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading products">
              {#each Array(6) as _}
                <div class="overflow-hidden border border-base-300 bg-base-200">
                  <div class="skeleton-surface h-48"></div>
                  <div class="space-y-3 p-5">
                    <div class="skeleton-surface h-4 w-1/3 rounded"></div>
                    <div class="skeleton-surface h-6 w-full rounded"></div>
                    <div class="skeleton-surface h-5 w-2/3 rounded"></div>
                    <div class="skeleton-surface mt-7 h-9 w-full rounded"></div>
                  </div>
                </div>
              {/each}
            </div>
          {:else if items.length === 0}
            <div class="state-panel border border-dashed border-base-300 bg-base-200/50 p-12 text-center">
              <svg class="mx-auto size-8 text-muted" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="10.8" cy="10.8" r="6.3" stroke="currentColor" stroke-width="1.6"/><path d="m15.5 15.5 5 5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>
              <h3 class="mt-3 text-xl font-semibold">No matching products</h3>
              <p class="mt-2 text-sm text-muted">Try a broader search or clear some filters.</p>
              <button type="button" class="btn btn-outline mt-5" onclick={clearFilters}>Clear all filters</button>
            </div>
          {:else}
            <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {#each items as product, index (product.id)}
                <div class="card-enter" style={`--card-index: ${Math.min(index, 8)}`}>
                  <ProductCard {product} onDetails={openDetail} />
                </div>
              {/each}
            </div>
          {/if}

          {#if !loading && !error && meta && meta.total_pages > 1}
            <nav class="mt-8 flex items-center justify-center gap-3" aria-label="Product pages">
              <button type="button" class="btn btn-outline btn-sm" disabled={page <= 1} onclick={() => changePage(page - 1)}>← Previous</button>
              <span class="text-sm text-muted" aria-live="polite">Page {page} of {meta.total_pages}</span>
              <button type="button" class="btn btn-outline btn-sm" disabled={page >= meta.total_pages} onclick={() => changePage(page + 1)}>Next →</button>
            </nav>
          {/if}
        </div>
      </div>
    </section>
  </main>

  <footer class="border-t border-base-300">
    <div class="mx-auto flex max-w-[1500px] flex-col gap-3 px-4 py-7 text-xs text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-10">
      <div class="flex items-center gap-2">
        <span class="brand-mark grid size-5 place-items-center border border-primary text-[8px] font-bold text-primary" aria-hidden="true">TG</span>
        <strong class="text-sm text-base-content">techguide</strong>
        <span class="ml-2 hidden sm:inline">Parts catalog for Egypt.</span>
      </div>
      <span>© {new Date().getFullYear()} Tech Guide</span>
    </div>
  </footer>
</div>

<dialog bind:this={detailDialog} class="modal" aria-labelledby="detail-title" oncancel={(event) => { event.preventDefault(); closeDetail(); }} onclose={() => { detailAbort?.abort(); detail = null; }}>
  <div class="modal-box detail-modal max-w-2xl border border-base-300 bg-base-200 p-0">
    <div class="flex items-center justify-between border-b border-base-300 px-5 py-4">
      <h2 id="detail-title" class="text-xl font-semibold">Product details</h2>
      <button type="button" class="btn btn-ghost btn-sm btn-circle" aria-label="Close product details" onclick={closeDetail}>✕</button>
    </div>
    {#if detailLoading}
      <div class="p-8 text-center text-muted" role="status">Loading product details…</div>
    {:else if detailError}
      <div class="p-8 text-center text-error" role="alert">{detailError}</div>
    {:else if detail}
      <div class="space-y-5 p-5 sm:p-6">
        <div class="product-image-well flex h-52 items-center justify-center rounded-xl p-5">
          {#if safeExternalURL(detail.image_url)}
            <img src={safeExternalURL(detail.image_url) || ''} alt="" class="max-h-full max-w-full object-contain" referrerpolicy="no-referrer" />
          {:else}
            <svg class="fallback-mark" width="70" height="70" viewBox="0 0 70 70" fill="none" aria-hidden="true"><rect x="15" y="15" width="40" height="40" rx="5" stroke="currentColor" stroke-width="2"/><rect x="27" y="27" width="16" height="16" rx="2" stroke="currentColor" stroke-width="2"/></svg>
          {/if}
        </div>
        <div>
          <p class="text-xs font-semibold text-muted">{detail.provider?.name}</p>
          <h3 class="mt-1 text-2xl font-semibold leading-snug">{detail.name}</h3>
          <p class="mt-2 text-sm text-muted">{[detail.category?.slug, detail.brand?.name].filter(Boolean).join(' · ')}</p>
        </div>
        <div class="flex flex-wrap items-center justify-between gap-3 border-t border-base-300 pt-4">
          <div>
            <p class="text-xs uppercase tracking-wider text-muted">Listed price</p>
            <strong class="font-price text-2xl">{formatPrice(detail.price, detail.currency)}</strong>
            <p class="mt-1 text-xs text-muted">{detail.in_stock === true ? 'In stock' : detail.in_stock === false ? 'Out of stock' : 'Stock unknown'}</p>
          </div>
          {#if safeExternalURL(detail.canonical_product_url)}
            <a class="btn btn-primary" href={safeExternalURL(detail.canonical_product_url) || '#'} target="_blank" rel="noopener noreferrer">View at store <span aria-hidden="true">↗</span></a>
          {/if}
        </div>
      </div>
    {/if}
  </div>
  <div class="modal-backdrop"><button type="button" aria-label="Close product details" onclick={closeDetail}>close</button></div>
</dialog>
