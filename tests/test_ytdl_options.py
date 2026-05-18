import pytest

from app.ytdl_options import DownloadOptions, build_ydl_opts, OUTTMPL


def test_audio_mp3_defaults():
    opts = build_ydl_opts(DownloadOptions(), "/work/job1")
    assert opts["format"] == "bestaudio/best"
    assert opts["paths"] == {"home": "/work/job1"}
    assert opts["outtmpl"] == {"default": OUTTMPL}
    extract = opts["postprocessors"][0]
    assert extract["key"] == "FFmpegExtractAudio"
    assert extract["preferredcodec"] == "mp3"
    assert extract["preferredquality"] == "320"


def test_audio_with_thumbnail_and_metadata():
    opts = build_ydl_opts(DownloadOptions(), "/work/job1")
    keys = [pp["key"] for pp in opts["postprocessors"]]
    assert keys == ["FFmpegExtractAudio", "FFmpegMetadata", "EmbedThumbnail"]
    assert opts["writethumbnail"] is True


def test_audio_without_extras():
    options = DownloadOptions(embed_thumbnail=False, embed_metadata=False)
    opts = build_ydl_opts(options, "/work/job1")
    keys = [pp["key"] for pp in opts["postprocessors"]]
    assert keys == ["FFmpegExtractAudio"]
    assert "writethumbnail" not in opts


@pytest.mark.parametrize("fmt", ["flac", "wav"])
def test_lossless_format_has_no_quality(fmt):
    options = DownloadOptions(format=fmt)
    opts = build_ydl_opts(options, "/work/job1")
    extract = opts["postprocessors"][0]
    assert extract["preferredcodec"] == fmt
    assert "preferredquality" not in extract


def test_video_best():
    options = DownloadOptions(mode="video", format="mp4", quality="best")
    opts = build_ydl_opts(options, "/work/job1")
    assert opts["format"] == "bestvideo*+bestaudio/best"
    assert opts["merge_output_format"] == "mp4"
    keys = [pp["key"] for pp in opts["postprocessors"]]
    assert "FFmpegMetadata" in keys
    assert "EmbedThumbnail" in keys
    assert opts["writethumbnail"] is True


def test_video_resolution_cap():
    options = DownloadOptions(mode="video", format="mkv", quality="1080")
    opts = build_ydl_opts(options, "/work/job1")
    assert opts["format"] == "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    assert opts["merge_output_format"] == "mkv"
    keys = [pp["key"] for pp in opts["postprocessors"]]
    assert "FFmpegMetadata" in keys
    assert "EmbedThumbnail" in keys
    assert opts["writethumbnail"] is True


def test_cookiefile_added_when_given():
    opts = build_ydl_opts(DownloadOptions(), "/work/job1",
                          cookiefile="/c/cookies.txt")
    assert opts["cookiefile"] == "/c/cookies.txt"


def test_cookiefile_absent_by_default():
    opts = build_ydl_opts(DownloadOptions(), "/work/job1")
    assert "cookiefile" not in opts
