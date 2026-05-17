import os

import pytest
from fastapi.testclient import TestClient

from app import app as app_module
from app import downloader


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """A TestClient with WORK_DIR pointed at a temp directory."""
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
    assert res.json()["type"] == "video"


def test_inspect_bad_url_returns_error_json(client, monkeypatch):
    def boom(url):
        raise downloader.DownloadFailed("Unsupported URL")
    monkeypatch.setattr(downloader, "inspect", boom)
    res = client.post("/api/inspect", json={"url": "http://x"})
    assert res.status_code == 400
    assert res.json() == {"error": "Unsupported URL"}
