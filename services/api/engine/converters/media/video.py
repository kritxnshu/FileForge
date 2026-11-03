"""Video conversion and tools with FFmpeg."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ... import ffmpeg
from ...context import ConversionError, Ctx
from ...registry import Operation, Options, register, ui
from .audio import codec_args as audio_codec_args

VIDEO = ("mp4", "mov", "mkv", "webm", "avi", "flv", "wmv", "3gp")
AUDIO_OUT = ("mp3", "aac", "wav", "flac", "ogg", "m4a", "opus")

# codecs each container accepts as-is (for the stream-copy fast path)
COPY_OK = {
    "mp4": ({"h264", "hevc", "mpeg4", "av1"}, {"aac", "mp3", "ac3", "alac"}),
    "mov": ({"h264", "hevc", "mpeg4", "prores", "mjpeg"}, {"aac", "mp3", "alac", "pcm_s16le"}),
    "mkv": ({"h264", "hevc", "vp8", "vp9", "av1", "mpeg4", "mpeg2video"}, {"aac", "mp3", "opus", "vorbis", "flac", "ac3", "pcm_s16le"}),
    "webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis"}),
    "avi": ({"mpeg4", "h264", "mjpeg", "msmpeg4v3"}, {"mp3", "ac3", "pcm_s16le"}),
    "flv": ({"h264", "flv1"}, {"aac", "mp3"}),
    "wmv": ({"wmv1", "wmv2"}, {"wmav1", "wmav2"}),
    "3gp": ({"h264", "h263", "mpeg4"}, {"aac", "amr_nb"}),
}
MUXER = {"mp4": "mp4", "mov": "mov", "mkv": "matroska", "webm": "webm", "avi": "avi", "flv": "flv", "wmv": "asf", "3gp": "3gp"}
CRF = {"high": 18, "medium": 23, "low": 28}
VP9_CRF = {"high": 24, "medium": 32, "low": 40}


def video_codec(target: str, quality: str, bitrate_k: int | None) -> list[str]:
    if target == "webm":
        a = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4"]
        return a + (["-b:v", f"{bitrate_k}k"] if bitrate_k else ["-crf", str(VP9_CRF[quality]), "-b:v", "0"])
    if target == "wmv":
        return ["-c:v", "wmv2", "-b:v", f"{bitrate_k or {'high': 4000, 'medium': 2000, 'low': 900}[quality]}k"]
    if target == "avi":
        return ["-c:v", "mpeg4", "-vtag", "xvid", "-q:v", str({"high": 2, "medium": 4, "low": 7}[quality])] if not bitrate_k else \
            ["-c:v", "mpeg4", "-vtag", "xvid", "-b:v", f"{bitrate_k}k"]
    a = ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    if target == "3gp":
        a += ["-profile:v", "baseline", "-level", "3.0"]
    return a + (["-b:v", f"{bitrate_k}k"] if bitrate_k else ["-crf", str(CRF[quality])])


def audio_codec(target: str, kbps: int = 128) -> list[str]:
    return {
        "webm": ["-c:a", "libopus", "-b:a", f"{kbps}k", "-ar", "48000"],
        "wmv": ["-c:a", "wmav2", "-b:a", f"{kbps}k"],
        "avi": ["-c:a", "libmp3lame", "-b:a", f"{kbps}k"],
    }.get(target, ["-c:a", "aac", "-b:a", f"{kbps}k"])


class VideoOptions(Options):
    quality: Literal["high", "medium", "low"] = Field("medium", title="Quality",
                                                      description="Lower quality makes smaller files.")
    resolution: Literal["keep", "2160", "1440", "1080", "720", "480", "360"] = Field(
        "keep", title="Resolution", description="Output height in pixels; width follows the aspect ratio.")
    fps: Literal["keep", "60", "30", "25", "24", "15"] = Field("keep", title="Frame rate", json_schema_extra=ui(advanced=True))
    start: float | None = Field(None, ge=0, title="Trim start", json_schema_extra=ui(unit="s"))
    end: float | None = Field(None, gt=0, title="Trim end", json_schema_extra=ui(unit="s"))
    target_size_mb: float | None = Field(None, gt=0.1, le=4000, title="Target size (optional)",
                                         description="Aim for about this file size using two-pass encoding.",
                                         json_schema_extra=ui(unit="MB", advanced=True))
    mute: bool = Field(False, title="Remove audio", json_schema_extra=ui(advanced=True))
    allow_copy: bool = Field(True, title="Fast lossless remux when possible",
                             description="If the video already uses codecs the new format supports, copy them instead of re-encoding.",
                             json_schema_extra=ui(advanced=True))

    @model_validator(mode="after")
    def _range(self):
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("end must be after start")
        return self


def _filters(o: VideoOptions, src_h: int | None) -> list[str]:
    vf = []
    if o.resolution != "keep":
        h = int(o.resolution)
        if src_h and h > src_h:
            h = src_h
        vf.append(f"scale=-2:{h}")
    if o.fps != "keep":
        vf.append(f"fps={o.fps}")
    return vf


def _video(ctx: Ctx, target: str) -> None:
    o: VideoOptions = ctx.options  # type: ignore[assignment]
    info = ffmpeg.probe(ctx, ctx.input.path)
    vs, as_ = ffmpeg.streams(info, "video"), ffmpeg.streams(info, "audio")
    if not vs:
        raise ConversionError("invalid_input", "This file has no video track.")
    total = ffmpeg.duration(info)
    span = ffmpeg.trimmed_duration(total, o.start, o.end)
    pre, post = ffmpeg.trim_args(o.start, o.end)
    out = ctx.default_out(target)
    vcodec, acodec = vs[0].get("codec_name"), (as_[0].get("codec_name") if as_ else None)
    ok_v, ok_a = COPY_OK[target]
    plain = o.resolution == "keep" and o.fps == "keep" and not o.target_size_mb and o.start is None and o.end is None
    if o.allow_copy and plain and vcodec in ok_v and (acodec is None or acodec in ok_a or o.mute):
        args = ["-i", str(ctx.input.path), "-map", "0:v:0", *([] if o.mute or not as_ else ["-map", "0:a:0"]),
                "-c", "copy", "-map_metadata", "0", "-f", MUXER[target]]
        if target in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
        ffmpeg.run(ctx, [*args, str(out)], total_s=span, stage="Remuxing (no re-encoding)")
        ctx.notice(f"Copied the existing {vcodec.upper()}{'/' + acodec.upper() if acodec and not o.mute else ''} streams "
                   "into the new container without re-encoding: fast and lossless.")
        ctx.info["remuxed"] = True
        ffmpeg.verify_duration(ctx, out, span)
        ctx.add_output(out, target)
        return
    vf = _filters(o, vs[0].get("height"))
    if target in ("mp4", "mov", "mkv", "flv", "3gp"):
        vf.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")  # H.264 4:2:0 needs even dimensions
    if target == "3gp" and o.resolution == "keep":
        vf.insert(0, "scale='min(iw,352)':-2")
    audio = [] if o.mute or not as_ else ["-map", "0:a:0", *audio_codec(target)]
    base = [*pre, "-i", str(ctx.input.path), "-map", "0:v:0", *post, *(["-vf", ",".join(vf)] if vf else [])]
    if o.target_size_mb:
        abits = 0 if not audio else 128
        vbits = int(o.target_size_mb * 8192 / span) - abits
        if vbits < 50:
            raise ConversionError("invalid_option", f"{o.target_size_mb} MB is too small for {span:.0f} seconds of video. Try a larger size.")
        passlog = str(ctx.work_dir / "passlog")
        codec = video_codec(target, o.quality, vbits)
        two = target not in ("avi", "wmv")
        if two:
            ffmpeg.run(ctx, [*base, *codec, "-pass", "1", "-passlogfile", passlog, "-an", "-f", MUXER[target], "/dev/null"],
                       total_s=span, stage="Analyzing (pass 1 of 2)", offset=0, span=0.5)
            ffmpeg.run(ctx, [*base, *codec, "-pass", "2", "-passlogfile", passlog, *audio, "-f", MUXER[target], str(out)],
                       total_s=span, stage="Encoding (pass 2 of 2)", offset=0.5, span=0.5)
        else:
            ffmpeg.run(ctx, [*base, *codec, *audio, "-f", MUXER[target], str(out)], total_s=span, stage="Encoding video")
        got = out.stat().st_size / 1048576
        ctx.notice(f"Aimed for {o.target_size_mb:g} MB; the result is {got:.1f} MB.")
    else:
        args = [*base, *video_codec(target, o.quality, None), *audio, "-map_metadata", "0", "-f", MUXER[target]]
        if target in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
        ffmpeg.run(ctx, [*args, str(out)], total_s=span, stage="Encoding video")
    ffmpeg.verify_duration(ctx, out, span)
    ctx.add_output(out, target)


def video_convert(ctx: Ctx) -> None:
    _video(ctx, ctx.target)


def video_edit(ctx: Ctx) -> None:
    _video(ctx, ctx.input.format)


register(Operation(
    id="video.convert", category="video", label="Convert video",
    description="Convert between video formats. When the codecs already fit, streams are copied without re-encoding.",
    inputs=VIDEO, outputs=VIDEO, cardinality="one_to_one", options=VideoOptions, run=video_convert,
    engines=("ffmpeg", "ffprobe"), resource_class="heavy", memory_mb=None,
    pair_limitations={**{(s, "wmv"): ("WMV uses the older WMV2 codec, so files are larger for the same quality.",) for s in VIDEO if s != "wmv"},
                      **{(s, "3gp"): ("3GP is for old phones: output is limited to 352 px wide by default.",) for s in VIDEO if s != "3gp"}},
    keywords=("mp4 converter", "movie", "clip"),
))

register(Operation(
    id="video.edit", category="video", label="Trim / compress video",
    description="Trim, resize, change the frame rate or quality, or compress to a target size, keeping the format.",
    inputs=VIDEO, outputs=(), cardinality="transform", options=VideoOptions, run=video_edit,
    engines=("ffmpeg", "ffprobe"), resource_class="heavy", memory_mb=None, slug="edit-video",
    keywords=("cut", "trim", "compress", "resize", "smaller"),
))


# ---------------------------------------------------------------------------


class GifOptions(Options):
    fps: int = Field(12, ge=1, le=30, title="Frames per second")
    width: int = Field(480, ge=16, le=800, title="Width", json_schema_extra=ui(unit="px"))
    start: float = Field(0, ge=0, title="Start at", json_schema_extra=ui(unit="s"))
    duration: float = Field(10, gt=0, le=30, title="Length", description="At most 30 seconds.", json_schema_extra=ui(unit="s"))


def to_gif(ctx: Ctx) -> None:
    o: GifOptions = ctx.options  # type: ignore[assignment]
    info = ffmpeg.probe(ctx, ctx.input.path)
    if not ffmpeg.streams(info, "video"):
        raise ConversionError("invalid_input", "This file has no video track.")
    total = ffmpeg.duration(info)
    span = ffmpeg.trimmed_duration(total, o.start, o.start + o.duration)
    palette = ctx.work_dir / "palette.png"
    scale = f"fps={o.fps},scale='min({o.width},iw)':-1:flags=lanczos"
    common = [*(["-ss", f"{o.start:.3f}"] if o.start else []), "-t", f"{span:.3f}", "-i", str(ctx.input.path)]
    ffmpeg.run(ctx, [*common, "-vf", f"{scale},palettegen=stats_mode=diff", "-update", "1", "-frames:v", "1", str(palette)],
               total_s=span, stage="Building palette (pass 1 of 2)", offset=0, span=0.4)
    out = ctx.default_out("gif")
    ffmpeg.run(ctx, [*common, "-i", str(palette), "-lavfi", f"{scale}[x];[x][1:v]paletteuse=dither=sierra2_4a", "-loop", "0", str(out)],
               total_s=span, stage="Rendering GIF (pass 2 of 2)", offset=0.4, span=0.6)
    if total > o.start + o.duration:
        ctx.notice(f"Made a {span:g}-second GIF starting at {o.start:g} s (GIFs are limited to {o.duration:g} s here).")
    ctx.add_output(out, "gif")


register(Operation(
    id="video.to_gif", category="video", label="Video to GIF",
    description="Make an animated GIF from part of a video, with a palette optimized for the clip.",
    inputs=VIDEO, outputs=("gif",), cardinality="one_to_one", options=GifOptions, run=to_gif,
    engines=("ffmpeg", "ffprobe"), resource_class="heavy", memory_mb=None,
    limitations=("GIFs are limited to 30 seconds, 30 fps and 800 px wide.",), keywords=("animated gif", "meme"),
))


class FromGifOptions(Options):
    quality: Literal["high", "medium", "low"] = Field("high", title="Quality")


def from_gif(ctx: Ctx) -> None:
    o: FromGifOptions = ctx.options  # type: ignore[assignment]
    info = ffmpeg.probe(ctx, ctx.input.path)
    out = ctx.default_out()
    vf = "scale=trunc(iw/2)*2:trunc(ih/2)*2" if ctx.target == "mp4" else "scale=iw:ih"
    ffmpeg.run(ctx, ["-i", str(ctx.input.path), "-vf", vf, "-an", *video_codec(ctx.target, o.quality, None),
                     *(["-movflags", "+faststart"] if ctx.target == "mp4" else []), "-f", MUXER[ctx.target], str(out)],
               total_s=ffmpeg.duration(info) or 1, stage="Encoding video")
    ctx.add_output(out)


register(Operation(
    id="video.from_gif", category="video", label="GIF to video",
    description="Turn an animated GIF into a much smaller MP4 or WebM video.", inputs=("gif",), outputs=("mp4", "webm"),
    cardinality="one_to_one", options=FromGifOptions, run=from_gif, engines=("ffmpeg", "ffprobe"), resource_class="heavy",
    memory_mb=None, keywords=("gif to mp4",),
))


class ExtractAudioOptions(Options):
    bitrate: Literal[96, 128, 160, 192, 256, 320] | None = Field(None, title="Bitrate", json_schema_extra=ui(unit="kbps", targets=("mp3", "aac", "m4a", "ogg", "opus")))
    start: float | None = Field(None, ge=0, title="Trim start", json_schema_extra=ui(unit="s", advanced=True))
    end: float | None = Field(None, gt=0, title="Trim end", json_schema_extra=ui(unit="s", advanced=True))


def extract_audio(ctx: Ctx) -> None:
    o: ExtractAudioOptions = ctx.options  # type: ignore[assignment]
    info = ffmpeg.probe(ctx, ctx.input.path)
    if not ffmpeg.streams(info, "audio"):
        raise ConversionError("no_audio", "This video has no audio track to extract.")
    span = ffmpeg.trimmed_duration(ffmpeg.duration(info), o.start, o.end)
    pre, post = ffmpeg.trim_args(o.start, o.end)
    out = ctx.default_out()
    extra = ["-ar", "48000"] if ctx.target == "opus" else []
    ffmpeg.run(ctx, [*pre, "-i", str(ctx.input.path), "-map", "0:a:0", "-vn", *post, *extra, "-map_metadata", "0",
                     *audio_codec_args(ctx.target, o.bitrate), str(out)], total_s=span, stage="Extracting audio")
    ffmpeg.verify_duration(ctx, out, span)
    ctx.add_output(out)


register(Operation(
    id="video.extract_audio", category="video", label="Extract audio",
    description="Save the soundtrack of a video as an audio file.", inputs=VIDEO, outputs=AUDIO_OUT, cardinality="one_to_one",
    options=ExtractAudioOptions, run=extract_audio, engines=("ffmpeg", "ffprobe"), resource_class="heavy", memory_mb=None,
    keywords=("mp4 to mp3", "soundtrack", "rip audio"),
))


class ThumbOptions(Options):
    at: float = Field(1.0, ge=0, title="Time", description="Seconds from the beginning.", json_schema_extra=ui(unit="s"))
    width: int | None = Field(None, ge=16, le=7680, title="Width (optional)", json_schema_extra=ui(unit="px"))


def thumbnail(ctx: Ctx) -> None:
    o: ThumbOptions = ctx.options  # type: ignore[assignment]
    info = ffmpeg.probe(ctx, ctx.input.path)
    total = ffmpeg.duration(info)
    if total and o.at >= total:
        raise ConversionError("invalid_option", f"The video is only {total:.1f} seconds long. Pick an earlier time.")
    out = ctx.default_out()
    vf = [f"scale={o.width}:-2"] if o.width else []
    ffmpeg.run(ctx, ["-ss", f"{o.at:.3f}", "-i", str(ctx.input.path), "-frames:v", "1", *(["-vf", ",".join(vf)] if vf else []),
                     *(["-q:v", "2"] if ctx.target == "jpg" else []), "-update", "1", str(out)], total_s=1, stage="Grabbing frame")
    ctx.add_output(out)


register(Operation(
    id="video.thumbnail", category="video", label="Video frame to image",
    description="Save a single frame of a video as a PNG or JPG at the time you choose.", inputs=VIDEO, outputs=("png", "jpg"),
    cardinality="one_to_one", options=ThumbOptions, run=thumbnail, engines=("ffmpeg", "ffprobe"), resource_class="heavy",
    memory_mb=None, keywords=("screenshot", "still", "poster frame"),
))
