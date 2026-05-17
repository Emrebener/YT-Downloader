# YouTube MP3 Downloader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A self-hosted, single-page website that downloads YouTube videos/playlists as audio or video files via yt-dlp, packaged as one Docker container.

**Architecture:** A single FastAPI app serves a static one-page frontend and three API endpoints. Single-file downloads use a two-step token handshake (`POST /api/download` → `GET /api/file/{token}`); playlist ZIPs stream on the fly. yt-dlp runs inside plain `def` route handlers so FastAPI executes them in its threadpool and the event loop never blocks.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, yt-dlp, ffmpeg, zipstream-ng, vanilla HTML/CSS/JS, Docker.

---

## File Structure

```
Youtube-Mp3-Downloader/
├── app/
│   ├── __init__.py            # marks app/ as a package
│   ├── app.py                 # FastAPI app, routes, token store, cleanup sweep
│   ├── downloader.py          # yt-dlp wrapper: inspect, download_one, build_playlist_zip
│   ├── ytdl_options.py        # DownloadOptions dataclass + build_ydl_opts (pure function)
│   └── static/
│       ├── index.html         # page markup
│       ├── style.css          # dark theme styling
│       └── app.js             # UI logic
├── tests/
│   ├── __init__.py
│   ├── test_ytdl_options.py   # pure-function unit tests
│   ├── test_downloader.py     # network integration tests (marked `network`)
│   └── test_api.py            # API tests with TestClient + monkeypatched downloader
├── conftest.py                # empty — puts repo root on sys.path for pytest
├── pytest.ini                 # registers the `network` marker
├── requirements.txt           # runtime dependencies
├── requirements-dev.txt       # test dependencies
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
└── README.md
```

**Unit responsibilities:**
- `ytdl_options.py` — pure: UI option values in, a yt-dlp `ydl_opts` dict out. No I/O. Fully unit-testable.
- `downloader.py` — the *only* module that imports yt-dlp. Inspect a URL, download one file, build a streaming playlist ZIP. Raises `DownloadFailed` on any yt-dlp error.
- `app.py` — HTTP plumbing only: request parsing, the in-memory token store, temp-dir lifecycle, static file serving.
- `static/*` — the frontend; talks only to `/api/*`.

---

## Task 1: Project scaffolding

**Files:**
- Create: `app/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `conftest.py` (empty)
- Create: `pytest.ini`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.dockerignore`

- [ ] **Step 1: Create the empty package/marker files**

Create three empty files: `app/__init__.py`, `tests/__init__.py`, and `conftest.py`.
(`conftest.py` at the repo root, even empty, makes pytest add the root to `sys.path` so `import app` works.)

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
markers =
    network: tests that need internet access (deselect with -m "not network")
testpaths = tests
```

- [ ] **Step 3: Create `requirements.txt`**

```
fastapi>=0.115
uvicorn[standard]>=0.34
# yt-dlp is intentionally unpinned: YouTube changes break old versions.
# After the first successful Docker build, pin it (see README "Updating yt-dlp").
yt-dlp
zipstream-ng>=1.8
```

- [ ] **Step 4: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0
httpx>=0.27
```

- [ ] **Step 5: Create `.dockerignore`**

```
tests/
docs/
.superpowers/
.git/
__pycache__/
*.pyc
requirements-dev.txt
pytest.ini
conftest.py
README.md
```

- [ ] **Step 6: Install dependencies locally**

Run: `pip install -r requirements-dev.txt`
Expected: installs without error.

- [ ] **Step 7: Commit**

```bash
git add app/__init__.py tests/__init__.py conftest.py pytest.ini requirements.txt requirements-dev.txt .dockerignore
git commit -m "chore: project scaffolding and dependencies"
```

---

## Task 2: `ytdl_options.py` — option translation

**Files:**
- Create: `app/ytdl_options.py`
- Test: `tests/test_ytdl_options.py`

This is a pure function: a `DownloadOptions` dataclass plus `build_ydl_opts(options, out_dir)` returning the yt-dlp `ydl_opts` dict.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ytdl_options.py`:

```python
from app.ytdl_options import DownloadOptions, build_ydl_opts, OUTTMPL


def test_audio_mp3_defaults():
    opts = build_ydl_opts(DownloadOptions(), "/work/job1")
    assert opts["format"] == "bestaudio/best"
    assert opts["paths"] == {"home": "/work/job1"}
    assert opts["outtmpl"] == {"default": OUTTMPL}
    extract = opts["postprocessors"][0]
    assert extract["key"] == "FFmpegExtractAudio"
    assert extract["preferredcodec"] == "mp3"
    assert extract["preferredquality"] == "320"


def test_audio_with_thumbnail_and_metadata():
    opts = build_ydl_opts(DownloadOptions(), "/work/job1")
    keys = [pp["key"] for pp in opts["postprocessors"]]
    assert keys == ["FFmpegExtractAudio", "FFmpegMetadata", "EmbedThumbnail"]
    assert opts["writethumbnail"] is True


def test_audio_without_extras():
    options = DownloadOptions(embed_thumbnail=False, embed_metadata=False)
    opts = build_ydl_opts(options, "/work/job1")
    keys = [pp["key"] for pp in opts["postprocessors"]]
    assert keys == ["FFmpegExtractAudio"]
    assert "writethumbnail" not in opts


