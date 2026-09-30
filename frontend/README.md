# Tech Guide frontend

A Svelte 5, Tailwind CSS 4, and daisyUI 5 frontend for the PC parts catalog API.

## Run locally

```sh
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite. In development, requests to `/api` are proxied to the backend at `http://localhost:8082`. Start the backend before browsing products.

## Production

```sh
npm run check
npm run build
```

Serve `dist/` as static files. By default, the app calls `/api`; configure your reverse proxy to forward that path to the backend. Alternatively, set `VITE_API_URL` to the backend origin before building. If frontend and backend use different origins, allow the frontend origin in the backend's `CORS_ALLOWED_ORIGINS`.

The app uses `GET /products` for browsing without a `q` parameter. The search form requires text and sends `q` together with the selected category, provider, brand, stock, price, sort, and pagination filters to `GET /products/search`. The category/provider/brand endpoints populate filters; `GET /products/{id}` supplies details and the store URL; `GET /health` supplies connection status. The UI does not expose catalog ingestion controls.
