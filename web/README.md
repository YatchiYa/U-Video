# UGC Studio — web app

The friendly web interface of UGC Studio (local AI video production). Next.js (App Router) + TypeScript + Tailwind.
French by default, English with one click (the choice is remembered in the browser).

The browser only talks to this Next server: every `/api/...` request is proxied server-side to the UGC Studio API
(`UGC_API_URL`), so there is no CORS and videos stream with seeking (HTTP Range requests pass through).

## Development

Start the API first (it includes an in-memory worker), from the repository root:

```bash
.venv/bin/ugc serve --port 8000
```

Then the web app:

```bash
cd web
npm install
UGC_API_URL=http://127.0.0.1:8000 npm run dev      # http://localhost:3000
```

`UGC_API_URL` defaults to `http://127.0.0.1:8000`.

Checks: `npm run lint`, `npm run typecheck`, `npm run build`.

## Production (without Docker)

Next.js resolves the `/api` rewrite **when building**, so set `UGC_API_URL` for the build:

```bash
cd web
npm ci
UGC_API_URL=http://127.0.0.1:8000 npm run build
npm start          # standalone server on port 3000 (PORT=4000 npm start to change)
```

`npm start` copies `public/` and `.next/static/` next to the standalone `server.js` and runs it.

## Docker

```bash
docker build -t ugc-studio-web web/
docker run -p 3000:3000 -e UGC_API_URL=http://api:8000 ugc-studio-web
```

The image is built with a placeholder API address; `docker-entrypoint.sh` writes the runtime `UGC_API_URL` into
the built server files at each start, so one image works with any API address. With docker compose, put it next to
the `api` service and set `UGC_API_URL=http://api:8000`.

## Layout

```
app/                      pages (App Router)
  page.tsx                home: projects, health, "Create a video"
  create/page.tsx         step-by-step creation wizard
  projects/[id]/page.tsx  project: storyboard, render & watch, fix a moment, voice, timeline, settings
  jobs/page.tsx           activity (all jobs)
components/               UI kit (ui.tsx), JobPanel (live job progress), header, health bar
components/project/       the project tabs + video player
lib/api.ts                typed API client (types match docs/openapi.json + api.py/service.py)
lib/i18n.tsx              fr/en dictionary + provider
lib/hooks.ts              data loading, job following (SSE with polling fallback)
```

Long operations (render, mix, export, website analysis, creation) are jobs: the app follows them live with
Server-Sent Events (`/api/jobs/{id}/events`), falls back to polling, and reconnects to running jobs when you come
back to a project.
