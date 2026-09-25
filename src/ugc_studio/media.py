"""Low-level media tools: probing, frame I/O, conforming clips, color matching, optical-flow frame repair."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import av
import cv2
import imageio_ffmpeg
import numpy as np

log = logging.getLogger(__name__)
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def ffmpeg(args: list[str], quiet: bool = True) -> None:
    cmd = [FFMPEG, "-hide_banner", "-y", *(["-loglevel", "error"] if quiet else []), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-3000:]}")


def probe(path: str | Path) -> dict:
    with av.open(str(path)) as c:
        v = c.streams.video[0] if c.streams.video else None
        a = c.streams.audio[0] if c.streams.audio else None
        frames = v.frames if v and v.frames else (sum(1 for _ in c.decode(video=0)) if v else 0)
        return {
            "frames": frames,
            "fps": float(v.average_rate) if v else 0.0,
            "width": v.codec_context.width if v else 0,
            "height": v.codec_context.height if v else 0,
            "seconds": frames / float(v.average_rate) if v else float(c.duration or 0) / 1e6,
            "audio": bool(a),
            "audio_rate": a.rate if a else 0,
        }


COLOR_ARGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


def read_frames(path: str | Path) -> list[np.ndarray]:
    """Decode to RGB with an explicit BT.709 limited-range matrix (the same one `write_video_with_audio` uses),
    so a decode -> edit -> encode round trip does not shift colors."""
    info = probe(path)
    w, h = info["width"], info["height"]
    proc = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-vf",
                           "scale=in_color_matrix=bt709:in_range=tv:flags=accurate_rnd+full_chroma_int",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"cannot decode {path}: {proc.stderr[-500:]!r}")
    arr = np.frombuffer(proc.stdout, np.uint8)
    n = arr.size // (w * h * 3)
    return [f.copy() for f in arr[: n * w * h * 3].reshape(n, h, w, 3)]


def extract_frame(video: str | Path, out_png: str | Path, which: str | int = "last") -> Path:
    frame = None
    with av.open(str(video)) as c:
        for i, f in enumerate(c.decode(video=0)):
            frame = f
            if which == "first" or (isinstance(which, int) and i == which):
                break
    if frame is None:
        raise ValueError(f"No video frames in {video}")
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    frame.to_image().save(out_png)
    return out_png


# ---------------------------------------------------------------- color matching (Reinhard in Lab -> 3D LUT)
def _lab_stats(frames: list[np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    px = np.concatenate([cv2.cvtColor(f, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32) for f in frames])
    return px.mean(0), px.std(0) + 1e-3


def sample_frames(path: str | Path, n: int = 8) -> list[np.ndarray]:
    frames = read_frames(path)
    idx = np.linspace(0, len(frames) - 1, min(n, len(frames))).round().astype(int)
    return [cv2.resize(frames[i], (320, int(320 * frames[i].shape[0] / frames[i].shape[1]))) for i in idx]


def color_match_lut(src: list[np.ndarray], ref: list[np.ndarray], out_cube: str | Path, strength: float = 0.7,
                    size: int = 33) -> Path:
    """3D LUT moving src's Lab statistics toward ref's. `strength` < 1 keeps some of the shot's own mood."""
    ms, ss = _lab_stats(src)
    mr, sr = _lab_stats(ref)
    scale = 1 + strength * (sr / ss - 1)
    scale = np.clip(scale, 0.75, 1.33)  # never crush or blow out a shot
    grid = np.linspace(0, 255, size, dtype=np.float32)
    b, g, r = np.meshgrid(grid, grid, grid, indexing="ij")  # .cube order: red varies fastest
    rgb = np.stack([r, g, b], -1).reshape(-1, 1, 3).astype(np.uint8)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float32)
    lab = (lab - ms) * scale + ms + strength * (mr - ms)
    out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8).reshape(-1, 1, 3), cv2.COLOR_LAB2RGB).reshape(-1, 3)
    out = out.astype(np.float32) / 255.0
    lines = [f"LUT_3D_SIZE {size}"] + [f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}" for v in out]
    Path(out_cube).write_text("\n".join(lines) + "\n")
    return Path(out_cube)


