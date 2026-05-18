import os

import pytest
from fastapi.testclient import TestClient

from app import app as app_module
from app import downloader


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient with WORK_DIR pointed at a temp directory."""
    # WORK_DIR must be patched BEFORE entering TestClient: the lifespan handler
    # reads it on startup. lifespan/_new_job_dir read the module global at call
    # time, so patching the module attribute here takes effect.
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
    data = res.json()
    assert data["type"] == "video"
    assert {"title", "channel", "duration", "thumbnail"} <= data.keys()


def test_inspect_returns_playlist_metadata(client, monkeypatch):
    monkeypatch.setattr(
        downloader, "inspect",
        lambda url: {
            "type": "playlist", "title": "My Mix", "count": 2,
            "entries": [
                {"id": "1", "url": "u1", "title": "A", "channel": "C",
                 "duration": 10, "thumbnail": None},
                {"id": "2", "url": "u2", "title": "B", "channel": "C",
                 "duration": 20, "thumbnail": None},
            ],
        },
    )
    res = client.post("/api/inspect", json={"url": "http://x"})
    assert res.status_code == 200
    data = res.json()
    assert data["type"] == "playlist"
    assert data["count"] == 2
    assert len(data["entries"]) == 2


def test_inspect_bad_url_returns_error_json(client, monkeypatch):
    def boom(url):
        raise downloader.DownloadFailed("Unsupported URL")
    monkeypatch.setattr(downloader, "inspect", boom)
    res = client.post("/api/inspect", json={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "Unsupported URL"}


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

    # The BackgroundTask cleanup runs synchronously under TestClient,
    # so the job dir must be gone after the file has been served.
    work_dir = app_module.WORK_DIR
    remaining = list(work_dir.iterdir()) if work_dir.exists() else []
    assert remaining == [], f"job dir not cleaned up: {remaining}"


def test_download_error_returns_error_json(client, monkeypatch):
    def boom(url, options, out_dir):
        raise downloader.DownloadFailed("Video unavailable")
    monkeypatch.setattr(downloader, "download_one", boom)
    res = client.post("/api/download", json={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "Video unavailable"}

    # The failing download must not leak its job dir.
    work_dir = app_module.WORK_DIR
    remaining = list(work_dir.iterdir()) if work_dir.exists() else []
    assert remaining == [], f"job dir leaked on failure: {remaining}"


def test_file_unknown_token_returns_404(client):
    res = client.get("/api/file/does-not-exist")
    assert res.status_code == 404
    assert "error" in res.json()


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

    # The BackgroundTask cleanup runs synchronously under TestClient,
    # so the job dir must be gone after the ZIP has streamed.
    work_dir = app_module.WORK_DIR
    remaining = list(work_dir.iterdir()) if work_dir.exists() else []
    assert remaining == [], f"job dir not cleaned up after ZIP stream: {remaining}"


def test_download_zip_non_playlist_returns_error(client, monkeypatch):
    def boom(url, options, job_dir):
        raise downloader.DownloadFailed("This URL is not a playlist.")
    monkeypatch.setattr(downloader, "build_playlist_zip", boom)

    res = client.get("/api/download-zip", params={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "This URL is not a playlist."}


def test_status_reports_cookies_absent(client, monkeypatch):
    monkeypatch.setattr(downloader, "cookie_file", lambda: None)
    res = client.get("/api/status")
    assert res.status_code == 200
    assert res.json() == {"cookies": False}


def test_status_reports_cookies_present(client, monkeypatch):
    monkeypatch.setattr(downloader, "cookie_file", lambda: "/c/cookies.txt")
    res = client.get("/api/status")
    assert res.status_code == 200
    assert res.json() == {"cookies": True}
