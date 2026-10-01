import assert from 'node:assert/strict';
import test from 'node:test';
import { catalogSearchParams, emptyFilters, fetchBrowseProducts, fetchCatalog, fetchSearchProducts, formatPrice, safeExternalURL } from './api.ts';

test('catalog search params include only selected filters', () => {
  const params = catalogSearchParams({
    ...emptyFilters,
    q: '  RTX  ',
    category: '5',
    stock: 'false',
    minPrice: '1000',
    sort: 'price_asc',
  }, 2);
  assert.equal(params.get('q'), 'RTX');
  assert.equal(params.get('category_ids'), '5');
  assert.equal(params.get('in_stock'), 'false');
  assert.equal(params.get('min_price'), '1000');
  assert.equal(params.get('sort'), 'price_asc');
  assert.equal(params.get('page'), '2');
  assert.equal(params.has('provider_ids'), false);
});

test('browse and search map their different API response envelopes', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    const search = String(url).includes('/products/search?');
    return new Response(JSON.stringify(search
      ? { success: true, data: [{ id: 7 }], meta: { page: 1, total_items: 1, total_pages: 1 } }
      : { success: true, data: { items: [{ id: 3 }], meta: { page: 1, total_items: 1, total_pages: 1 } } }
    ), { headers: { 'content-type': 'application/json' } });
  };
  try {
    const browse = await fetchBrowseProducts({ ...emptyFilters, q: 'Ryzen' }, 1);
    const search = await fetchSearchProducts({ ...emptyFilters, q: 'Ryzen', category: '7', stock: 'true' }, 1);
    const dispatchedSearch = await fetchCatalog({ ...emptyFilters, q: 'Ryzen' }, 1);
    assert.equal(browse.items[0].id, 3);
    assert.equal(search.items[0].id, 7);
    assert.equal(dispatchedSearch.items[0].id, 7);
    assert.match(calls[0], /\/api\/products\?/);
    assert.equal(new URL(calls[0], 'http://example.test').searchParams.has('q'), false);
    assert.match(calls[1], /\/api\/products\/search\?/);
    const searchParams = new URL(calls[1], 'http://example.test').searchParams;
    assert.equal(searchParams.get('q'), 'Ryzen');
    assert.equal(searchParams.get('category_ids'), '7');
    assert.equal(searchParams.get('in_stock'), 'true');
    assert.match(calls[2], /\/api\/products\/search\?/);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('search refuses a blank query without making a request', async () => {
  await assert.rejects(fetchSearchProducts(emptyFilters, 1), /Enter a product name/);
});

test('external URLs accept only HTTP and HTTPS', () => {
  assert.equal(safeExternalURL('javascript:alert(1)'), null);
  assert.equal(safeExternalURL('data:text/html,hello'), null);
  assert.equal(safeExternalURL('https://example.com/part'), 'https://example.com/part');
});

test('unknown and placeholder prices are never shown as zero EGP', () => {
  assert.equal(formatPrice(null), 'Price not found');
  assert.equal(formatPrice('0.00'), 'Price not found');
  assert.equal(formatPrice('199.00'), '199 EGP');
});
