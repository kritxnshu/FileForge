"""Audio/video validators: ffprobe for codec + duration, decoded samples for content."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import check


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                         capture_output=True, text=True, timeout=60)
    check(out.returncode == 0, f"ffprobe can't read {path.name}: {out.stderr[-300:]}")
    return json.loads(out.stdout)


def dominant_hz(path: Path) -> float:
    import numpy as np

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "8000",
                          "-f", "s16le", "-"], capture_output=True, timeout=60).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(float)
    check(len(a) > 2000, "too little audio decoded")
    spec = np.abs(np.fft.rfft(a * np.hanning(len(a))))
    return float(np.fft.rfftfreq(len(a), 1 / 8000)[spec.argmax()])


def center_pixel(path: Path, at: float = 1.0) -> tuple[int, int, int]:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1", "-vf", "scale=8:8",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=60).stdout
    check(len(raw) >= 192, "no frame decoded")
    i = (4 * 8 + 4) * 3
    return raw[i], raw[i + 1], raw[i + 2]


def validate_media(path: Path, *, audio_codec: str | set | None = None, video_codec: str | set | None = None,
                   duration: float | None = None, tol: float = 0.35, tone_hz: float | None = 440,
                   red_video: bool = False) -> dict:
    info = probe(path)
    streams = info["streams"]
    a = [s for s in streams if s["codec_type"] == "audio"]
    v = [s for s in streams if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")]
    if audio_codec:
        want = {audio_codec} if isinstance(audio_codec, str) else audio_codec
        check(bool(a) and a[0]["codec_name"] in want, f"audio codec {a[0]['codec_name'] if a else None} not in {want}")
    if video_codec:
        want = {video_codec} if isinstance(video_codec, str) else video_codec
        check(bool(v) and v[0]["codec_name"] in want, f"video codec {v[0]['codec_name'] if v else None} not in {want}")
    if duration is not None:
        d = float(info["format"].get("duration") or 0)
        check(abs(d - duration) <= tol, f"duration {d:.2f}s, expected {duration:.2f}±{tol}")
    if tone_hz and a:
        hz = dominant_hz(path)
        check(abs(hz - tone_hz) < 12, f"dominant frequency {hz:.0f} Hz, expected {tone_hz}")
    if red_video:
        r, g, b = center_pixel(path, 0.5)
        check(r > 180 and g < 90 and b < 90, f"frame should be red, got {(r, g, b)}")
    return info
