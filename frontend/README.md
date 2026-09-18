# Signals frontend

Vite + React + TypeScript, Leaflet choropleth, TanStack Query. Two screens: the block-group heat map
and the block drawer (signals, households, outreach brief).

```bash
npm install
echo "VITE_ORG_TOKEN=<must match backend SIGNALS_ORG_TOKEN>" > .env.local
npm run dev      # http://localhost:5173, expects the API on http://127.0.0.1:8000 (VITE_API_BASE to change)
npm run build    # tsc -b && vite build
```

See the root [README](../README.md) for the full pipeline and [`md/architecture.md`](../md/architecture.md) for design notes.
