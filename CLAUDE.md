# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Self-hosted FastAPI service that wraps `yt-dlp` + `ffmpeg` to download videos/playlists from YouTube (and ~1800 other sites) as audio or video files. A single static HTML/JS page is the only UI; everything else is a Python backend packaged in Docker. There is no database, no auth, and no multi-user concept — it is meant to run on `localhost`.

## Common commands

Development (host machine, no Docker):

```bash
pip install -r requirements-dev.txt
pytest -m "not network"                 # fast offline suite (default for dev loop)
pytest                                  # also runs tests marked @pytest.mark.network
pytest tests/test_downloader.py::test_name   # run one test
WORK_DIR=$(mktemp -d) uvicorn app.app:app --reload    # dev server
```

`WORK_DIR` **must** point somewhere writable when running outside Docker — the app's lifespan handler wipes and recreates it on startup, and `/app/work` (the default) won't exist on a host.

Production-ish (Docker, what end users run):

```bash
docker compose up -d --build       # build + start, exposed on :8800
docker compose logs -f             # tail logs
docker compose down                # stop
```

Rebuild (`--build`) is the way to pick up new `yt-dlp` releases — it is intentionally unpinned in `requirements.txt` because YouTube breaks old versions frequently.

## Architecture

Three Python modules in `app/`, with strict layering — keep it that way:

- **`app/ytdl_options.py`** — pure translation from UI choices (`DownloadOptions`) to a `ydl_opts` dict. No I/O, does not import `yt_dlp`. This is what unit tests exercise without network.
- **`app/downloader.py`** — the *only* module that touches `yt_dlp`. Exposes `inspect`, `download_one`, `build_playlist_zip`, and the `DownloadFailed` exception. All yt-dlp errors are caught here and re-raised as `DownloadFailed` with a `cookies_expired` flag and a user-friendly message (`_friendly` collapses YouTube's sign-in-wall error into a short hint).
- **`app/app.py`** — FastAPI routes, in-memory token store, temp-dir lifecycle. Catches `DownloadFailed` and turns it into a JSON error response that includes `cookies_expired` so the frontend can show its banner.

Routes (all under `/api/*`; `/` serves the static frontend, mounted last so API routes win):

- `GET /api/status` — `{cookies: bool}` driving the "missing cookies" banner.
- `POST /api/inspect` — metadata only; returns `{type: "video"|"playlist", ...}`.
- `POST /api/download` → returns `{token}`; `GET /api/file/{token}` then streams the file and deletes its temp dir in a `BackgroundTask`. Tokens live in a `dict` guarded by `_tokens_lock` and are swept every 5 min (`TOKEN_TTL=1800s`).
- `GET /api/download-zip` — streams a playlist as an on-the-fly ZIP via `zipstream-ng`; failed tracks are skipped and listed in `_errors.txt` inside the archive. If *every* track fails, raise instead of returning an empty zip.

### Things that look weird but are intentional

- **Download path resolution.** `downloader._resolve_path` reads `info["requested_downloads"][0]["filepath"]` from the post-processed dict instead of globbing `out_dir`. Postprocessors (`EmbedThumbnail`, `FFmpegMetadata`) leave `.webp`/`.part`/pre-mux files behind that a glob would pick up.
- **`cookie_file()` is called per request.** It reads `COOKIES_FILE` and re-checks `os.path.isfile` every time, so dropping a `cookies.txt` into the mounted `./cookies/` folder takes effect without a restart. When passing it through, reuse the single returned value — don't call it twice in one flow (TOCTOU).
- **`cookies_expired` propagation.** A `DownloadFailed` from a yt-dlp sign-in/bot/age wall sets `cookies_expired=True` *only when a cookies file was in use* — that's how the UI distinguishes "you need cookies" from "your cookies are stale". `build_playlist_zip` ORs this across all tracks.
- **`outtmpl = "%(channel,uploader)s - %(title)s.%(ext)s"`** — `channel` falls back to `uploader` (`yt-dlp` field-fallback syntax). Don't "simplify" to a single field.
- **`noplaylist: True`** in `build_ydl_opts` means a video-in-playlist URL downloads just that one video from `/api/download`; playlist handling is opt-in via `/api/download-zip` after `inspect` classifies the URL.
- **Lifespan wipes `WORK_DIR` on startup.** Leftovers from a crashed previous run are dropped. Tests must monkeypatch `app_module.WORK_DIR` *before* entering `TestClient` so the lifespan handler sees the temp path (see `tests/test_api.py`).

### Frontend

`app/static/{index.html,app.js,style.css}` — vanilla JS, no build step. It calls the JSON API, shows the cookies banner based on `/api/status` and the `cookies_expired` flag on error responses, and triggers downloads via `window.location` to the token URL (single) or the `/api/download-zip` URL (playlist ZIP).

## Testing notes

- Tests are split by module: `test_ytdl_options.py` (pure), `test_downloader.py` (mocks `YoutubeDL`), `test_api.py` (FastAPI `TestClient`, mocks `downloader.*`).
- Network-touching tests are marked `@pytest.mark.network` and skipped by `-m "not network"` in the inner-loop.
- `app/downloader.py` is the network boundary — when adding behavior, put the logic somewhere unit-testable (often `ytdl_options.py`) and keep `downloader.py` thin.
