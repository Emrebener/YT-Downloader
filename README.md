# YouTube MP3 Downloader

A simple, self-hosted website for downloading YouTube videos and playlists as
audio (MP3/M4A/Opus/FLAC/WAV) or video (MP4/WebM/MKV) files. Backed by
[yt-dlp](https://github.com/yt-dlp/yt-dlp). Intended for single-user use on a
home LAN — no authentication.

## Run with Docker

```bash
docker compose up -d --build
```

Open `http://<host>:8000`. Paste a video or playlist URL, pick format/quality,
and click Download.

- A **video URL** downloads directly.
- A **playlist URL** lists each video with its own Download button, plus
  "Download all (ZIP)" and "Download all (one by one)".

Downloaded files are named `<channel> - <title>.<ext>`.

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
