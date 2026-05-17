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
