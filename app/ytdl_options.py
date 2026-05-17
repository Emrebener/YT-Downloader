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