def test_audio_flac_has_no_quality():
    options = DownloadOptions(format="flac")
    opts = build_ydl_opts(options, "/work/job1")
    extract = opts["postprocessors"][0]
    assert extract["preferredcodec"] == "flac"
    assert "preferredquality" not in extract


def test_video_best():
    options = DownloadOptions(mode="video", format="mp4", quality="best")
    opts = build_ydl_opts(options, "/work/job1")
    assert opts["format"] == "bestvideo*+bestaudio/best"
    assert opts["merge_output_format"] == "mp4"


def test_video_resolution_cap():
    options = DownloadOptions(mode="video", format="mkv", quality="1080")
    opts = build_ydl_opts(options, "/work/job1")
    assert opts["format"] == "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    assert opts["merge_output_format"] == "mkv"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ytdl_options.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ytdl_options'`.

- [ ] **Step 3: Write `app/ytdl_options.py`**

```python
"""Translate UI download options into a yt-dlp ``ydl_opts`` dictionary.

Pure module: no I/O, no yt-dlp import. Easy to unit-test.
"""
from dataclasses import dataclass

#: yt-dlp output template — "<channel> - <title>.<ext>", uploader as fallback.
OUTTMPL = "%(channel,uploader)s - %(title)s.%(ext)s"

#: Audio formats whose quality is lossless (a bitrate is meaningless).
LOSSLESS = {"flac", "wav"}


@dataclass
class DownloadOptions:
    """User-chosen download settings.

    ``quality`` carries the audio bitrate (e.g. ``"320"``) in audio mode and the
    resolution cap (``"best"`` or ``"1080"`` etc.) in video mode.
    """

    mode: str = "audio"           # "audio" | "video"
    format: str = "mp3"           # audio: mp3/m4a/opus/flac/wav; video: mp4/webm/mkv
    quality: str = "320"          # audio: kbps; video: "best" | "2160".."360"
    embed_thumbnail: bool = True
    embed_metadata: bool = True


def build_ydl_opts(options: DownloadOptions, out_dir: str) -> dict:
    """Return a yt-dlp options dict for downloading a single item into ``out_dir``."""
    opts: dict = {
        "paths": {"home": out_dir},
        "outtmpl": {"default": OUTTMPL},
        "noplaylist": True,        # a video-in-playlist URL downloads just the video
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [],
    }
    if options.mode == "audio":
        _apply_audio(options, opts)
    else:
        _apply_video(options, opts)
    _apply_extras(options, opts)
    return opts


def _apply_audio(options: DownloadOptions, opts: dict) -> None:
    opts["format"] = "bestaudio/best"
    extract = {"key": "FFmpegExtractAudio", "preferredcodec": options.format}
    if options.format not in LOSSLESS:
        extract["preferredquality"] = options.quality
    opts["postprocessors"].append(extract)


def _apply_video(options: DownloadOptions, opts: dict) -> None:
    if options.quality == "best":
        opts["format"] = "bestvideo*+bestaudio/best"
    else:
        h = options.quality
        opts["format"] = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"
    opts["merge_output_format"] = options.format


def _apply_extras(options: DownloadOptions, opts: dict) -> None:
    """Append metadata/thumbnail postprocessors common to both modes."""
    if options.embed_metadata:
        opts["postprocessors"].append(
            {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True}
        )
    if options.embed_thumbnail:
        opts["writethumbnail"] = True
        opts["postprocessors"].append({"key": "EmbedThumbnail"})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_ytdl_options.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add app/ytdl_options.py tests/test_ytdl_options.py
git commit -m "feat: ydl_opts builder for audio/video options"
```

---

## Task 3: `downloader.inspect` — read URL metadata

**Files:**
- Create: `app/downloader.py`
- Test: `tests/test_downloader.py`

`inspect(url)` returns a video dict or a playlist dict. Network test marked `network`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_downloader.py`:

```python
import os

import pytest

from app import downloader
from app.ytdl_options import DownloadOptions

# Canonical yt-dlp test video. Module constant so it can be swapped if removed.
TEST_VIDEO = "https://www.youtube.com/watch?v=BaW_jenozKc"


def _skip_if_gone(exc: Exception):
    """Treat 'video removed/unavailable' as a skip, not a failure."""
    msg = str(exc).lower()
    if any(s in msg for s in ("unavailable", "removed", "private", "not available")):
        pytest.skip(f"test video no longer available: {exc}")
    raise exc


@pytest.mark.network
def test_inspect_video_returns_video_dict():
    try:
        info = downloader.inspect(TEST_VIDEO)
    except downloader.DownloadFailed as exc:
        _skip_if_gone(exc)
    assert info["type"] == "video"
    assert info["title"]
    assert "channel" in info


def test_inspect_bad_url_raises_download_failed():
    with pytest.raises(downloader.DownloadFailed):
        downloader.inspect("https://not-a-real-site.example/nope")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_downloader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.downloader'`.

- [ ] **Step 3: Write `app/downloader.py` (inspect portion)**

