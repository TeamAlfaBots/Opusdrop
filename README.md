# OpusDrop

**Upload. Share. That's It.** OpusDrop is a no-account public file host for images, video, and text. It issues permanent direct, preview, and download links and stores both metadata and file bytes in Turso/libSQL BLOBs.

## Architecture

One Render Web Service runs one Uvicorn/FastAPI process. The production build statically exports the Next.js App Router UI; FastAPI serves that export, all API routes, direct files, preview route shells, and downloads on one origin. No local disk is used for durable uploads.

```
Browser ── one HTTPS origin ── FastAPI/Uvicorn
                               ├── /api/* and /file/*
                               ├── Next.js static export
                               └── Turso (metadata + BLOB bytes)
```

## Features

- Multi-file drag/drop with progress, 4 MB per-file default limit on Vercel (configurable with `MAX_FILE_SIZE`)
- JPG/JPEG, PNG, GIF, WEBP, AVIF, MP4, WEBM, MOV, TXT, MD, JSON, CSV, LOG
- Extension, declared MIME, and magic/signature checks; active web content is rejected
- Cryptographic 144-bit IDs and 256-bit deletion tokens
- Raw tokens are returned once; only SHA-256 token hashes are stored
- Image/video/text/JSON/CSV previews; byte Range responses for seeking
- Bounded 1 MB upload reads, upload concurrency semaphore, request-size and in-memory rate limits
- Parameterized SQL, secure headers, narrow CORS, structured errors
- No accounts, expiry jobs, MongoDB, object storage, or persistent Render filesystem

## Structure

- `frontend/` — Next.js, React, TypeScript, Tailwind, Motion, Lucide
- `backend/app/` — FastAPI configuration, DB, validation, routes, security
- `tests/` — workflow, validation, range, deletion, and limit tests
- `scripts/start.sh` — Render-compatible process entrypoint
- `render.yaml` — single-service Blueprint

## Local development

Prerequisites: Python 3.12+, Node 22+, npm.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt pytest httpx
cp .env.example .env
# For local-only development set TURSO_DATABASE_URL=file:local.db
npm --prefix frontend install
npm --prefix frontend run build
PORT=8000 bash scripts/start.sh
```

Open `http://localhost:8000`. For frontend hot reload, run `npm --prefix frontend run dev`; API requests should target port 8000 (or add a local Next rewrite).

## Turso setup

```bash
turso auth signup
turso db create opusdrop
turso db show opusdrop --url
turso db tokens create opusdrop
```

Put the URL and token in `.env`. On startup, OpusDrop creates `files` and its index idempotently. The table contains ID, original/stored names, server-selected MIME, size, BLOB, deletion-token hash, and timestamps. All values are bound parameters.

### Capacity warning

The configured limit is an **OpusDrop application ceiling**, not a promise that a selected Turso plan, client protocol, transaction, or quota accepts a statement/BLOB of that size. Turso plan quotas change; check the official pricing and limits pages immediately before launch. As of November 2026, published pricing reports a Free allowance around 5 GB total storage, 500M rows read/month, 10M rows written/month, and 3 GB sync transfer, but those aggregate figures do not establish a per-statement/BLOB limit. Perform a staging upload at the full limit against the exact plan/region/client. OpusDrop converts quota/size/full errors to HTTP 507 and connection/timeouts to 503.

Large public BLOB delivery can consume database transfer and Render memory quickly. Each request currently materializes one BLOB because libSQL query results return whole values; set conservative Render concurrency and `MAX_CONCURRENT_UPLOADS`. For serious scale, Turso-only BLOB storage is materially less efficient than object storage, but this implementation intentionally follows the requirement.

## Environment

See `.env.example`. `PUBLIC_BASE_URL` documents the canonical deployment URL; generated links use trusted proxy headers on the active one-origin request. Set `ALLOWED_ORIGINS` to the exact production origin. Never commit `.env`.

