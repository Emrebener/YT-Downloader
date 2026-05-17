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
            if info is None:
                raise DownloadFailed("Could not retrieve metadata for this URL.")
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
    """Return the best available thumbnail URL for a playlist entry."""
    for thumb in reversed(e.get("thumbnails") or []):
        if thumb.get("url"):
            return thumb["url"]
    if e.get("id"):
        return f"https://i.ytimg.com/vi/{e['id']}/default.jpg"
    return None
