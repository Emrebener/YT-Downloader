"""The only module that touches yt-dlp: inspect URLs, download files, build ZIPs."""
import os
import shutil

from yt_dlp import YoutubeDL
from yt_dlp.utils import YoutubeDLError, sanitize_filename
from zipstream import ZipStream

from app.ytdl_options import DownloadOptions, build_ydl_opts


class DownloadFailed(Exception):
    """Raised when yt-dlp cannot inspect or download a URL."""


def _clean(message: str) -> str:
    """Strip yt-dlp's noisy 'ERROR:' prefix for display to the user."""
    return message.replace("ERROR:", "").strip()


def _friendly(message: str) -> str:
    """Turn a raw yt-dlp error into a concise, user-facing message.

    YouTube's sign-in / bot-check wall has a long, link-laden error; collapse it
    into a short hint pointing at cookie setup.
    """
    cleaned = _clean(message)
    low = cleaned.lower()
    if "sign in to confirm" in low or "not a bot" in low or "confirm your age" in low:
        return ("YouTube blocked this download with a sign-in check. Add a "
                "cookies.txt file — or refresh it if it has expired. See the "
                "app's setup notes.")
    return cleaned


def cookie_file() -> str | None:
    """Return the configured cookies.txt path if the file exists, else None.

    The path comes from the ``COOKIES_FILE`` env var (default
    ``/app/cookies/cookies.txt``). Read at call time so it stays current.
    """
    path = os.environ.get("COOKIES_FILE", "/app/cookies/cookies.txt")
    return path if os.path.isfile(path) else None


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
    cookies = cookie_file()
    if cookies:
        opts["cookiefile"] = cookies
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=False))
            if info is None:
                raise DownloadFailed("Could not retrieve metadata for this URL.")
    except YoutubeDLError as exc:
        raise DownloadFailed(_friendly(str(exc)))

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
    ydl_opts = build_ydl_opts(options, out_dir, cookiefile=cookie_file())
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.sanitize_info(ydl.extract_info(url, download=True))
            if info is None:
                raise DownloadFailed("Could not download this URL.")
    except YoutubeDLError as exc:
        raise DownloadFailed(_friendly(str(exc)))
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

    Every track is downloaded first; only the files that download successfully
    are added to the archive. Videos that are unavailable, private or removed
    are skipped entirely — they produce no ZIP entry — and are listed in an
    ``_errors.txt`` file inside the archive. The returned ZipStream then streams
    the finished files straight from disk.
    """
    data = inspect(url)
    if data["type"] != "playlist":
        raise DownloadFailed("This URL is not a playlist.")

    entries = data["entries"]
    if not entries:
        raise DownloadFailed("Playlist is empty or has no accessible entries.")

    files: list[tuple[str, str]] = []   # (arcname, filepath) for each success
    errors: list[str] = []
    used: set[str] = set()

    for idx, entry in enumerate(entries, 1):
        track_dir = os.path.join(job_dir, f"track-{idx}")
        os.makedirs(track_dir, exist_ok=True)
        try:
            path = download_one(entry["url"], options, track_dir)
        except DownloadFailed as exc:
            label = entry.get("title") or f"track-{idx}"
            errors.append(f"{label}: {exc}")
            shutil.rmtree(track_dir, ignore_errors=True)
            continue
        files.append((_dedupe(os.path.basename(path), used), path))

    if not files:
        detail = errors[0] if errors else "the playlist had no usable entries"
        raise DownloadFailed(
            f"All {len(entries)} videos failed to download. First error — {detail}"
        )

    stream = ZipStream(sized=False)
    for arcname, path in files:
        stream.add_path(path, arcname)
    if errors:
        summary = f"{len(errors)} video(s) skipped (unavailable or failed):\n\n"
        stream.add((summary + "\n".join(errors) + "\n").encode("utf-8"),
                   "_errors.txt")

    zip_name = sanitize_filename(data.get("title") or "playlist") + ".zip"
    return stream, zip_name


def _dedupe(name: str, used: set) -> str:
    """Return ``name`` made unique against ``used`` by adding a ``(n)`` suffix."""
    if name not in used:
        used.add(name)
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while True:
        candidate = f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})"
        if candidate not in used:
            used.add(candidate)
            return candidate
        n += 1
