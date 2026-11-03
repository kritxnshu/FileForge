"""Audio conversion and editing with FFmpeg."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ... import ffmpeg
from ...context import ConversionError, Ctx
from ...registry import Operation, Options, register, ui

AUDIO = ("mp3", "wav", "aac", "flac", "ogg", "m4a", "opus", "wma")
LOSSY = ("mp3", "aac", "ogg", "m4a", "opus", "wma")
COVER_TARGETS = {"mp3", "m4a", "flac"}
TAGS = ("title", "artist", "album", "date", "genre", "track")


def codec_args(target: str, bitrate: int | None) -> list[str]:
    br = f"{bitrate or {'opus': 128, 'ogg': 192}.get(target, 192)}k"
    if target == "mp3":
        return ["-c:a", "libmp3lame", "-b:a", br, "-f", "mp3"]
    if target == "aac":
        return ["-c:a", "aac", "-b:a", br, "-f", "adts"]
    if target == "m4a":
        return ["-c:a", "aac", "-b:a", br, "-f", "ipod", "-movflags", "+faststart"]
    if target == "flac":
        return ["-c:a", "flac", "-f", "flac"]
    if target == "wav":
        return ["-c:a", "pcm_s16le", "-f", "wav"]
    if target == "opus":
        return ["-c:a", "libopus", "-b:a", br, "-f", "ogg"]
    if target == "ogg":
        if "libvorbis" in ffmpeg.encoders():
            return ["-c:a", "libvorbis", "-b:a", br, "-f", "ogg"]
        # FFmpeg's built-in Vorbis encoder is experimental and stereo-only
        return ["-c:a", "vorbis", "-strict", "-2", "-ac", "2", "-b:a", br, "-f", "ogg"]
    if target == "wma":
        return ["-c:a", "wmav2", "-b:a", br, "-f", "asf"]
    raise ConversionError("unsupported", f"Can't write {target}.")


class AudioOptions(Options):
    bitrate: Literal[64, 96, 128, 160, 192, 256, 320] | None = Field(
        None, title="Bitrate", description="Leave empty for a sensible default (192 kbps; 128 kbps for Opus).",
        json_schema_extra=ui(unit="kbps", targets=LOSSY))
    sample_rate: Literal[8000, 16000, 22050, 24000, 32000, 44100, 48000] | None = Field(
        None, title="Sample rate", description="Leave empty to keep the original.", json_schema_extra=ui(unit="Hz", advanced=True))
    channels: Literal["keep", "mono", "stereo"] = Field("keep", title="Channels", json_schema_extra=ui(advanced=True))
    start: float | None = Field(None, ge=0, title="Trim start", description="Seconds from the beginning.", json_schema_extra=ui(unit="s"))
    end: float | None = Field(None, gt=0, title="Trim end", description="Seconds from the beginning.", json_schema_extra=ui(unit="s"))
    normalize: bool = Field(False, title="Normalize loudness", description="Even out volume to a broadcast standard (EBU R128, −16 LUFS).")
    keep_metadata: bool = Field(True, title="Keep tags and cover art", json_schema_extra=ui(advanced=True))

    @model_validator(mode="after")
    def _range(self):
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("end must be after start")
        return self


def _audio(ctx: Ctx, target: str) -> None:
    o: AudioOptions = ctx.options  # type: ignore[assignment]
    info = ffmpeg.probe(ctx, ctx.input.path)
    if not ffmpeg.streams(info, "audio"):
        raise ConversionError("invalid_input", "This file has no audio track.")
    total = ffmpeg.duration(info)
    span = ffmpeg.trimmed_duration(total, o.start, o.end)
    pre, post = ffmpeg.trim_args(o.start, o.end)
    args = [*pre, "-i", str(ctx.input.path), "-map", "0:a:0"]
    has_cover = bool([s for s in info["streams"] if s.get("disposition", {}).get("attached_pic")])
    keep_cover = o.keep_metadata and has_cover and target in COVER_TARGETS
    if keep_cover:
        args += ["-map", "0:v:0", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    args += post
    filters = []
    if o.normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11,asetnsamples=n=4096:p=0")  # loudnorm emits huge frames
    if filters:
        args += ["-af", ",".join(filters)]
    if o.sample_rate:
        args += ["-ar", str(o.sample_rate)]
    elif target == "opus":
        args += ["-ar", "48000"]
    elif o.normalize:
        args += ["-ar", "48000" if target != "mp3" else "44100"]
    if o.channels != "keep":
        args += ["-ac", "1" if o.channels == "mono" else "2"]
    args += ["-map_metadata", "0" if o.keep_metadata else "-1"]
    if target == "mp3":
        args += ["-id3v2_version", "3"]
    if target == "mp3" and o.sample_rate and o.sample_rate < 32000 and (o.bitrate or 192) > 160:
        ctx.notice(f"MP3 at {o.sample_rate} Hz is limited to 160 kbps by the format, so the bitrate was capped.")
    args += codec_args(target, o.bitrate)
    out = ctx.default_out(target)
    ffmpeg.run(ctx, [*args, str(out)], total_s=span, stage="Encoding audio")
    ffmpeg.verify_duration(ctx, out, span)
    # Report what metadata survived (tag mapping differs between containers).
    if o.keep_metadata:
        before = {k.lower(): v for k, v in (info.get("format", {}).get("tags") or {}).items()}
        before.update({k.lower(): v for s in ffmpeg.streams(info, "audio") for k, v in (s.get("tags") or {}).items()})
        after_info = ffmpeg.probe(ctx, out)
        after = {k.lower(): v for k, v in (after_info.get("format", {}).get("tags") or {}).items()}
        after.update({k.lower(): v for s in ffmpeg.streams(after_info, "audio") for k, v in (s.get("tags") or {}).items()})
        had = [t for t in TAGS if t in before]
        kept = [t for t in had if t in after]
        lost = [t for t in had if t not in after]
        if has_cover:
            (kept if keep_cover else lost).append("cover art")
        if kept:
            ctx.notice("Kept: " + ", ".join(kept) + ".")
        if lost:
            ctx.warn(f"{target.upper()} couldn't keep: " + ", ".join(lost) + ".")
        ctx.info["metadata_kept"] = kept
    if target == "ogg" and "libvorbis" not in ffmpeg.encoders():
        ctx.notice("Encoded with FFmpeg's built-in Vorbis encoder (stereo).")
    ctx.add_output(out, target)


def audio_convert(ctx: Ctx) -> None:
    _audio(ctx, ctx.target)


def audio_edit(ctx: Ctx) -> None:
    _audio(ctx, ctx.input.format)


_vorbis_partial = "libvorbis" not in ffmpeg.encoders() if ffmpeg.encoders() else False

register(Operation(
    id="audio.convert", category="audio", label="Convert audio",
    description="Convert between audio formats, with optional bitrate, sample rate, channels, trimming and loudness normalization.",
    inputs=AUDIO, outputs=AUDIO, cardinality="one_to_one", options=AudioOptions, run=audio_convert,
    engines=("ffmpeg", "ffprobe"), resource_class="heavy", memory_mb=None,
    pair_support={(s, "ogg"): "partial" for s in AUDIO if s != "ogg"} if _vorbis_partial else {},
    pair_limitations={
        **({(s, "ogg"): ("This server uses FFmpeg's built-in Vorbis encoder: stereo only, lower quality than libvorbis.",)
            for s in AUDIO if s != "ogg"} if _vorbis_partial else {}),
        **{(s, t): ("Tags are carried over where the format supports them; cover art can't be stored in this format.",)
           for s in AUDIO for t in ("wav", "aac", "ogg", "opus", "wma") if s != t},
    },
    keywords=("mp3 converter", "music", "sound"),
))

register(Operation(
    id="audio.edit", category="audio", label="Trim / adjust audio",
    description="Trim, normalize loudness, or change the bitrate, sample rate or channels without changing the format.",
    inputs=AUDIO, outputs=(), cardinality="transform", options=AudioOptions, run=audio_edit,
    engines=("ffmpeg", "ffprobe"), resource_class="heavy", memory_mb=None, slug="edit-audio",
    keywords=("cut", "trim", "normalize", "volume"),
))