```python
"""The only module that touches yt-dlp: inspect URLs, download files, build ZIPs."""
import os
import shutil

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, sanitize_filename
from zipstream import ZipStream

from app.ytdl_options import DownloadOptions, build_ydl_opts

CHUNK = 64 * 1024


class DownloadFailed(Exception):
    """Raised when yt-dlp cannot inspect or download a URL."""


def _clean(message: str) -> str:
    """Strip yt-dlp's noisy 'ERROR:' prefix for display to the user."""
    return message.replace("ERROR:", "").strip()


def inspect(url: str) -> dict:
    """Return metadata for ``url`` without downloading.

    Result is either ``{"type": "video", ...}`` or ``{"type": "playlist", ...}``.
    """
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",   # list playlist entries without resolving each
        "skip_download": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
    except DownloadError as exc:
        raise DownloadFailed(_clean(str(exc)))

    if info.get("_type") == "playlist":
        entries = [_entry(e) for e in (info.get("entries") or []) if e]
        return {
            "type": "playlist",
            "title": info.get("title") or "Playlist",
            "count": len(entries),
            "entries": entries,
        }
    return {
        "type": "video",
        "title": info.get("title") or "video",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
    }


def _entry(e: dict) -> dict:
    """Normalise one flat playlist entry into the shape the frontend expects."""
    return {
        "id": e.get("id"),
        "url": e.get("url") or e.get("webpage_url") or e.get("id"),
        "title": e.get("title") or "Untitled",
        "channel": e.get("channel") or e.get("uploader") or "",
        "duration": e.get("duration"),
        "thumbnail": _thumb(e),
    }


def _thumb(e: dict):
    thumbs = e.get("thumbnails") or []
    if thumbs:
        return thumbs[-1].get("url")
    if e.get("id"):
        return f"https://i.ytimg.com/vi/{e['id']}/default.jpg"
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_downloader.py -v`
Expected: PASS (`test_inspect_bad_url...` passes; `test_inspect_video...` passes online).
Offline check — run `pytest tests/test_downloader.py -m "not network" -v`: PASS (1 passed, 1 deselected).

- [ ] **Step 5: Commit**

```bash
git add app/downloader.py tests/test_downloader.py
git commit -m "feat: downloader.inspect for video/playlist metadata"
```

---

## Task 4: `downloader.download_one` — download a single file

**Files:**
- Modify: `app/downloader.py` (append functions)
- Test: `tests/test_downloader.py` (append test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_downloader.py`:

```python
@pytest.mark.network
def test_download_one_produces_named_audio_file(tmp_path):
    try:
        path = downloader.download_one(TEST_VIDEO, DownloadOptions(), str(tmp_path))
    except downloader.DownloadFailed as exc:
        _skip_if_gone(exc)
    assert os.path.exists(path)
    assert path.endswith(".mp3")
    # Filename follows "<channel> - <title>.mp3".
    assert " - " in os.path.basename(path)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_downloader.py::test_download_one_produces_named_audio_file -v`
Expected: FAIL with `AttributeError: module 'app.downloader' has no attribute 'download_one'`.

- [ ] **Step 3: Append `download_one` to `app/downloader.py`**

```python
def download_one(url: str, options: DownloadOptions, out_dir: str) -> str:
    """Download a single video/audio file into ``out_dir``; return its final path."""
    ydl_opts = build_ydl_opts(options, out_dir)
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=True))
    except DownloadError as exc:
        raise DownloadFailed(_clean(str(exc)))
    return _resolve_path(info)


def _resolve_path(info: dict) -> str:
    """Find the final file path from the post-processed info dict.

    The temp dir is never globbed: EmbedThumbnail/FFmpegMetadata leave
    intermediate .webp/.part/pre-mux artifacts that a glob could pick up.
    """
    downloads = info.get("requested_downloads") or []
    if downloads and downloads[0].get("filepath"):
        return downloads[0]["filepath"]
    if info.get("filepath"):
        return info["filepath"]
    raise DownloadFailed("Could not determine the downloaded file path.")
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_downloader.py::test_download_one_produces_named_audio_file -v`
Expected: PASS (online), or skipped if the test video was removed.

- [ ] **Step 5: Commit**

```bash
git add app/downloader.py tests/test_downloader.py
git commit -m "feat: downloader.download_one"
```

---

## Task 5: `downloader.build_playlist_zip` — streaming playlist ZIP

**Files:**
- Modify: `app/downloader.py` (append functions)
- Test: `tests/test_downloader.py` (append tests)

`build_playlist_zip` returns a `(ZipStream, zip_name)` pair. The `ZipStream` downloads each track lazily as it is iterated, so bytes flow to the client continuously.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_downloader.py`:

```python
def test_build_playlist_zip_rejects_non_playlist(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "inspect", lambda url: {"type": "video"})
    with pytest.raises(downloader.DownloadFailed):
        downloader.build_playlist_zip("http://x", DownloadOptions(), str(tmp_path))


def test_build_playlist_zip_returns_stream_and_name(monkeypatch, tmp_path):
    fake = {
        "type": "playlist",
        "title": "My Mix",
        "count": 1,
        "entries": [{"url": "http://x/1", "title": "Song", "channel": "Band"}],
    }
    monkeypatch.setattr(downloader, "inspect", lambda url: fake)
    # Make each track "download" a tiny file without network.
    def fake_download(url, options, out_dir):
        path = os.path.join(out_dir, "Band - Song.mp3")
        with open(path, "wb") as fh:
            fh.write(b"audio-bytes")
        return path
    monkeypatch.setattr(downloader, "download_one", fake_download)

    stream, name = downloader.build_playlist_zip(
        "http://x", DownloadOptions(), str(tmp_path)
    )
    assert name == "My Mix.zip"
    data = b"".join(stream)
    assert data[:2] == b"PK"            # ZIP magic number
    assert len(data) > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_downloader.py -k playlist_zip -v`
