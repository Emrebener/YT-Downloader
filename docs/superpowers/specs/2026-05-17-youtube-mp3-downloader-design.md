# YouTube MP3 Downloader — Design

**Date:** 2026-05-17
**Status:** Approved

## Purpose

A simple, self-hosted website for downloading YouTube videos as MP3s (or other
audio/video formats) without ad-laden third-party sites. Backed by yt-dlp.
Single user, runs on the home LAN.

## Scope

- One-page web UI: options bar, large URL input, Download button, results area.
- Video URLs download directly; playlist URLs list each video with per-track
  download buttons plus "Download all" controls.
- Audio and video downloading, with format/quality options exposed from yt-dlp.
- Packaged as a single Docker container, started with `docker compose up -d`.

Out of scope: authentication, user accounts, persistent download library,
background job queue, live progress bars, multi-user support.

## Architecture

Single FastAPI application, one Docker container.

```
┌─────────────────────────────────────────┐
│  Docker container                         │
│  ┌─────────────────────────────────────┐ │
│  │  FastAPI (uvicorn)                   │ │
│  │   • serves static frontend (1 page) │ │
│  │   • POST /api/inspect      → metadata│ │
│  │   • POST /api/download     → token  │ │
│  │   • GET  /api/file/{token} → file   │ │
│  │   • GET  /api/download-zip → zip    │ │
│  ├─────────────────────────────────────┤ │
│  │  yt-dlp (Python lib) + ffmpeg (bin) │ │
│  └─────────────────────────────────────┘ │
│  $WORK_DIR  ← per-request temp subdirs    │
└─────────────────────────────────────────┘
```

- **Backend:** Python 3.12 + FastAPI + uvicorn. `yt-dlp` used as a library;
  `ffmpeg` installed in the image for audio extraction and muxing.
- **Frontend:** static `index.html` + `app.js` + `style.css`, no build step,
  served by FastAPI.
- **No database, no auth, no job queue.** State is limited to a small in-memory
  token store (see Download Mechanism); it does not survive a restart, which is
  acceptable.
- **Processing model:** synchronous. yt-dlp does its work within the request;
  the UI shows a spinner meanwhile. Single-file downloads use a two-step
  token handshake; playlist ZIPs use a streaming response (see Download
  Mechanism).
- **Event loop:** all route handlers that invoke yt-dlp are declared as plain
  `def` (not `async def`), so FastAPI runs them in its worker threadpool. A
  multi-minute download therefore never blocks the event loop, and `/api/inspect`
  stays responsive during a download.
- **Work dir:** each download request gets its own temp subdirectory under a
  configurable `WORK_DIR` (env var, default `/app/work` — on the container's
  disk-backed writable layer, *not* `/tmp`, which may be size-limited or
  RAM-backed). yt-dlp writes there; the temp subdir is removed via a
  `BackgroundTask` once its file has been served, and a startup sweep plus a
  periodic sweep delete orphaned subdirs and expired tokens.
- uvicorn runs with request timeouts disabled so long synchronous downloads are
  not cut off. Safe — LAN only, no reverse proxy.

## Components

### Units

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| `app.py` | FastAPI app, routes, static file serving, token store | `downloader`, `ytdl_options` |
| `downloader.py` | Wraps yt-dlp: inspect URL, download to temp dir, stream zip | `yt-dlp`, `ytdl_options` |
| `ytdl_options.py` | Translates UI options → yt-dlp `ydl_opts` dict | — |
| `static/index.html` | Page markup | — |
| `static/app.js` | UI logic: inspect, render results, trigger downloads | `/api/*` |
| `static/style.css` | Styling | — |

Each unit is independently understandable: `ytdl_options` is a pure function
(options in, dict out), `downloader` is the only place that touches yt-dlp, and
`app.py` only does HTTP plumbing.

## UI Layout

Single page, top to bottom:

1. **Options bar:** Audio/Video toggle, Format dropdown, Quality dropdown,
   "Embed thumbnail" checkbox, "Embed metadata" checkbox.
2. **Input row:** large text input (paste URL) + Download button.
3. **Results area:**
   - Single video: no list rendered; the browser save dialog opens directly
     after a brief spinner.
   - Playlist: header (title + video count) with "Download all (ZIP)" and
     "Download all (one by one)" buttons, then a list of rows — each row shows
     thumbnail, index, title, channel, duration, and a per-track Download
     button.

## Format & Quality Options

### Audio mode
- **Format:** MP3, M4A (AAC), Opus, FLAC, WAV.
- **Quality:** 320 / 256 / 192 / 128 kbps for lossy formats; disabled
  (lossless) for FLAC and WAV.
