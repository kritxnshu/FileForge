"""Audio & video: matrix with ffprobe + decoded-content checks, metadata, remux, two-pass, security."""

from __future__ import annotations

import pytest
from conftest import convert, pairs_of
from fixtures.generate import MEDIA_SECONDS, path

from engine.validators.images import validate_image
from engine.validators.media import center_pixel, probe, validate_media

A_CODEC = {"mp3": "mp3", "wav": "pcm_s16le", "aac": "aac", "flac": "flac", "ogg": "vorbis", "m4a": "aac", "opus": "opus",
           "wma": "wmav2"}
V_CODEC = {"mp4": "h264", "mov": "h264", "mkv": "h264", "webm": "vp9", "avi": "mpeg4", "flv": "h264", "wmv": "wmv2",
           "3gp": "h264"}
VA_CODEC = {"mp4": "aac", "mov": "aac", "mkv": "aac", "webm": "opus", "avi": "mp3", "flv": "aac", "wmv": "wmav2", "3gp": "aac"}
SLOW = 240


@pytest.mark.parametrize("src,dst", pairs_of("audio.convert"))
def test_audio_matrix(src, dst):
    r = convert("audio.convert", path(f"tone.{src}"), dst, timeout=SLOW)
    assert r.ok, r.error
    validate_media(r.out, audio_codec=A_CODEC[dst], duration=MEDIA_SECONDS, tol=0.4)
    assert any(e.get("total") == 100 for e in r.progress), "no FFmpeg progress was reported"


@pytest.mark.verifies("audio.convert:mp3->m4a", "audio.convert:mp3->wav")
def test_audio_metadata_carry_over():
    r = convert("audio.convert", path("tagged.mp3"), "m4a", timeout=SLOW)
    tags = {k.lower(): v for k, v in probe(r.out)["format"].get("tags", {}).items()}
    assert tags["title"] == "Known Tone" and tags["artist"] == "Fixture Band" and tags["album"] == "Test Album"
    assert any(s.get("disposition", {}).get("attached_pic") for s in probe(r.out)["streams"])
    assert any("cover art" in n for n in r.notices)
    r = convert("audio.convert", path("tagged.mp3"), "wav", timeout=SLOW)
    assert any("cover art" in w for w in r.warnings)


@pytest.mark.verifies("audio.convert:wav->mp3")
def test_audio_options_bitrate_rate_channels():
    r = convert("audio.convert", path("tone.wav"), "mp3", {"bitrate": 320, "sample_rate": 44100, "channels": "mono"}, timeout=SLOW)
    a = [s for s in probe(r.out)["streams"] if s["codec_type"] == "audio"][0]
    assert a["sample_rate"] == "44100" and a["channels"] == 1 and abs(int(a["bit_rate"]) - 320000) < 20000
    # MP3 below 32 kHz can't exceed 160 kbps: the user is told the bitrate was capped
    r = convert("audio.convert", path("tone.wav"), "mp3", {"bitrate": 320, "sample_rate": 22050}, timeout=SLOW)
    assert [s for s in probe(r.out)["streams"] if s["codec_type"] == "audio"][0]["sample_rate"] == "22050"
    assert any("capped" in n for n in r.notices)


@pytest.mark.parametrize("src,dst", pairs_of("audio.edit"))
def test_audio_edit_trim_normalize(src, dst):
    r = convert("audio.edit", path(f"tone.{src}"), options={"start": 0.5, "end": 2.0, "normalize": True}, timeout=SLOW)
    assert r.ok, r.error
    validate_media(r.out, audio_codec=A_CODEC[src], duration=1.5, tol=0.25)


@pytest.mark.verifies("neg:audio.convert", "neg:audio.edit")
def test_audio_negative(tmp_path):
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"ID3" + b"\x00" * 50)
    r = convert("audio.convert", bad, "wav", formats=["mp3"])
    assert not r.ok and r.error["code"] == "corrupt_input"
    r = convert("audio.edit", path("tone.wav"), options={"start": 10})
    assert not r.ok and "after the end" in r.error["message"]
    from engine.registry import get

    with pytest.raises(ValueError):
        get("audio.convert").options.model_validate({"start": 2, "end": 1})


