# Frontend

Next.js 16 (App Router), Tailwind v4, shadcn/ui. Run it with `make dev` from the repo root (FastAPI on :8000, this
app on :3000). The browser calls the API directly at `NEXT_PUBLIC_API_URL` and sends the demo passcode, which you
enter once in the UI.

- `lib/types.ts` is generated from `docs/openapi.json` by `scripts/gen_frontend_types.py` (`make openapi`). Don't edit it.
- `lib/api.ts` is the typed client. Every page fetches through it.
- Branding lives only in `styles/theme.css`, `config/app.ts` and `components/brand/`. `scripts/check_branding.py`
  (part of `make test` and CI) fails on color literals, Tailwind palette classes or the codename anywhere else.

```
npm run dev     # dev server on :3000
npm run lint
npm run build
```
