# Tracer Watch web page

The page at https://ersul4ik.github.io/tracer-watch/. It reads `board.json`, which the bot writes to the `state` branch after every pass, and sends notes back to the bot as `watch.yml` workflow runs.

React + TypeScript + Vite + Tailwind CSS + shadcn/ui, charts with Recharts. The `pages` workflow builds and deploys it on every push to `main` that touches `web/`.

```sh
npm ci
npm run dev                      # against the live board.json
python -m bot --dry-run --board web/public/board.dev.json   # from the repo root: fresh local data
VITE_BOARD_URL=/tracer-watch/board.dev.json npm run dev     # against that file
npm run lint && npm run build
```
