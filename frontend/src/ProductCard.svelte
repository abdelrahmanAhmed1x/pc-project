<script lang="ts">
  import { formatPrice, safeExternalURL, type Product } from './lib/api';

  let { product, onDetails }: { product: Product; onDetails: (id: number) => void } = $props();
  let imageFailed = $state(false);
  const imageURL = $derived(safeExternalURL(product.image_url));
</script>

<article class="card product-card h-full overflow-hidden border border-base-300 bg-base-200">
  <div class="product-image-well flex h-48 items-center justify-center overflow-hidden p-6 sm:h-52">
    {#if imageURL && !imageFailed}
      <img
        src={imageURL}
        alt=""
        loading="lazy"
        decoding="async"
        referrerpolicy="no-referrer"
        class="max-h-full max-w-full object-contain"
        onerror={() => { imageFailed = true; }}
      />
    {:else}
      <svg class="fallback-mark" width="70" height="70" viewBox="0 0 70 70" fill="none" aria-hidden="true">
        <rect x="15" y="15" width="40" height="40" rx="5" stroke="currentColor" stroke-width="2"/>
        <rect x="27" y="27" width="16" height="16" rx="2" stroke="currentColor" stroke-width="2"/>
        <path d="M23 8v7m12-7v7m12-7v7M23 55v7m12-7v7m12-7v7M8 23h7m-7 12h7m-7 12h7m40-24h7m-7 12h7m-7 12h7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
      </svg>
    {/if}
  </div>
  <div class="card-body flex flex-col gap-3 p-5">
    <div class="flex min-w-0 items-center justify-between gap-2">
      <span class="store-name truncate text-xs font-semibold text-muted">
        {product.provider_count && product.provider_count > 1
          ? `${product.provider_count} verified retailers`
          : product.provider?.name || 'Store listing'}
      </span>
      <span class:badge-success={product.in_stock === true} class:badge-warning={product.in_stock === false} class="badge badge-sm shrink-0">
        {product.in_stock === true ? 'In stock' : product.in_stock === false ? 'Out of stock' : 'Stock unknown'}
      </span>
    </div>
    <h3 class="line-clamp-3 min-h-12 text-[15px] leading-snug font-semibold text-base-content">{product.name || `Product #${product.id}`}</h3>
    <p class="min-h-5 truncate text-xs text-muted">
      {[product.category?.slug, product.brand?.name].filter(Boolean).join(' · ') || 'PC component'}
    </p>
    <div class="mt-auto flex items-end justify-between gap-3 border-t border-base-300 pt-4">
      <div>
        <span class="block text-[11px] font-medium uppercase tracking-wider text-muted">
          {product.price_status !== 'known' ? 'Price unavailable' : product.condition && product.condition !== 'new' ? `${product.condition} listed price` : product.in_stock === true ? 'Lowest in-stock price' : product.in_stock === false ? 'Listed price · out of stock' : 'Listed price · stock unconfirmed'}
        </span>
        <strong class="font-price text-xl leading-tight text-base-content">{formatPrice(product.price, product.currency)}</strong>
        {#if (product.offer_count || 0) > 1}<span class="block text-xs text-muted">{product.offer_count} offers to compare</span>{/if}
      </div>
      <button type="button" class="btn btn-outline btn-sm detail-link shrink-0" onclick={() => onDetails(product.id)} aria-label={`View details for ${product.name}`}>
        Details <span class="detail-arrow" aria-hidden="true">↗</span>
      </button>
    </div>
  </div>
</article>
