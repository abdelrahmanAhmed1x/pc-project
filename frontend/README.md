# Tech buying assistant preview

This is a plain HTML, CSS, and JavaScript frontend for the backend APIs. The **Assistant chat** tab uses `POST /ai/chat` and displays the assistant's message, catalog-backed product cards, store links, and an optional estimated total. It sends the returned `session_id` on later turns.

The **Explore catalog** tab uses:

- `GET /products/search` for quick fuzzy product search.
- `GET /products` for browsing with category, provider, brand, price, stock, and sort filters, plus pagination.
- `GET /products/categories`, `/products/providers`, and `/products/brands` to populate the filter choices.
- `GET /products/{id}` to show product details and the canonical store URL.
- `GET /health` for the API response indicator in the header. This checks the HTTP process only.

Start the backend, then serve this directory with any static file server, for example:

```sh
cd frontend
python3 -m http.server 5173
```

Open <http://localhost:5173>. The page uses `http://localhost:8082` as its default API URL. Change it with **API settings** if your backend uses another address. If you configure `CORS_ALLOWED_ORIGINS` instead of using its development default, include the frontend origin.

The current session and visible chat are kept in browser session storage for this preview. ADK on the backend owns the actual conversation history. The browser cache does not replace it.
