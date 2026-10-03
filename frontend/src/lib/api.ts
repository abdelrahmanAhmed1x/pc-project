export type Facet = { id: number; name?: string; slug?: string };

export type Product = {
  id: number;
  name: string;
  price: string | null;
  last_seen_price: string | null;
  last_seen_at: string | null;
  price_status?: 'known' | 'not_found' | 'placeholder' | 'price_on_request' | 'stale';
  condition?: 'new' | 'used' | 'refurbished' | 'unknown';
  offer_count?: number;
  variant_count?: number;
  provider_count?: number;
  product_variant_id?: number;
  currency: string;
  in_stock: boolean | null;
  image_url: string | null;
  category: { id: number; slug: string };
  provider: { id: number; name: string };
  brand: { id: number; name: string } | null;
};

export type ProductDetail = Product & {
  canonical_product_url: string;
  offers: Offer[];
};

export type Offer = {
  id: number;
  provider: { id: number; name: string };
  product_variant_id: number;
  configuration: Record<string, string>;
  sku: string | null;
  raw_name: string | null;
  price: string | null;
  old_price: string | null;
  price_status: 'known' | 'not_found' | 'placeholder' | 'price_on_request';
  currency: string;
  in_stock: boolean | null;
  condition: string;
  warranty: string | null;
  url: string;
  image_url: string | null;
  last_seen_at: string;
  is_current: boolean;
};

export type PageMeta = {
  page: number;
  limit: number;
  total_items: number;
  total_pages: number;
};

export type CatalogFilters = {
  q: string;
  category: string;
  provider: string;
  brand: string;
  stock: string;
  minPrice: string;
  maxPrice: string;
  sort: string;
  limit: string;
};

export const emptyFilters: CatalogFilters = {
  q: '',
  category: '',
  provider: '',
  brand: '',
  stock: '',
  minPrice: '',
  maxPrice: '',
  sort: '',
  limit: '12',
};

const configuredBase = import.meta.env?.VITE_API_URL?.trim();
const baseURL = (configuredBase || '/api').replace(/\/+$/, '');

type Envelope<T> = {
  success: boolean;
  data?: T;
  meta?: PageMeta;
  error?: { message?: string };
};

async function request<T>(path: string, signal?: AbortSignal): Promise<Envelope<T>> {
  const response = await fetch(`${baseURL}${path}`, { signal });
  let payload: Envelope<T>;
  try {
    payload = await response.json() as Envelope<T>;
  } catch {
    throw new Error(`The catalog returned an invalid response (${response.status}).`);
  }
  if (!response.ok || !payload.success) {
    throw new Error(payload.error?.message || `Request failed (${response.status}).`);
  }
  return payload;
}

function filterParams(filters: CatalogFilters, page: number): URLSearchParams {
  const params = new URLSearchParams({ page: String(page), limit: filters.limit });
  const entries: [string, string][] = [
    ['category_ids', filters.category],
    ['provider_ids', filters.provider],
    ['brand_ids', filters.brand],
    ['in_stock', filters.stock],
    ['min_price', filters.minPrice],
    ['max_price', filters.maxPrice],
    ['sort', filters.sort],
  ];
  for (const [key, value] of entries) {
    if (value !== '') params.set(key, value);
  }
  return params;
}

export function catalogSearchParams(filters: CatalogFilters, page: number): URLSearchParams {
  const params = filterParams(filters, page);
  if (filters.q.trim()) params.set('q', filters.q.trim());
  return params;
}

function checkedPage(items: Product[] | undefined, meta: PageMeta | undefined) {
  if (!Array.isArray(items) || !meta || !Number.isInteger(meta.page)) {
    throw new Error('The catalog returned an unexpected response.');
  }
  return { items, meta };
}

export async function fetchBrowseProducts(filters: CatalogFilters, page: number, signal?: AbortSignal) {
  const result = await request<{ items: Product[]; meta: PageMeta }>(
    `/products?${filterParams(filters, page)}`,
    signal,
  );
  return checkedPage(result.data?.items, result.data?.meta);
}

export async function fetchSearchProducts(filters: CatalogFilters, page: number, signal?: AbortSignal) {
  const query = filters.q.trim();
  if (!query) throw new Error('Enter a product name or model to search.');
  const params = filterParams(filters, page);
  params.set('q', query);
  const result = await request<Product[]>(`/products/search?${params}`, signal);
  return checkedPage(result.data, result.meta);
}

export function fetchCatalog(filters: CatalogFilters, page: number, signal?: AbortSignal) {
  return filters.q.trim()
    ? fetchSearchProducts(filters, page, signal)
    : fetchBrowseProducts(filters, page, signal);
}

export async function fetchFacets(signal?: AbortSignal) {
  const [categories, providers, brands] = await Promise.all([
    request<Facet[]>('/products/categories', signal),
    request<Facet[]>('/products/providers', signal),
    request<Facet[]>('/products/brands', signal),
  ]);
  return {
    categories: categories.data || [],
    providers: providers.data || [],
    brands: brands.data || [],
  };
}

export async function fetchProduct(id: number, signal?: AbortSignal): Promise<ProductDetail> {
  const result = await request<ProductDetail>(`/products/${encodeURIComponent(id)}`, signal);
  if (!result.data || result.data.id !== id) throw new Error('Product details are unavailable.');
  return result.data;
}

export async function fetchHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const result = await request<{ status: string }>('/health', signal);
    return result.data?.status === 'ok';
  } catch {
    return false;
  }
}

export function safeExternalURL(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

export function formatPrice(value: string | null, currency = 'EGP'): string {
  if (value === null || value === '') return 'Price not found';
  const amount = Number(value);
  if (!Number.isFinite(amount) || amount <= 0) return 'Price not found';
  return `${new Intl.NumberFormat('en-EG', { maximumFractionDigits: 2 }).format(amount)} ${currency}`;
}
