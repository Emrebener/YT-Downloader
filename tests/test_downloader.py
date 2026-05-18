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
