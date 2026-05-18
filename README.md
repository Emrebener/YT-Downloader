# YouTube MP3 Downloader

A simple, self-hosted website for downloading YouTube videos and playlists as
audio (MP3/M4A/Opus/FLAC/WAV) or video (MP4/WebM/MKV) files. Backed by
[yt-dlp](https://github.com/yt-dlp/yt-dlp). Intended for single-user use on a
home LAN — no authentication.

## Run with Docker

```bash
docker compose up -d --build
```

Open `http://<host>:8800`. Paste a video or playlist URL, pick format/quality,
and click Download.

- A **video URL** downloads directly.
- A **playlist URL** lists each video with its own Download button, plus
  "Download all (ZIP)" and "Download all (one by one)".

Downloaded files are named `<channel> - <title>.<ext>`.

The host port is set in `docker-compose.yml` (`8800:8000`); change the first
number if 8800 is taken.

## YouTube sign-in (cookies)

YouTube blocks unauthenticated downloads with a "Sign in to confirm you're not
a bot" check — playlists trip this especially often. To download reliably, give
yt-dlp your YouTube cookies:

1. Install a cookies-export extension, e.g. **Get cookies.txt LOCALLY**
   (available for Chrome and Firefox).
2. Sign in to `youtube.com` in that browser.
3. With a YouTube tab open, use the extension to **export** cookies and save the
   file as **`cookies.txt`**.
4. Put `cookies.txt` in the **`cookies/`** folder next to `docker-compose.yml`.
5. Restart: `docker compose restart`.

The app shows a warning banner while no cookie file is present. If downloads
later start failing again with a sign-in error, the cookies have expired —
re-export and replace the file.

**Keep `cookies.txt` private** — it grants access to your YouTube account. It is
git-ignored so it is never committed.

## Options

- **Audio:** MP3, M4A, Opus, FLAC, WAV — bitrate 320/256/192/128 kbps (lossless
  formats ignore bitrate).
- **Video:** MP4, WebM, MKV — resolution cap from Best down to 360p.
- **Embed thumbnail** / **Embed metadata** toggles for both modes.

## Updating yt-dlp

YouTube changes frequently break older yt-dlp versions. To update, rebuild the
image:

```bash
docker compose up -d --build
```

`yt-dlp` is unpinned in `requirements.txt` so each build pulls the latest
release. For reproducible builds, pin it — after a successful build run
`docker compose exec ytdl pip show yt-dlp` and set `yt-dlp==<version>` in
`requirements.txt`.

## Limits

- Accepts any URL yt-dlp supports (~1800 sites), not just YouTube.
- Playlist ZIPs are processed within a single request. For very large
  playlists prefer per-track downloads.
- Temp files live under `WORK_DIR` (default `/app/work`) on the container's
  writable layer. A full video playlist can be several GB transiently; mount a
  host volume at `WORK_DIR` (see `docker-compose.yml`) if container disk is tight.

## Development

```bash
pip install -r requirements-dev.txt
pytest -m "not network"      # fast, offline
pytest                       # includes network integration tests
WORK_DIR=$(mktemp -d) uvicorn app.app:app --reload
```