@pytest.mark.parametrize("src,dst", pairs_of("video.convert"))
def test_video_matrix(src, dst):
    r = convert("video.convert", path(f"video.{src}"), dst, timeout=SLOW)
    assert r.ok, r.error
    validate_media(r.out, video_codec=V_CODEC[dst] if not r.info.get("remuxed") else None, audio_codec=VA_CODEC[dst]
                   if not r.info.get("remuxed") else None, duration=MEDIA_SECONDS, tol=0.5, red_video=True)


@pytest.mark.verifies("video.convert:mp4->mkv", "video.convert:mkv->mp4")
def test_video_remux_fast_path():
    r = convert("video.convert", path("video.mp4"), "mkv")
    assert r.info.get("remuxed") and any("without re-encoding" in n for n in r.notices)
    info = validate_media(r.out, video_codec="h264", audio_codec="aac", duration=MEDIA_SECONDS)
    assert info["format"]["format_name"].startswith("matroska")
    r = convert("video.convert", path("video.mkv"), "mp4", {"allow_copy": False})
    assert not r.info.get("remuxed")


@pytest.mark.parametrize("src,dst", pairs_of("video.edit"))
def test_video_edit(src, dst):
    r = convert("video.edit", path(f"video.{src}"), options={"start": 0.5, "end": 2.5, "resolution": "360" if src != "3gp" else "keep",
                                                            "fps": "15", "quality": "low"}, timeout=SLOW)
    assert r.ok, r.error
    validate_media(r.out, duration=2.0, tol=0.4, red_video=True)


@pytest.mark.verifies("video.edit:mp4->mp4")
def test_video_target_size_two_pass(tmp_path):
    import subprocess

    big = tmp_path / "noise.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=6", "-c:v", "libx264", "-crf", "10",
                    "-pix_fmt", "yuv420p", str(big)], check=True)
    r = convert("video.edit", big, options={"target_size_mb": 0.25, "allow_copy": False}, formats=["mp4"], timeout=SLOW)
    assert r.ok, r.error
    size = r.out.stat().st_size / 1048576
    assert 0.12 < size < 0.35, size
    stages = [e.get("stage", "") for e in r.progress]
    assert any("pass 1 of 2" in s for s in stages) and any("pass 2 of 2" in s for s in stages)


@pytest.mark.verifies("neg:video.convert", "neg:video.edit")
def test_video_negative(tmp_path):
    import subprocess

    r = convert("video.convert", path("truncated.mp4"), "webm", formats=["mp4"])
    assert not r.ok and r.error["code"] == "corrupt_input" and "truncated" in r.error["message"]
    r = convert("video.convert", path("truncated.mp4"), "mkv", formats=["mp4"])  # remux path too
    assert not r.ok and r.error["code"] == "corrupt_input"
    long = tmp_path / "long.mp4"  # 20 s: 0.11 MB leaves < 50 kbps for video
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=20", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(long)], check=True)
    r = convert("video.edit", long, options={"target_size_mb": 0.11, "allow_copy": False}, formats=["mp4"])
    assert not r.ok and "too small" in r.error["message"]


@pytest.mark.parametrize("src,dst", pairs_of("video.to_gif"))
def test_video_to_gif(src, dst):
    r = convert("video.to_gif", path(f"video.{src}"), "gif", {"fps": 10, "width": 160, "duration": 2}, timeout=SLOW)
    assert r.ok, r.error
    from engine.validators.images import open_image

    im = open_image(r.out)
    assert im.format == "GIF" and im.width == 160 and 15 <= im.n_frames <= 25
    assert im.convert("RGB").getpixel((80, 60))[0] > 180


@pytest.mark.verifies("neg:video.to_gif")
def test_video_to_gif_limits():
    from engine.registry import get

    with pytest.raises(ValueError):
        get("video.to_gif").options.model_validate({"duration": 60})
    r = convert("video.to_gif", path("video.mp4"), "gif", {"start": 9})
    assert not r.ok


