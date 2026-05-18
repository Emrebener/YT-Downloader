import os

import pytest

from app import downloader
from app.ytdl_options import DownloadOptions

# "Me at the zoo" — the first-ever YouTube video. Module constant so it can be
# swapped if it ever becomes unavailable.
TEST_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def _skip_if_gone(exc: Exception):
    """Treat 'video removed/unavailable' as a skip, not a failure."""
    msg = str(exc).lower()
    if any(s in msg for s in ("unavailable", "removed", "private", "not available")):
        pytest.skip(f"test video no longer available: {exc}")
    raise


@pytest.mark.network
def test_inspect_video_returns_video_dict():
    try:
        info = downloader.inspect(TEST_VIDEO)
    except downloader.DownloadFailed as exc:
        _skip_if_gone(exc)
    assert info["type"] == "video"
    assert info["title"]
    assert "channel" in info
    assert "duration" in info
    assert "thumbnail" in info


def test_inspect_bad_url_raises_download_failed():
    with pytest.raises(downloader.DownloadFailed):
        downloader.inspect("bogus://x")


@pytest.mark.network
def test_download_one_produces_named_audio_file(tmp_path):
    path = None
    try:
        path = downloader.download_one(TEST_VIDEO, DownloadOptions(), str(tmp_path))
    except downloader.DownloadFailed as exc:
        _skip_if_gone(exc)
    assert path is not None
    assert os.path.exists(path)
    assert path.endswith(".mp3")
    # Filename follows "<channel> - <title>.mp3".
    assert " - " in os.path.basename(path)


def test_resolve_path_prefers_requested_downloads():
    info = {"requested_downloads": [{"filepath": "/tmp/a.mp3"}], "filepath": "/tmp/b.mp3"}
    assert downloader._resolve_path(info) == "/tmp/a.mp3"


def test_resolve_path_falls_back_to_filepath():
    info = {"requested_downloads": [], "filepath": "/tmp/b.mp3"}
    assert downloader._resolve_path(info) == "/tmp/b.mp3"


def test_resolve_path_raises_when_no_path():
    with pytest.raises(downloader.DownloadFailed):
        downloader._resolve_path({})


def test_build_playlist_zip_rejects_non_playlist(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "inspect", lambda url: {"type": "video"})
    with pytest.raises(downloader.DownloadFailed):
        downloader.build_playlist_zip("http://x", DownloadOptions(), str(tmp_path))


def test_build_playlist_zip_returns_stream_and_name(monkeypatch, tmp_path):
    import io
    import zipfile

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
    zf = zipfile.ZipFile(io.BytesIO(data))
    # All tracks succeeded — no _errors.txt is added.
    assert zf.namelist() == ["Band - Song.mp3"]
    assert zf.read("Band - Song.mp3") == b"audio-bytes"


def test_build_playlist_zip_skips_failed_track(monkeypatch, tmp_path):
    import io
    import zipfile

    fake = {
        "type": "playlist",
        "title": "My Mix",
        "count": 2,
        "entries": [
            {"url": "http://x/1", "title": "Good", "channel": "Band"},
            {"url": "http://x/2", "title": "Bad", "channel": "Band"},
        ],
    }
    monkeypatch.setattr(downloader, "inspect", lambda url: fake)

    def fake_download(url, options, out_dir):
        if url == "http://x/2":
            raise downloader.DownloadFailed("boom")
        path = os.path.join(out_dir, "Band - Good.mp3")
        with open(path, "wb") as fh:
            fh.write(b"good-audio")
        return path
    monkeypatch.setattr(downloader, "download_one", fake_download)

    stream, name = downloader.build_playlist_zip(
        "http://x", DownloadOptions(), str(tmp_path)
    )
    data = b"".join(stream)
    zf = zipfile.ZipFile(io.BytesIO(data))
    # The failed track produces NO entry at all — not an empty file.
    assert zf.namelist() == ["Band - Good.mp3", "_errors.txt"]
    assert zf.read("Band - Good.mp3") == b"good-audio"
    errors_txt = zf.read("_errors.txt").decode("utf-8")
    assert "Bad" in errors_txt and "boom" in errors_txt