- yt-dlp: `format: 'bestaudio/best'` + `FFmpegExtractAudio` postprocessor
  (`preferredcodec`, `preferredquality`).

### Video mode
- **Container:** MP4, WebM, MKV.
- **Resolution cap:** Best / 2160p / 1440p / 1080p / 720p / 480p / 360p.
- yt-dlp: `format: 'bestvideo[height<=N]+bestaudio/best[height<=N]'` (no cap
  when "Best"), `merge_output_format` set to the chosen container.

### Both modes — checkboxes
- **Embed thumbnail:** `EmbedThumbnail` postprocessor (cover art).
- **Embed metadata:** `FFmpegMetadata` postprocessor (title, artist, chapters).

### Defaults
Audio / MP3 / 320 kbps / both checkboxes on.

## File Naming

Downloaded files use the yt-dlp output template:

```
%(channel,uploader)s - %(title)s.%(ext)s
```

`channel` is preferred; `uploader` is the fallback when `channel` is missing.
Example: channel "Eminem" + video "Mockingbird" → `Eminem - Mockingbird.mp3`.
yt-dlp's built-in filename sanitization handles filesystem-unsafe characters.

The `Content-Disposition: attachment` header carries the same name so the
browser save dialog pre-fills it. Because titles can contain non-ASCII
characters (CJK, emoji), the header includes both a plain ASCII-fallback
`filename="..."` and an RFC 5987 `filename*=UTF-8''...` parameter with the
percent-encoded full name. Starlette's `FileResponse(filename=...)` already
emits both; `/api/file/{token}` relies on that, and the streaming ZIP response
sets the header explicitly in the same form.

## Download Mechanism

A browser-native navigation download gives JavaScript no success/failure
signal, so it cannot drive the inline error UI or sequence the "one by one"
flow. Single-file downloads therefore use a **two-step token handshake**:

1. **`POST /api/download`** does the yt-dlp work synchronously. On success it
   registers the produced file in an in-memory token store
   (`token → {path, filename, content_type, created_at}`) and returns
   `{ "token": "..." }`. On failure it returns a 4xx JSON `{ "error": "..." }`.
   Because this is a normal `fetch()` the frontend can `await` it, read the
   error, and — for "one by one" — wait for it before starting the next track.
2. **`GET /api/file/{token}`** streams the already-produced file with a
   `FileResponse`, so bytes go straight to disk with no copy in browser memory.
   The frontend triggers it by navigation (hidden anchor). A `BackgroundTask`
   then deletes the temp subdir and removes the token. Tokens expire after a
   TTL (default 30 min) and are swept periodically in case the file is never
   fetched.

This keeps the model synchronous and queue-free while making errors and
sequencing fully observable in JS and avoiding multi-GB blobs in RAM.

## API

### `POST /api/inspect`
- Body: `{ "url": "..." }`.
- Runs `extract_info(url, download=False)` with `extract_flat='in_playlist'` so
  playlists list quickly without resolving every entry.
- Returns one of:
  - `{ "type": "video", "title", "channel", "duration", "thumbnail" }`
  - `{ "type": "playlist", "title", "count", "entries": [ { "id", "url",
    "title", "channel", "duration", "thumbnail" }, ... ] }`
- Playlist detected via the yt-dlp `_type == 'playlist'` field.

### `POST /api/download`
- Body: `url`, `mode` (`audio`|`video`), `format`, `quality`,
  `thumbnail` (bool), `metadata` (bool).
- Creates a per-request temp subdir, builds `ydl_opts` via `ytdl_options`, runs
  yt-dlp. The final file path comes from the **postprocessed info dict** —
  `ydl.prepare_filename(info)` reconciled with the postprocessors' final
  extension (yt-dlp records postprocessor output in `info['requested_downloads']`
  / `info['filepath']`). The temp subdir is *not* globbed, since
  `EmbedThumbnail`/`FFmpegMetadata` leave intermediate `.webp`/`.part`/pre-mux
  artifacts behind.
- Registers the file in the token store and returns `{ "token": "..." }`, or a
  4xx JSON `{ "error": "..." }` on failure (temp subdir cleaned up immediately).

