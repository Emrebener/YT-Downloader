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
        downloader.inspect("https://not-a-real-site.example/nope")