def test_build_playlist_zip_all_failed_raises(monkeypatch, tmp_path):
    fake = {
        "type": "playlist",
        "title": "Dead Mix",
        "count": 2,
        "entries": [
            {"url": "http://x/1", "title": "A", "channel": "C"},
            {"url": "http://x/2", "title": "B", "channel": "C"},
        ],
    }
    monkeypatch.setattr(downloader, "inspect", lambda url: fake)
    monkeypatch.setattr(
        downloader, "download_one",
        lambda url, options, out_dir: (_ for _ in ()).throw(
            downloader.DownloadFailed("Video unavailable")
        ),
    )

    with pytest.raises(downloader.DownloadFailed):
        downloader.build_playlist_zip("http://x", DownloadOptions(), str(tmp_path))


def test_cookie_file_returns_path_when_present(monkeypatch, tmp_path):
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("COOKIES_FILE", str(f))
    assert downloader.cookie_file() == str(f)


def test_cookie_file_returns_none_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("COOKIES_FILE", str(tmp_path / "absent.txt"))
    assert downloader.cookie_file() is None


def test_download_failed_defaults_cookies_expired_false():
    assert downloader.DownloadFailed("oops").cookies_expired is False


def test_download_failed_accepts_cookies_expired():
    assert downloader.DownloadFailed("oops", cookies_expired=True).cookies_expired is True


def test_signin_wall_detects_bot_check():
    assert downloader._signin_wall("ERROR: Sign in to confirm you're not a bot")


def test_signin_wall_detects_age_confirmation():
    assert downloader._signin_wall("Please confirm your age")


def test_signin_wall_ignores_plain_error():
    assert not downloader._signin_wall("Video unavailable")


def test_friendly_returns_hint_for_signin_wall():
    msg = downloader._friendly("ERROR: Sign in to confirm you're not a bot")
    assert "cookies.txt" in msg
    assert "sign-in" in msg.lower()


def test_friendly_passes_through_plain_error():
    assert downloader._friendly("ERROR: Video unavailable") == "Video unavailable"


class _SigninWallYDL:
    """Fake YoutubeDL whose extract_info always raises YouTube's bot wall."""

    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def sanitize_info(self, info):
        return info

    def extract_info(self, url, download=False):
        from yt_dlp.utils import YoutubeDLError
        raise YoutubeDLError("ERROR: Sign in to confirm you're not a bot")


def test_inspect_flags_expired_when_cookies_present(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "YoutubeDL", _SigninWallYDL)
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("COOKIES_FILE", str(f))
    with pytest.raises(downloader.DownloadFailed) as exc:
        downloader.inspect("http://x")
    assert exc.value.cookies_expired is True


def test_inspect_no_flag_when_cookies_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "YoutubeDL", _SigninWallYDL)
    monkeypatch.setenv("COOKIES_FILE", str(tmp_path / "absent.txt"))
    with pytest.raises(downloader.DownloadFailed) as exc:
        downloader.inspect("http://x")
    assert exc.value.cookies_expired is False


def test_download_one_flags_expired_when_cookies_present(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "YoutubeDL", _SigninWallYDL)
    f = tmp_path / "cookies.txt"
    f.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setenv("COOKIES_FILE", str(f))
    with pytest.raises(downloader.DownloadFailed) as exc:
        downloader.download_one("http://x", DownloadOptions(), str(tmp_path))
    assert exc.value.cookies_expired is True


def test_download_one_no_flag_when_cookies_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "YoutubeDL", _SigninWallYDL)
    monkeypatch.setenv("COOKIES_FILE", str(tmp_path / "absent.txt"))
    with pytest.raises(downloader.DownloadFailed) as exc:
        downloader.download_one("http://x", DownloadOptions(), str(tmp_path))
    assert exc.value.cookies_expired is False
