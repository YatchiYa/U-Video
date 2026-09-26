"""What every generation backend implements, plus the shared HTTP helpers for cloud APIs.

A backend only *generates*. Everything around it stays the same whatever the provider: keyframe best-of-N and
screen checks, speech/pronunciation/identity gates and automatic re-takes, conform, color match, edit and QA.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    """A provider call failed or is misconfigured; the message says what to do."""


@dataclass(frozen=True)
class ImageCondition:
    path: str
    frame_idx: int = 0  # 0 = first frame; num_frames-1 (or larger, clamped) = land exactly on this image at the end
    strength: float = 1.0


def need_key(var: str, provider: str) -> str:
    """The API key from the environment/.env, or a clear error naming the variable."""
    value = os.environ.get(var, "").strip()
    if not value:
        raise ProviderError(f"{provider} needs {var}: add `{var}=...` to .env (see .env.example).")
    return value


# ------------------------------------------------------------------ interfaces
class ImageBackend:
    """Text-to-image, optionally guided by reference images (identity, product, previous frame)."""

    name = "image"
    supports_references = True

    def generate(self, prompt: str, width: int, height: int, seed: int, references: list[str | Path] | None = None,
                 out_path: str | Path | None = None):  # -> PIL.Image.Image
        raise NotImplementedError

    def close(self) -> None:
        pass


class VideoBackend:
    """Image/text-to-video. `images` are first/last frame conditions (frame_idx 0 / last)."""

    name = "video"
    makes_audio = False        # native sound (ambience, speech); False -> the clip gets a silent track
    supports_end_frame = False
    supports_retake = False    # regenerate a time window of an existing clip (`ugc fix --retake`)

    def render(self, prompt: str, out_path: str | Path, width: int, height: int, num_frames: int, seed: int,
               images: list[ImageCondition] | None = None, fps: int = 24) -> Path:
        raise NotImplementedError

    def render_long(self, prompt: str, out_path: str | Path, width: int, height: int, segments: list[int],
                    seed: int, images: list[ImageCondition], fps: int, workdir: Path) -> Path:
        """Shot longer than one local generation. Cloud models make longer clips in one call: the segments are
        summed back (each continuation segment overlaps the previous one by one frame)."""
        total = sum(segments) - (len(segments) - 1)
        return self.render(prompt, out_path, width, height, total, seed, images, fps)

    def close(self) -> None:
        pass


class VoiceBackend:
    """Narration: writes `<out_dir>/<id>.wav` for every line {"id", "text", "seed"}."""

    name = "voice"

    def synthesize(self, lines: list[dict], out_dir: Path, language: str, voice) -> None:
        raise NotImplementedError


class MusicBackend:
    """Instrumental bed: writes `<out_dir>/cand<k>.wav` candidates (the engine scores and keeps the best)."""

    name = "music"

    def generate(self, caption: str, seconds: float, bpm: int | None, seed: int, candidates: int, out_dir: Path) -> None:
        raise NotImplementedError


# ------------------------------------------------------------------ HTTP helpers (cloud providers)
def client(timeout: float = 120.0, transport=None):
    """One place to build HTTP clients; tests inject an httpx.MockTransport."""
    import httpx

    return httpx.Client(timeout=timeout, transport=transport or _TRANSPORT, follow_redirects=True)


_TRANSPORT = None  # tests set providers.base._TRANSPORT = httpx.MockTransport(...)


def check(resp, provider: str):
    """Raise a readable ProviderError for any non-2xx answer (status + the provider's own message)."""
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:  # noqa: BLE001 - non-JSON error pages
            detail = resp.text[:500]
        raise ProviderError(f"{provider} error {resp.status_code}: {detail}")
    return resp


def poll(fetch: Callable[[], dict], done: Callable[[dict], bool], failed: Callable[[dict], str | None],
         provider: str, timeout: float = 900.0, every: float = 5.0) -> dict:
    """Poll an async generation task until done / failed / timeout."""
    t0 = time.time()
    while True:
        data = fetch()
        err = failed(data)
        if err:
            raise ProviderError(f"{provider} generation failed: {err}")
        if done(data):
            return data
        if time.time() - t0 > timeout:
            raise ProviderError(f"{provider} generation timed out after {timeout:.0f}s")
        time.sleep(every if _TRANSPORT is None else 0)


def download(url: str, out: Path, headers: dict | None = None, provider: str = "provider") -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with client(timeout=600) as c:
        r = check(c.get(url, headers=headers or {}), provider)
        out.write_bytes(r.content)
    return out


def image_data_uri(path: str | Path, max_side: int = 2048) -> str:
    """A reference/keyframe image as a base64 data URI (PNG), downscaled if huge."""
    return f"data:image/png;base64,{image_b64(path, max_side)}"


def image_b64(path: str | Path, max_side: int = 2048) -> str:
    from PIL import Image

    im = Image.open(path).convert("RGB")
    if max(im.size) > max_side:
        k = max_side / max(im.size)
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def save_image_bytes(data: bytes, width: int, height: int, out_path: str | Path | None):
    """Decode a provider image, fit it exactly to width x height (cover crop), save and return it."""
    from PIL import Image, ImageOps

    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.size != (width, height):
        im = ImageOps.fit(im, (width, height), Image.LANCZOS)
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        im.save(out_path)
    return im


def aspect_of(width: int, height: int, allowed: list[str]) -> str:
    """The provider aspect ratio closest to width:height (e.g. "16:9", "9:16", "1:1")."""
    target = width / height

    def val(a: str) -> float:
        w, h = a.split(":")
        return float(w) / float(h)

    return min(allowed, key=lambda a: abs(val(a) - target))


def pick_duration(seconds: float, allowed: list[int]) -> int:
    """Smallest supported clip length that covers the shot (longest if none does)."""
    for d in sorted(allowed):
        if d >= seconds - 0.05:
            return d
    return max(allowed)


def conform_clip(src: Path, out: Path, width: int, height: int, num_frames: int, fps: int) -> Path:
    """Provider clip -> exactly what the edit expects: width x height (cover crop), fps, num_frames, with an audio
    track (silent when the model makes none)."""
    from ugc_studio.media import ffmpeg, probe

    info = probe(src)
    seconds = num_frames / fps
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height},"
          f"fps={fps},setsar=1,tpad=stop_mode=clone:stop_duration=10,trim=end_frame={num_frames}")
    args = ["-i", str(src)]
    if info["audio"]:
        args += ["-vf", vf, "-af", f"apad,atrim=duration={seconds:.4f}", "-map", "0:v:0", "-map", "0:a:0"]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-vf", vf, "-map", "0:v:0", "-map", "1:a:0",
                 "-t", f"{seconds:.4f}"]
    tmp = out.with_suffix(".partial.mp4")
    ffmpeg([*args, "-c:v", "libx264", "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-b:a", "192k", "-ar", "48000", str(tmp)])
    os.replace(tmp, out)
    return out