Expected: FAIL with `AttributeError: ... has no attribute 'build_playlist_zip'`.

- [ ] **Step 3: Append the ZIP functions to `app/downloader.py`**

```python
def build_playlist_zip(url: str, options: DownloadOptions, job_dir: str):
    """Return ``(ZipStream, zip_name)`` for a playlist URL.

    The ZipStream downloads each track lazily as it is consumed, so the HTTP
    response starts streaming as soon as the first track finishes. A track that
    fails is skipped and recorded; the failures are written to ``_errors.txt``
    inside the archive.
    """
    data = inspect(url)
    if data["type"] != "playlist":
        raise DownloadFailed("This URL is not a playlist.")

    entries = data["entries"]
    ext = options.format
    stream = ZipStream(sized=False)
    errors: list[str] = []
    used: set[str] = set()

    for idx, entry in enumerate(entries, 1):
        arcname = _arcname(entry, ext, idx, used)
        stream.add(
            _track_bytes(entry, options, job_dir, idx, arcname, errors),
            arcname,
        )
    stream.add(_errors_text(errors), "_errors.txt")

    zip_name = sanitize_filename(data.get("title") or "playlist") + ".zip"
    return stream, zip_name


def _arcname(entry: dict, ext: str, idx: int, used: set) -> str:
    """Build a unique, filesystem-safe ZIP entry name from flat playlist data."""
    channel = entry.get("channel") or "Unknown"
    title = entry.get("title") or f"track-{idx}"
    base = sanitize_filename(f"{channel} - {title}")
    name = f"{base}.{ext}"
    n = 2
    while name in used:
        name = f"{base} ({n}).{ext}"
        n += 1
    used.add(name)
    return name


def _track_bytes(entry, options, job_dir, idx, arcname, errors):
    """Generator: download one track, yield its bytes, then clean up.

    Consumed lazily by ZipStream during streaming. On failure it records the
    error and yields nothing (leaving a 0-byte entry, explained in _errors.txt).
    """
    track_dir = os.path.join(job_dir, f"track-{idx}")
    os.makedirs(track_dir, exist_ok=True)
    try:
        path = download_one(entry["url"], options, track_dir)
    except DownloadFailed as exc:
        errors.append(f"{arcname}: {exc}")
        return
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(CHUNK)
            if not chunk:
                break
            yield chunk
    shutil.rmtree(track_dir, ignore_errors=True)


def _errors_text(errors: list):
    """Generator for _errors.txt, evaluated last so ``errors`` is fully populated."""
    def gen():
        if not errors:
            yield b"All tracks downloaded successfully.\n"
        else:
            yield f"{len(errors)} track(s) failed:\n\n".encode("utf-8")
            for line in errors:
                yield (line + "\n").encode("utf-8")
    return gen()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_downloader.py -k playlist_zip -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full downloader suite offline**

Run: `pytest tests/test_downloader.py -m "not network" -v`
Expected: PASS (network tests deselected).

- [ ] **Step 6: Commit**

```bash
git add app/downloader.py tests/test_downloader.py
git commit -m "feat: streaming playlist ZIP builder"
```

---

## Task 6: `app.py` — FastAPI app and `/api/inspect`

**Files:**
- Create: `app/app.py`
- Test: `tests/test_api.py`

API tests use FastAPI's `TestClient` and monkeypatch `downloader` functions, so no network is needed.

- [ ] **Step 1: Write the failing test**

Create `tests/test_api.py`:

```python
import os

import pytest
from fastapi.testclient import TestClient

