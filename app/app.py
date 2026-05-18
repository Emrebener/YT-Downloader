"""FastAPI application: routes, in-memory token store, temp-dir lifecycle."""
import logging
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


def _error(message: str, code: int = 400, cookies_expired: bool = False) -> JSONResponse:
    body = {"error": message}
    if cookies_expired:
        body["cookies_expired"] = True
    return JSONResponse(status_code=code, content=body)


def _content_disposition(filename: str) -> str:
    """Build a Content-Disposition value with an ASCII fallback and RFC 5987 form."""
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    return (
        f"attachment; filename=\"{ascii_name}\"; "
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )


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
            logging.getLogger(__name__).warning(
                "cleanup sweep failed", exc_info=True
            )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Clear anything left from a previous run, then start the periodic sweeper.
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR, ignore_errors=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=_sweep_loop, daemon=True).start()
    yield


app = FastAPI(title="YouTube MP3 Downloader", lifespan=lifespan)


@app.get("/api/status")
def api_status():
    """Report whether a YouTube cookies file is configured."""
    return {"cookies": downloader.cookie_file() is not None}


@app.post("/api/inspect")
def api_inspect(req: InspectRequest):
    """Return video/playlist metadata for a URL."""
    try:
        return downloader.inspect(req.url)
    except downloader.DownloadFailed as exc:
        return _error(str(exc), cookies_expired=exc.cookies_expired)


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
        return _error(str(exc), cookies_expired=exc.cookies_expired)

    token = uuid.uuid4().hex
    with _tokens_lock:
        _tokens[token] = {
            "path": path,
            "dir": str(job_dir),
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
        return _error(str(exc), cookies_expired=exc.cookies_expired)

    def cleanup():
        shutil.rmtree(job_dir, ignore_errors=True)

    return StreamingResponse(
        iter(zip_stream),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition(zip_name)},
        background=BackgroundTask(cleanup),
    )


# Static frontend — mounted last so /api/* routes take precedence.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