### `GET /api/file/{token}`
- Streams the token's file as a `FileResponse` with `Content-Disposition:
  attachment`. A `BackgroundTask` removes the temp subdir and token afterward.
- Unknown/expired token → 404.

### `GET /api/download-zip`
- Query params: the playlist `url` plus the same option params as
  `POST /api/download`.
- Returns a `StreamingResponse` that processes one playlist entry at a time and
  appends each finished file to an **on-the-fly ZIP** (e.g. `zipstream-ng`), so
  bytes flow to the browser continuously from the first completed track —
  preventing browser-side connection timeouts on long playlists. A track that
  fails is skipped; its error is recorded and a `_errors.txt` summary is added
  to the archive. The temp subdir is cleaned up when the response finishes.
- This is a direct GET (navigation): inspect has already validated the URL, so
  start-of-request errors are unlikely; per-track errors are captured in-band.

## Frontend Flow

A single `downloadOne(url, options)` helper does the two-step handshake:
`await fetch('POST /api/download')` → on a 4xx, throw with the error message;
on success, navigate a hidden anchor to `GET /api/file/{token}`.

1. User sets options and pastes a URL, clicks Download.
2. Frontend calls `POST /api/inspect`.
3. If `type == "video"`: call `downloadOne` immediately (spinner during the
   POST; save dialog appears once the token resolves). A thrown error is shown
   inline near the input.
4. If `type == "playlist"`: render the results list.
   - Per-track Download button → `downloadOne` for that video URL; an error is
     shown on that row.
   - "Download all (ZIP)" → navigate to `GET /api/download-zip`.
   - "Download all (one by one)" → `for` loop over entries, `await downloadOne`
     for each. Awaiting the POST is a real completion signal, so tracks process
     strictly in sequence; a failing track shows its error and the loop
     continues.

## Error Handling

- yt-dlp errors — private / age-restricted / geo-blocked videos, unsupported
  URLs, network failures — are caught. `POST /api/inspect` and
  `POST /api/download` return them as a 4xx JSON `{ "error": "..." }`; the
  frontend (which `await`s these calls) shows the message inline near the input
  or on the affected playlist row.
- Temp directories are always cleaned up — on success via `BackgroundTask`,
  on error immediately in a `finally` block.
- In "one by one" mode, a failing track shows an error on its row and the loop
  continues with the next track.
- `GET /api/download-zip` has already begun streaming when a per-track failure
  occurs, so it cannot switch to a 4xx; instead it skips the track and records
  the failure in a `_errors.txt` file added to the archive.

## Limits & Constraints

- **URL handling:** any URL accepted by yt-dlp works (yt-dlp supports a generic
  extractor and ~1800 sites). The app does not restrict to youtube.com — the
  "YouTube" name reflects the primary use case, not a hard limit. URLs are
  passed to yt-dlp unmodified; no SSRF guard is added, which is acceptable for
  a single-user LAN deployment.
- **Playlist size:** a large playlist ZIP is processed entirely within one
  request. There is a practical ceiling (tens of tracks, or ~minutes of
  processing) beyond which it becomes unwieldy even with streaming. This is
  accepted; the README states it and suggests per-track downloads for very
  large playlists.
- **Disk:** `WORK_DIR` lives on the container's writable layer. A full video
  playlist can be several GB transiently. The README documents this and notes
  that `WORK_DIR` can be mounted to a host volume if container disk is tight.

## Docker Packaging

- **Base image:** `python:3.12-slim`. `ffmpeg` installed via apt.
- **Dependencies:** `fastapi`, `uvicorn`, `yt-dlp`, `zipstream-ng` in
  `requirements.txt` (yt-dlp pinned to a known-good version).
- **`docker-compose.yml`:** one service, port mapping `8000:8000`,
  `restart: unless-stopped`, `WORK_DIR` env (default `/app/work`). Run with
  `docker compose up -d`.
- No volumes required — temp subdirs live on the container's writable layer.
  A commented-out volume mount for `WORK_DIR` is included for users who want
  large playlist downloads on host disk.
- README notes that yt-dlp must be bumped and the image rebuilt periodically,
  since YouTube changes break older yt-dlp versions.

## Testing

- `ytdl_options.py`: unit tests — given UI option combinations, assert the
  produced `ydl_opts` dict (format string, postprocessor list, outtmpl).
- `downloader.py`: a network integration test that inspects a video URL and
  downloads it to a temp dir, asserting the file is named
  `<channel> - <title>.mp3` and the path is resolved from the info dict (not a
  glob). Marked with a `network` marker so it is skipped offline; it also
  treats a "video unavailable / removed" yt-dlp error as a skip rather than a
  failure, since no public video is guaranteed permanent. The URL is a module
  constant so it can be swapped easily.
- API: tests with `TestClient` that `/api/inspect` distinguishes video vs
  playlist URLs, that a bad URL yields a 4xx JSON `{ "error" }`, and that the
  `POST /api/download` → `GET /api/file/{token}` handshake returns the file
  with a correct `Content-Disposition` (including the `filename*` form for a
  non-ASCII title). Network-dependent assertions use the `network` marker.
- Manual smoke test: run the container, download one video and one playlist
  (both ZIP and one-by-one) in both Audio and Video modes.