from app import app as app_module
from app import downloader


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient with WORK_DIR pointed at a temp directory."""
    monkeypatch.setattr(app_module, "WORK_DIR", tmp_path / "work")
    with TestClient(app_module.app) as c:
        yield c


def test_inspect_returns_video_metadata(client, monkeypatch):
    monkeypatch.setattr(
        downloader, "inspect",
        lambda url: {"type": "video", "title": "Song", "channel": "Band",
                     "duration": 200, "thumbnail": None},
    )
    res = client.post("/api/inspect", json={"url": "http://x"})
    assert res.status_code == 200
    assert res.json()["type"] == "video"


def test_inspect_bad_url_returns_error_json(client, monkeypatch):
    def boom(url):
        raise downloader.DownloadFailed("Unsupported URL")
    monkeypatch.setattr(downloader, "inspect", boom)
    res = client.post("/api/inspect", json={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "Unsupported URL"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.app'`.

- [ ] **Step 3: Write `app/app.py`**

```python
"""FastAPI application: routes, in-memory token store, temp-dir lifecycle."""
import os
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from app import downloader
from app.ytdl_options import DownloadOptions

#: Directory holding per-request temp subdirs. Disk-backed container layer, not /tmp.
WORK_DIR = Path(os.environ.get("WORK_DIR", "/app/work"))
STATIC_DIR = Path(__file__).parent / "static"
TOKEN_TTL = 1800       # seconds a finished file is kept if never fetched
SWEEP_INTERVAL = 300   # seconds between cleanup sweeps

#: token -> {"path", "dir", "filename", "created_at"}
_tokens: dict[str, dict] = {}
_tokens_lock = threading.Lock()


class InspectRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    mode: str = "audio"
    format: str = "mp3"
    quality: str = "320"
    thumbnail: bool = True
    metadata: bool = True


def _error(message: str, code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=code, content={"error": message})


def _content_disposition(filename: str) -> str:
    """Build a Content-Disposition value with an ASCII fallback and RFC 5987 form."""
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _new_job_dir() -> Path:
    job_dir = WORK_DIR / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=True)
    return job_dir


def _sweep() -> None:
    """Drop tokens (and their temp dirs) older than TOKEN_TTL."""
    now = time.time()
    with _tokens_lock:
        stale = [t for t, e in _tokens.items() if now - e["created_at"] > TOKEN_TTL]
        for t in stale:
            entry = _tokens.pop(t)
            shutil.rmtree(entry["dir"], ignore_errors=True)


def _sweep_loop() -> None:
    while True:
        time.sleep(SWEEP_INTERVAL)
        try:
            _sweep()
        except Exception:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Clear anything left from a previous run, then start the periodic sweeper.
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_sweep_loop, daemon=True).start()
    yield


app = FastAPI(title="YouTube MP3 Downloader", lifespan=lifespan)


@app.post("/api/inspect")
def api_inspect(req: InspectRequest):
    """Return video/playlist metadata for a URL."""
    try:
        return downloader.inspect(req.url)
    except downloader.DownloadFailed as exc:
        return _error(str(exc))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/app.py tests/test_api.py
git commit -m "feat: FastAPI app with /api/inspect"
```

---

## Task 7: `/api/download` and `/api/file/{token}`

**Files:**
- Modify: `app/app.py` (append routes)
- Test: `tests/test_api.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_download_then_file_roundtrip(client, monkeypatch):
    # Fake a download that writes a real file into the job dir.
    def fake_download(url, options, out_dir):
        path = os.path.join(out_dir, "Eminem - Mockingbird.mp3")
        with open(path, "wb") as fh:
            fh.write(b"id3-bytes")
        return path
    monkeypatch.setattr(downloader, "download_one", fake_download)

    res = client.post("/api/download", json={"url": "http://x"})
    assert res.status_code == 200
    token = res.json()["token"]

    res2 = client.get(f"/api/file/{token}")
    assert res2.status_code == 200
    assert res2.content == b"id3-bytes"
    cd = res2.headers["content-disposition"]
    assert 'filename="Eminem - Mockingbird.mp3"' in cd
    assert "filename*=UTF-8''" in cd


def test_download_error_returns_error_json(client, monkeypatch):
    def boom(url, options, out_dir):
        raise downloader.DownloadFailed("Video unavailable")
    monkeypatch.setattr(downloader, "download_one", boom)
    res = client.post("/api/download", json={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "Video unavailable"}


def test_file_unknown_token_returns_404(client):
    res = client.get("/api/file/does-not-exist")
    assert res.status_code == 404
    assert "error" in res.json()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_api.py -k "download or file" -v`
Expected: FAIL — `/api/download` returns 404 (route not defined yet).

- [ ] **Step 3: Append the routes to `app/app.py`**

```python
@app.post("/api/download")
def api_download(req: DownloadRequest):
    """Download one file synchronously; return a token for fetching it."""
    options = DownloadOptions(
        mode=req.mode, format=req.format, quality=req.quality,
        embed_thumbnail=req.thumbnail, embed_metadata=req.metadata,
    )
    job_dir = _new_job_dir()
    try:
        path = downloader.download_one(req.url, options, str(job_dir))
    except downloader.DownloadFailed as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return _error(str(exc))

    token = uuid.uuid4().hex
    with _tokens_lock:
        _tokens[token] = {
            "path": path,
            "dir": job_dir,
            "filename": os.path.basename(path),
            "created_at": time.time(),
        }
    return {"token": token}


@app.get("/api/file/{token}")
def api_file(token: str):
    """Stream a previously prepared file, then delete its temp dir."""
    with _tokens_lock:
        entry = _tokens.pop(token, None)
    if entry is None:
        return _error("Unknown or expired download token.", code=404)

    def cleanup():
        shutil.rmtree(entry["dir"], ignore_errors=True)

    return FileResponse(
        entry["path"],
        media_type="application/octet-stream",
        headers={"Content-Disposition": _content_disposition(entry["filename"])},
        background=BackgroundTask(cleanup),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add app/app.py tests/test_api.py
git commit -m "feat: two-step token download endpoints"
```

---

## Task 8: `/api/download-zip`

**Files:**
- Modify: `app/app.py` (append route)
- Test: `tests/test_api.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_download_zip_streams_archive(client, monkeypatch):
    def fake_zip(url, options, job_dir):
        def gen():
            yield b"PK\x03\x04fake-zip-bytes"
        return gen(), "My Mix.zip"
    monkeypatch.setattr(downloader, "build_playlist_zip", fake_zip)

    res = client.get("/api/download-zip", params={"url": "http://x"})
    assert res.status_code == 200
    assert res.content.startswith(b"PK")
    assert "My Mix.zip" in res.headers["content-disposition"]


def test_download_zip_non_playlist_returns_error(client, monkeypatch):
    def boom(url, options, job_dir):
        raise downloader.DownloadFailed("This URL is not a playlist.")
    monkeypatch.setattr(downloader, "build_playlist_zip", boom)

    res = client.get("/api/download-zip", params={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "This URL is not a playlist."}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_api.py -k zip -v`
Expected: FAIL — `/api/download-zip` returns 404.

- [ ] **Step 3: Append the route to `app/app.py`**

```python
@app.get("/api/download-zip")
def api_download_zip(url: str, mode: str = "audio", format: str = "mp3",
                     quality: str = "320", thumbnail: bool = True,
                     metadata: bool = True):
    """Stream a playlist as an on-the-fly ZIP archive."""
    options = DownloadOptions(
        mode=mode, format=format, quality=quality,
        embed_thumbnail=thumbnail, embed_metadata=metadata,
    )
    job_dir = _new_job_dir()
    try:
        zip_stream, zip_name = downloader.build_playlist_zip(
            url, options, str(job_dir)
        )
    except downloader.DownloadFailed as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        return _error(str(exc))

    def cleanup():
        shutil.rmtree(job_dir, ignore_errors=True)

    return StreamingResponse(
        iter(zip_stream),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition(zip_name)},
        background=BackgroundTask(cleanup),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add app/app.py tests/test_api.py
git commit -m "feat: streaming playlist ZIP endpoint"
```

---

## Task 9: Static file serving

**Files:**
- Modify: `app/app.py` (append mount at end of file)
- Create: `app/static/.gitkeep` (temporary, removed in Task 10)

The static mount must be the **last** line of `app.py` so `/api/*` routes are matched first.

- [ ] **Step 1: Create a placeholder so the static dir exists**

Create `app/static/.gitkeep` (empty file) so `StaticFiles` has a directory to point at before Task 10 adds the real files.

- [ ] **Step 2: Append the static mount to the end of `app/app.py`**

```python
# Static frontend — mounted last so /api/* routes take precedence.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
```

- [ ] **Step 3: Run the full test suite to confirm nothing broke**

Run: `pytest -m "not network" -v`
Expected: PASS (all non-network tests — 16 passed: 6 ytdl_options + 3 downloader + 7 api).

- [ ] **Step 4: Commit**

```bash
git add app/app.py app/static/.gitkeep
git commit -m "feat: serve static frontend"
```

---

## Task 10: Frontend — HTML and CSS

**Files:**
- Create: `app/static/index.html`
- Create: `app/static/style.css`
- Delete: `app/static/.gitkeep`

- [ ] **Step 1: Create `app/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>YT Downloader</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <main>
    <h1>&#127925; YT Downloader</h1>

    <div class="options">
      <div class="toggle" id="mode-toggle">
        <button type="button" data-mode="audio" class="active">Audio</button>
        <button type="button" data-mode="video">Video</button>
      </div>
      <label>Format
        <select id="format"></select>
      </label>
      <label>Quality
        <select id="quality"></select>
      </label>
      <label class="check"><input type="checkbox" id="thumbnail" checked> Embed thumbnail</label>
      <label class="check"><input type="checkbox" id="metadata" checked> Embed metadata</label>
    </div>

    <div class="input-row">
      <input type="text" id="url" placeholder="Paste a YouTube video or playlist URL">
      <button type="button" id="download-btn">Download</button>
    </div>

    <p class="error" id="error" hidden></p>
    <p class="status" id="status" hidden></p>
    <div id="results"></div>
  </main>

  <a id="sink" hidden></a>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `app/static/style.css`**

```css
:root {
  --bg: #1e1e24;
  --panel: #2a2a32;
  --panel-2: #3a3a44;
  --accent: #e0457b;
  --text: #eee;
  --muted: #999;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
}

main {
  max-width: 760px;
  margin: 0 auto;
  padding: 32px 20px;
}

h1 { text-align: center; font-size: 24px; }

.options {
  background: var(--panel);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
  font-size: 13px;
}

.options label { display: flex; align-items: center; gap: 6px; }
.options select {
  background: var(--bg);
  color: var(--text);
  border: 1px solid #444;
  padding: 5px;
  border-radius: 4px;
}
.options select:disabled { opacity: 0.4; }

.toggle { display: flex; gap: 4px; background: var(--bg); border-radius: 6px; padding: 3px; }
.toggle button {
  background: transparent;
  color: var(--muted);
  border: none;
  padding: 5px 14px;
  border-radius: 4px;
  cursor: pointer;
}
.toggle button.active { background: var(--accent); color: #fff; }

.input-row { display: flex; gap: 10px; margin-bottom: 18px; }
.input-row input {
  flex: 1;
  background: var(--bg);
  color: var(--text);
  border: 1px solid #444;
  padding: 11px 12px;
  border-radius: 6px;
  font-size: 14px;
}
.input-row button, .pl-actions button {
  background: var(--accent);
  color: #fff;
  border: none;
  padding: 11px 24px;
  border-radius: 6px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
}
.input-row button:disabled { opacity: 0.5; cursor: default; }

.error { color: var(--accent); font-size: 14px; }
.status { color: var(--muted); font-size: 14px; }

.pl-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}
.pl-title { font-weight: 600; }
.pl-actions { display: flex; gap: 8px; }
.pl-actions button { padding: 7px 14px; font-size: 13px; }
.pl-actions button.secondary { background: var(--panel-2); }

.track {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--panel);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 6px;
}
.track img, .track .thumb {
  width: 56px;
  height: 32px;
  border-radius: 3px;
  background: #444;
  flex-shrink: 0;
  object-fit: cover;
}
.track .meta { flex: 1; font-size: 13px; }
.track .meta .dur { color: var(--muted); }
.track button {
  background: var(--panel-2);
  color: var(--text);
  border: none;
  padding: 5px 12px;
  border-radius: 5px;
  font-size: 12px;
  cursor: pointer;
}
.track button:disabled { opacity: 0.5; cursor: default; }
.track .track-status { font-size: 12px; }
.track .track-status.error { color: var(--accent); }
.track .track-status.done { color: #4caf50; }
```

- [ ] **Step 3: Delete the placeholder**

Run: `git rm app/static/.gitkeep`

- [ ] **Step 4: Commit**

```bash
git add app/static/index.html app/static/style.css
git commit -m "feat: frontend markup and styling"
```

---

## Task 11: Frontend — `app.js`

**Files:**
- Create: `app/static/app.js`

Note: this file builds all dynamic DOM with `createElement`/`textContent` — never `innerHTML` — so user-controlled video titles cannot inject markup.

- [ ] **Step 1: Create `app/static/app.js`**

```javascript
"use strict";

const AUDIO_FORMATS = ["mp3", "m4a", "opus", "flac", "wav"];
const VIDEO_FORMATS = ["mp4", "webm", "mkv"];
const AUDIO_QUALITY = [["320", "320 kbps"], ["256", "256 kbps"],
                       ["192", "192 kbps"], ["128", "128 kbps"]];
const VIDEO_QUALITY = [["best", "Best"], ["2160", "2160p"], ["1440", "1440p"],
                       ["1080", "1080p"], ["720", "720p"], ["480", "480p"],
                       ["360", "360p"]];
const LOSSLESS = ["flac", "wav"];

let mode = "audio";

const $ = (id) => document.getElementById(id);

function fillSelect(sel, pairs) {
  sel.innerHTML = "";
  for (const [value, label] of pairs) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    sel.appendChild(opt);
  }
}

function refreshOptions() {
  if (mode === "audio") {
    fillSelect($("format"), AUDIO_FORMATS.map((f) => [f, f.toUpperCase()]));
    fillSelect($("quality"), AUDIO_QUALITY);
  } else {
    fillSelect($("format"), VIDEO_FORMATS.map((f) => [f, f.toUpperCase()]));
    fillSelect($("quality"), VIDEO_QUALITY);
  }
  syncQualityState();
}

function syncQualityState() {
  $("quality").disabled = mode === "audio" && LOSSLESS.includes($("format").value);
}

function currentOptions() {
  return {
    mode: mode,
    format: $("format").value,
    quality: $("quality").value,
    thumbnail: $("thumbnail").checked,
    metadata: $("metadata").checked,
  };
}

function fmtDuration(secs) {
  if (secs == null) return "";
  secs = Math.round(secs);
  const m = Math.floor(secs / 60);
  const s = String(secs % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function showError(msg) {
  $("error").textContent = msg;
  $("error").hidden = false;
}
function clearError() { $("error").hidden = true; }
function setStatus(msg) {
  $("status").textContent = msg || "";
  $("status").hidden = !msg;
}

async function inspectUrl(url) {
  const res = await fetch("/api/inspect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: url }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || "Could not read that URL.");
  }
  return res.json();
}

// Two-step handshake: POST /api/download -> {token}, then navigate to the file.
async function downloadOne(url, options) {
  const res = await fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign({ url: url }, options)),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error || "Download failed.");
  }
  const { token } = await res.json();
  const sink = $("sink");
  sink.href = "/api/file/" + token;
  sink.click();
}

function downloadZip(options) {
  const params = new URLSearchParams({
    url: $("url").value.trim(),
    mode: options.mode,
    format: options.format,
    quality: options.quality,
    thumbnail: String(options.thumbnail),
    metadata: String(options.metadata),
  });
  const sink = $("sink");
  sink.href = "/api/download-zip?" + params.toString();
  sink.click();
}

function setTrackStatus(row, state, message) {
  const el = row.querySelector(".track-status");
  const btn = row.querySelector("button");
  el.className = "track-status " + (state || "");
  if (state === "downloading") { el.textContent = "downloading…"; btn.disabled = true; }
  else if (state === "done") { el.textContent = "done"; btn.disabled = false; }
  else if (state === "error") { el.textContent = message || "failed"; btn.disabled = false; }
  else { el.textContent = ""; btn.disabled = false; }
}

function buildTrackRow(entry, index, options) {
  const row = document.createElement("div");
  row.className = "track";

  const thumb = document.createElement(entry.thumbnail ? "img" : "div");
  thumb.className = "thumb";
  if (entry.thumbnail) thumb.src = entry.thumbnail;

  const meta = document.createElement("div");
  meta.className = "meta";
  const label = `${index + 1}. ${entry.channel} — ${entry.title} `;
  meta.appendChild(document.createTextNode(label));
  const dur = document.createElement("span");
  dur.className = "dur";
  dur.textContent = fmtDuration(entry.duration);
  meta.appendChild(dur);

  const status = document.createElement("span");
  status.className = "track-status";

  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "Download";
  btn.addEventListener("click", async () => {
    setTrackStatus(row, "downloading");
    try {
      await downloadOne(entry.url, options);
      setTrackStatus(row, "done");
    } catch (e) {
      setTrackStatus(row, "error", e.message);
    }
  });

  row.append(thumb, meta, status, btn);
  return row;
}

function renderPlaylist(info) {
  const options = currentOptions();
  const results = $("results");
  results.innerHTML = "";

  const head = document.createElement("div");
  head.className = "pl-head";

  const title = document.createElement("div");
  title.className = "pl-title";
  title.textContent = `${info.title} · ${info.count} videos`;

  const actions = document.createElement("div");
  actions.className = "pl-actions";

  const zipBtn = document.createElement("button");
  zipBtn.type = "button";
  zipBtn.textContent = "Download all (ZIP)";
  zipBtn.addEventListener("click", () => downloadZip(options));

  const seqBtn = document.createElement("button");
  seqBtn.type = "button";
  seqBtn.className = "secondary";
  seqBtn.textContent = "Download all (one by one)";

  actions.append(zipBtn, seqBtn);
  head.append(title, actions);
  results.appendChild(head);

  const rows = info.entries.map((entry, i) => {
    const row = buildTrackRow(entry, i, options);
    results.appendChild(row);
    return row;
  });

  seqBtn.addEventListener("click", async () => {
    zipBtn.disabled = true;
    seqBtn.disabled = true;
    for (let i = 0; i < info.entries.length; i++) {
      setTrackStatus(rows[i], "downloading");
      try {
        await downloadOne(info.entries[i].url, options);
        setTrackStatus(rows[i], "done");
      } catch (e) {
        setTrackStatus(rows[i], "error", e.message);
      }
    }
    zipBtn.disabled = false;
    seqBtn.disabled = false;
  });
}

async function onDownload() {
  const url = $("url").value.trim();
  clearError();
  $("results").innerHTML = "";
  if (!url) { showError("Paste a URL first."); return; }

  $("download-btn").disabled = true;
  setStatus("Reading URL…");
  try {
    const info = await inspectUrl(url);
    if (info.type === "video") {
      setStatus("Downloading…");
      await downloadOne(url, currentOptions());
      setStatus("");
    } else {
      setStatus("");
      renderPlaylist(info);
    }
  } catch (e) {
    setStatus("");
    showError(e.message);
  } finally {
    $("download-btn").disabled = false;
  }
}

function init() {
  refreshOptions();

  $("mode-toggle").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-mode]");
    if (!btn) return;
    mode = btn.dataset.mode;
    for (const b of $("mode-toggle").children) {
      b.classList.toggle("active", b === btn);
    }
    refreshOptions();
  });

  $("format").addEventListener("change", syncQualityState);
  $("download-btn").addEventListener("click", onDownload);
  $("url").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") onDownload();
  });
}

init();
```

- [ ] **Step 2: Manual smoke test**

Run: `WORK_DIR=$(mktemp -d) uvicorn app.app:app --port 8000`
Open `http://localhost:8000`, paste a single YouTube video URL, click Download. Confirm: the spinner shows "Downloading…", then the browser save dialog opens with a `<channel> - <title>.mp3` filename. Then paste a playlist URL and confirm the list renders with per-track buttons.

- [ ] **Step 3: Commit**

```bash
git add app/static/app.js
git commit -m "feat: frontend UI logic"
```

---

## Task 12: Docker packaging

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

# ffmpeg is required by yt-dlp for audio extraction and muxing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV WORK_DIR=/app/work
EXPOSE 8000

# uvicorn imposes no per-request timeout by default, so long synchronous
# downloads are not cut off.
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
services:
  ytdl:
    build: .
    container_name: youtube-mp3-downloader
    ports:
      - "8000:8000"
    restart: unless-stopped
    environment:
      - WORK_DIR=/app/work
    # Uncomment to keep large playlist downloads on host disk instead of the
    # container's writable layer:
    # volumes:
    #   - ./work:/app/work
```

- [ ] **Step 3: Build and run**

Run: `docker compose up -d --build`
Then: `docker compose ps`
Expected: the `ytdl` service is `running`.

- [ ] **Step 4: Smoke test the container**

Open `http://localhost:8000`. Download one video (Audio/MP3) and one playlist (try both "Download all (ZIP)" and "one by one"). Switch to Video mode and download one video. Confirm files arrive correctly named.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: Docker packaging"
```

---

## Task 13: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create `README.md`**

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with usage and update instructions"
```

---

## Final Verification

- [ ] **Run the full offline test suite**

Run: `pytest -m "not network" -v`
Expected: all tests pass (16 passed: 6 ytdl_options + 3 downloader + 7 api); network tests deselected.

- [ ] **Run the network tests once**

Run: `pytest -m network -v`
Expected: pass, or skip if the test video was removed.

- [ ] **Container end-to-end check**

With `docker compose up -d --build` running, verify all four flows in a browser:
single video (audio), single video (video), playlist ZIP, playlist one-by-one.
