"""FFmpeg / ffprobe runner.

Hazards (SECURITY.md): a "media" file can be a playlist (HLS, concat, ffconcat) that makes FFmpeg
open local files or URLs. Every invocation therefore passes
  -protocol_whitelist file,pipe   and   -format_whitelist <real container demuxers>
so playlist/network demuxers are refused, and inputs are probed first. The job sandbox also has
no network. Progress comes from `-progress pipe:1` (out_time_us vs the input duration).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from functools import cache
from pathlib import Path

from .context import ConversionError, Ctx

DEMUXERS = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,avi,flv,asf,wav,mp3,aac,flac,ogg,gif"


def exe(name: str) -> str:
    p = os.environ.get(f"UC_{name.upper()}") or shutil.which(name)
    if not p:
        raise ConversionError("engine_missing", f"{name} isn't installed on this server.")
    return p


@cache
def encoders() -> frozenset[str]:
    try:
        out = subprocess.run([exe("ffmpeg"), "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
            names.add(parts[1])
    return frozenset(names)


def probe(ctx: Ctx, path: Path) -> dict:
    res = ctx.run([exe("ffprobe"), "-v", "error", "-protocol_whitelist", "file", "-format_whitelist", DEMUXERS,
                   "-show_format", "-show_streams", "-of", "json", str(path)], check=False, timeout_s=60)
    if res.returncode != 0:
        raise ConversionError("corrupt_input", "This media file is damaged, truncated or in a format we can't read.")
    info = json.loads(res.stdout or b"{}")
    if not info.get("streams"):
        raise ConversionError("corrupt_input", "This file has no audio or video streams.")
    return info


def duration(info: dict) -> float:
    try:
        return float(info.get("format", {}).get("duration") or 0)
    except ValueError:
        return 0.0


def streams(info: dict, kind: str) -> list[dict]:
    return [s for s in info.get("streams", []) if s.get("codec_type") == kind
            and not (kind == "video" and s.get("disposition", {}).get("attached_pic"))]


def run(ctx: Ctx, args: list[str], *, total_s: float, stage: str, offset: float = 0.0, span: float = 1.0) -> None:
    """Run ffmpeg with real progress. `offset`/`span` map this pass onto a share of the bar (two-pass)."""
    cmd = [exe("ffmpeg"), "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats",
           "-protocol_whitelist", "file,pipe", "-format_whitelist", DEMUXERS, *args]
    total = max(total_s, 0.001)
    ctx.progress(stage=stage, force=True)

    def on_line(line: bytes) -> None:
        if line.startswith(b"progress=end"):
            ctx.progress(round((offset + span) * 100, 1), 100, stage=stage, force=True)
            return
        if line.startswith(b"out_time_us=") or line.startswith(b"out_time_ms="):
            try:
                us = int(line.split(b"=", 1)[1])
            except ValueError:
                return
            done = min(1.0, us / 1_000_000 / total)
            ctx.progress(round((offset + done * span) * 100, 1), 100, stage=stage)

    res = ctx.run(cmd, on_line=on_line, check=False)
    if res.returncode != 0:
        import sys

        print("ffmpeg failed:", res.stderr_tail[-1500:], file=sys.stderr)  # surfaces in worker logs
        tail = res.stderr_tail.lower()
        if "invalid data" in tail or "moov atom not found" in tail or "end of file" in tail:
            raise ConversionError("corrupt_input", "This media file is damaged or truncated.")
        raise ConversionError("engine_error", "FFmpeg couldn't convert this file with these settings.")


def trim_args(start: float | None, end: float | None) -> tuple[list[str], list[str]]:
    """(input-side args, output-side args) for trimming. Seeking before -i is fast and frame-accurate when re-encoding."""
    pre, post = [], []
    if start:
        pre += ["-ss", f"{start:.3f}"]
    if end:
        post += ["-t", f"{max(0.001, end - (start or 0)):.3f}"]
    return pre, post


def trimmed_duration(total: float, start: float | None, end: float | None) -> float:
    s = start or 0
    e = min(end, total) if end else total
    if total and s >= total:
        raise ConversionError("invalid_option", f"The start time is after the end of the file ({total:.1f} s long).")
    if end is not None and end <= s:
        raise ConversionError("invalid_option", "The end time must be after the start time.")
    return max(0.001, e - s)
