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
│  │   • GET  /api/download     → file   │ │
│  │   • GET  /api/download-zip → zip    │ │
│  ├─────────────────────────────────────┤ │
│  │  yt-dlp (Python lib) + ffmpeg (bin) │ │
│  └─────────────────────────────────────┘ │
│  /tmp/ytmp3-work  ← per-request temp dir  │
└─────────────────────────────────────────┘
```

- **Backend:** Python 3.12 + FastAPI + uvicorn. `yt-dlp` used as a library;
  `ffmpeg` installed in the image for audio extraction and muxing.
- **Frontend:** static `index.html` + `app.js` + `style.css`, no build step,
  served by FastAPI.
- **No database, no auth, no job queue.** Each request is self-contained.
- **Processing model:** synchronous. The browser request blocks until the file
  is ready, then the download begins; the UI shows a spinner meanwhile.
- **Work dir:** each download request gets its own temp directory under `/tmp`.
  yt-dlp writes there; FastAPI streams the result back; the temp dir is deleted
  via a `BackgroundTask` after the response finishes (including on error).
- uvicorn runs with request timeouts disabled so long synchronous downloads are
  not cut off. Safe — LAN only, no reverse proxy.

## Components

### Units

| Unit | Responsibility | Depends on |
|------|----------------|------------|
| `app.py` | FastAPI app, routes, static file serving | `downloader`, `ytdl_options` |
| `downloader.py` | Wraps yt-dlp: inspect URL, download to temp dir, build zip | `yt-dlp`, `ytdl_options` |
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

The `Content-Disposition: attachment; filename="..."` header carries the same
name so the browser save dialog pre-fills it.

## API

All endpoints synchronous.

### `POST /api/inspect`
- Body: `{ "url": "..." }`.
- Runs `extract_info(url, download=False)` with `extract_flat='in_playlist'` so
  playlists list quickly without resolving every entry.
- Returns one of:
  - `{ "type": "video", "title", "channel", "duration", "thumbnail" }`
  - `{ "type": "playlist", "title", "count", "entries": [ { "id", "url",
    "title", "channel", "duration", "thumbnail" }, ... ] }`
- Playlist detected via the yt-dlp `_type == 'playlist'` field.

### `GET /api/download`
- Query params: `url`, `mode` (`audio`|`video`), `format`, `quality`,
  `thumbnail` (`0`|`1`), `metadata` (`0`|`1`).
- Creates a per-request temp dir, builds `ydl_opts` via `ytdl_options`, runs
  yt-dlp, locates the produced file by globbing the temp dir.
- Returns `FileResponse` with `Content-Disposition: attachment`. A
  `BackgroundTask` removes the temp dir afterward.
- A GET so the frontend can trigger a download by plain navigation.

### `GET /api/download-zip`
- Query params: the playlist `url` plus the same option params as
  `/api/download`.
- Processes every playlist entry into one temp dir, bundles them into
  `<playlist title>.zip`, streams the zip. Temp dir cleaned up afterward.

## Frontend Flow

1. User sets options and pastes a URL, clicks Download.
2. Frontend calls `POST /api/inspect`.
3. If `type == "video"`: immediately trigger `GET /api/download` with the
   current options (spinner until the save dialog appears).
4. If `type == "playlist"`: render the results list.
   - Per-track Download button → `GET /api/download` for that video URL.
   - "Download all (ZIP)" → `GET /api/download-zip`.
   - "Download all (one by one)" → iterate entries client-side, firing
     `GET /api/download` for each sequentially (each waits for the previous to
     finish).

## Error Handling

- yt-dlp errors — private / age-restricted / geo-blocked videos, unsupported
  URLs, network failures — are caught and returned as a 4xx JSON
  `{ "error": "..." }`. The frontend shows the message inline near the input,
  or on the affected playlist row.
- Temp directories are always cleaned up, including on error.
- In "one by one" mode, a failing track shows an error on its row and the batch
  continues with the next track.

## Docker Packaging

- **Base image:** `python:3.12-slim`. `ffmpeg` installed via apt.
- **Dependencies:** `fastapi`, `uvicorn`, `yt-dlp` in `requirements.txt`
  (yt-dlp pinned to a known-good version).
- **`docker-compose.yml`:** one service, port mapping `8000:8000`,
  `restart: unless-stopped`. Run with `docker compose up -d`.
- No volumes — files stream to the browser; temp dirs live inside the container.
- README notes that yt-dlp must be bumped and the image rebuilt periodically,
  since YouTube changes break older yt-dlp versions.

## Testing

- `ytdl_options.py`: unit tests — given UI option combinations, assert the
  produced `ydl_opts` dict (format string, postprocessor list, outtmpl).
- `downloader.py`: an integration test against a short, stable public YouTube
  video — inspect returns expected metadata; download produces a correctly
  named MP3. Marked so it can be skipped offline.
- API: a test that `/api/inspect` distinguishes video vs playlist URLs, and
  that a bad URL yields a 4xx JSON error.
- Manual smoke test: run the container, download one video and one playlist
  (both ZIP and one-by-one) in both Audio and Video modes.