## API

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/upload` | multipart field `file`; returns links and one-time token |
| GET | `/api/files/{id}` | metadata |
| GET | `/api/files/{id}/preview` | metadata plus bounded text/JSON/CSV preview |
| GET | `/api/files/{id}/download` | attachment response |
| DELETE | `/api/files/{id}` | requires `X-Deletion-Token` |
| GET | `/api/health` | health check |
| GET | `/file/{id}` | inline direct bytes, Range-aware |
| GET | `/preview/{id}` | UI preview |
| GET | `/download/{id}` | attachment alias |

Errors use `{ "error": { "code": "...", "message": "..." } }`. Interactive OpenAPI docs are at `/api/docs`.

## Test

```bash
pip install -r backend/requirements.txt pytest httpx
pytest -q
```

Tests cover guest text/image/video uploads, signatures, unsupported content, direct/preview/download routes, Range requests, correct/incorrect deletion tokens, oversize input, health, and missing files. Turso quota and restart persistence should additionally run as deployment smoke tests with a dedicated staging database because they require real service credentials.

## Deploy to Vercel

Vercel serves the static Next.js export from its CDN and runs FastAPI as one Python serverless function (`api/index.py`). Routing is in `vercel.json`.

1. Create a Turso database (`turso db create opusdrop`, `turso db show opusdrop --url`, `turso db tokens create opusdrop`).
2. Push this repo to GitHub, then **Add New > Project** in Vercel and import it. Leave Root Directory as the repo root; `vercel.json` sets the build.
3. Add environment variables: `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `APP_ENV=production`, `ALLOWED_ORIGINS=https://<your-domain>` (see `.env.example`). Leave `PUBLIC_BASE_URL` empty unless you use a canonical custom domain.
4. Deploy, then check `/api/health`, upload a file, open its preview, download it, and delete it with the token.

**Vercel limits that shape this app**

- Function request and response bodies are capped at about 4.5 MB, so the default `MAX_FILE_SIZE` is 4 MiB (`NEXT_PUBLIC_MAX_FILE_MB=4` in the UI). A 25 MB limit needs a different upload path (for example direct-to-storage uploads) and is not possible through the function.
- The filesystem is read-only/ephemeral, so `TURSO_DATABASE_URL` must be a `libsql://` URL. A `file:` URL is refused on Vercel.
- The rate limiter is in-memory and per function instance, so it is best-effort only. Use Vercel Firewall rate limiting for real abuse protection.
- Files are cached for up to 1 hour (`s-maxage=3600`), so a deleted file can keep being served from the CDN cache for up to an hour.

The Turso client is a small pure-Python Hrana-over-HTTP client (`backend/app/database.py`), so no native wheel is needed on Vercel.

## Deploy to one Render service

1. Push this repository to GitHub/GitLab.
2. In Render, create a Blueprint from `render.yaml` (one `web` service only).
3. Add secret values for `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN`.
4. Set `PUBLIC_BASE_URL` and `ALLOWED_ORIGINS` to the final Render custom/service domain, e.g. `https://opusdrop.onrender.com`.
5. Deploy. Build installs Python/Node dependencies and exports Next; start binds Uvicorn to Render's `$PORT` on `0.0.0.0`.
6. Confirm `/api/health`, then upload, preview, Range-fetch, download, restart the service, fetch again, and delete with the token.

## Security and operations

Deletion tokens cannot be recovered. Do not log multipart bodies, authorization tokens, or database URLs. Place Render's CDN/WAF or another trusted edge in front for distributed abuse protection: the built-in limiter is deliberately process-local and resets on restart. Public permanent hosting also needs an abuse-report and takedown process, malware moderation, backups, quota alerts, and legal policy before production launch.

If uploads return 415, verify extension, MIME, and signature agree. A 507 indicates quota/statement/storage limits. A 503 indicates database connectivity. A 416 means an invalid byte range. If the UI is missing, rerun the frontend build and confirm `frontend/out/index.html` exists.
