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