# ---------------------------------------------------------------- conform
def conform(src: str | Path, out: str | Path, *, fps: int, width: int, height: int, start: float = 0.0,
            duration: float | None = None, stretch: float = 1.0, lut: str | Path | None = None,
            drop_first: int = 0, keep_audio: bool = True) -> Path:
    """Normalize a clip to the edit's canvas: exact fps, cover-crop to width x height, optional in-point, speed
    change (slow-down for voice-over), color LUT, and 48 kHz stereo audio (silence if none). Output: all-intra
    high-quality intermediate so the edit is frame-accurate and fast to redo."""
    info = probe(src)
    vf = [f"trim=start_frame={drop_first}", "setpts=PTS-STARTPTS"]
    if start > 0:
        vf += [f"trim=start={start:.4f}", "setpts=PTS-STARTPTS"]
    if stretch != 1.0:
        vf += [f"setpts={stretch:.5f}*PTS"]
    vf += [f"fps={fps}", f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
           f"crop={width}:{height}"]
    if lut:
        vf += [f"lut3d=file='{Path(lut).as_posix()}':interp=tetrahedral"]
    if duration:
        vf += [f"trim=duration={duration:.4f}", "setpts=PTS-STARTPTS"]
    vf += ["format=yuv420p", "setsar=1"]
    a_start = start + drop_first / (info["fps"] or fps)
    if info["audio"] and keep_audio:
        af = [f"atrim=start={a_start:.4f}", "asetpts=PTS-STARTPTS"]
        if stretch != 1.0:
            af += [f"atempo={1 / stretch:.5f}"]
        af += ["aresample=48000", "aformat=channel_layouts=stereo"]
        if duration:
            af += ["apad", f"atrim=duration={duration:.4f}"]
        audio_args = ["-af", ",".join(af)]
        inputs = ["-i", str(src)]
    else:
        dur = duration or (info["seconds"] * stretch)
        inputs = ["-i", str(src), "-f", "lavfi", "-t", f"{dur:.4f}", "-i", "anullsrc=r=48000:cl=stereo"]
        audio_args = ["-map", "0:v:0", "-map", "1:a:0"]
    ffmpeg([*inputs, "-vf", ",".join(vf), *audio_args, "-c:v", "libx264", "-preset", "medium", "-crf", "12",
            "-g", "1", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out)])
    return Path(out)


# ---------------------------------------------------------------- frame repair
def interpolate_frames(frames: list[np.ndarray], a: int, b: int) -> None:
    """Replace frames a..b (inclusive) in place by motion-compensated interpolation between a-1 and b+1."""
    lo, hi = a - 1, b + 1
    if lo < 0 or hi >= len(frames):
        # Range touches an edge: hold the nearest good frame instead.
        good = frames[hi] if lo < 0 else frames[lo]
        for i in range(a, b + 1):
            frames[i] = good.copy()
        return
    f0, f1 = frames[lo], frames[hi]
    g0, g1 = cv2.cvtColor(f0, cv2.COLOR_RGB2GRAY), cv2.cvtColor(f1, cv2.COLOR_RGB2GRAY)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    flow01, flow10 = dis.calc(g0, g1, None), dis.calc(g1, g0, None)
    h, w = g0.shape
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    n = hi - lo
    for i in range(a, b + 1):
        t = (i - lo) / n
        w0 = cv2.remap(f0, gx - t * flow01[..., 0], gy - t * flow01[..., 1], cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REPLICATE)
        w1 = cv2.remap(f1, gx - (1 - t) * flow10[..., 0], gy - (1 - t) * flow10[..., 1], cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REPLICATE)
        frames[i] = ((1 - t) * w0.astype(np.float32) + t * w1.astype(np.float32)).clip(0, 255).astype(np.uint8)


def write_video_with_audio(frames: list[np.ndarray], fps: float, audio_src: str | Path | None, out: str | Path) -> Path:
    """Encode RGB frames losslessly-ish, copying the audio track from audio_src unchanged."""
    h, w = frames[0].shape[:2]
    tmp = Path(out).with_suffix(".video.mkv")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-", "-vf",
           "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p",
           "-c:v", "libx264", "-crf", "10", "-preset", "medium", *COLOR_ARGS, str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for f in frames:
            proc.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
    finally:
        proc.stdin.close()
        err = proc.stderr.read()
        if proc.wait() != 0:
            raise RuntimeError(f"encode failed: {err[-500:]!r}")
    if audio_src and probe(audio_src)["audio"]:
        # The video defines the length: pad/trim the audio to it (never -shortest, which drops video frames).
        dur = len(frames) / fps
        ffmpeg(["-i", str(tmp), "-i", str(audio_src), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-af", f"apad,atrim=duration={dur:.5f}", "-c:a", "aac", "-b:a", "256k", str(out)])
    else:
        ffmpeg(["-i", str(tmp), "-c:v", "copy", str(out)])
    tmp.unlink(missing_ok=True)
    return Path(out)
