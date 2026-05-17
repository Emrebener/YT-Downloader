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


def download_one(url: str, options: DownloadOptions, out_dir: str) -> str:
    """Download a single video/audio file into ``out_dir``; return its final path."""
    ydl_opts = build_ydl_opts(options, out_dir)
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=True))
            if info is None:
                raise DownloadFailed("Could not download this URL.")
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