@pytest.mark.parametrize("src,dst", pairs_of("video.from_gif"))
def test_gif_to_video(src, dst):
    r = convert("video.from_gif", path("animated.gif"), dst, timeout=SLOW)
    assert r.ok, r.error
    validate_media(r.out, video_codec=V_CODEC[dst], duration=0.6, tol=0.25, tone_hz=None)
    r_, g_, b_ = center_pixel(r.out, 0)  # first frame (pts 0) is red; -ss drops frames before the seek point
    assert r_ > 180 and g_ < 90
    import json
    import subprocess

    frames = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time",
                                        "-of", "json", str(r.out)], capture_output=True, text=True).stdout)["frames"]
    assert [round(float(f["pts_time"]), 2) for f in frames] == [0.0, 0.1, 0.3]  # GIF frame timing kept


@pytest.mark.verifies("neg:video.from_gif")
def test_gif_to_video_corrupt():
    r = convert("video.from_gif", path("truncated.png"), "mp4", formats=["gif"])
    assert not r.ok


@pytest.mark.parametrize("src,dst", pairs_of("video.extract_audio"))
def test_extract_audio(src, dst):
    r = convert("video.extract_audio", path(f"video.{src}"), dst, timeout=SLOW)
    assert r.ok, r.error
    validate_media(r.out, audio_codec=A_CODEC[dst], duration=MEDIA_SECONDS, tol=0.5)
    assert not [s for s in probe(r.out)["streams"] if s["codec_type"] == "video"]


@pytest.mark.verifies("neg:video.extract_audio")
def test_extract_audio_no_track(tmp_path):
    import subprocess

    silent = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-c:v", "libx264", "-pix_fmt",
                    "yuv420p", str(silent)], check=True)
    r = convert("video.extract_audio", silent, "mp3", formats=["mp4"])
    assert not r.ok and r.error["code"] == "no_audio"


@pytest.mark.parametrize("src,dst", pairs_of("video.thumbnail"))
def test_thumbnail(src, dst):
    r = convert("video.thumbnail", path(f"video.{src}"), dst, {"at": 1.5, "width": 160}, timeout=SLOW)
    assert r.ok, r.error
    validate_image(r.out, dst, color_blocks=False)
    from engine.validators.images import open_image

    im = open_image(r.out)
    assert im.width == 160 and im.convert("RGB").getpixel((80, 50))[0] > 180


@pytest.mark.verifies("neg:video.thumbnail")
def test_thumbnail_past_end():
    r = convert("video.thumbnail", path("video.mp4"), "png", {"at": 99})
    assert not r.ok and "only 3.0 seconds" in r.error["message"]


# --- security: playlist inputs ---------------------------------------------------


@pytest.mark.parametrize("kind", ["hls", "ffconcat"])
def test_playlist_inputs_rejected(tmp_path, kind):
    from test_security import Canary

    c = Canary()
    try:
        p = tmp_path / "evil.mp4"
        if kind == "hls":
            p.write_text(f"#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.0,\n{c.url}/seg.ts\n#EXTINF:1.0,\nfile:///etc/passwd\n#EXT-X-ENDLIST\n")
        else:
            p.write_text(f"ffconcat version 1.0\nfile '{path('video.mp4')}'\nfile '{c.url}/x.mp4'\n")
        for op, tgt in (("video.convert", "webm"), ("video.extract_audio", "mp3"), ("audio.convert", "wav")):
            r = convert(op, p, tgt, formats=["mp4" if op != "audio.convert" else "mp3"])
            assert not r.ok, f"{op} accepted a {kind} playlist"
            assert r.error["code"] == "corrupt_input"
        assert c.hits == []
    finally:
        c.close()


def test_playlist_upload_is_not_detected_as_media(tmp_path):
    from conftest import TMP

    from engine.detect import detect

    p = tmp_path / "x.mp4"
    p.write_text("#EXTM3U\n#EXTINF:1,\nhttp://169.254.169.254/x.ts\n")
    d = detect(p, "x.mp4", probe_dir=TMP)
    assert d.format == "txt"  # never routed to FFmpeg
