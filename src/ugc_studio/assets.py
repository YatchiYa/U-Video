"""Asset ingestion: every file you give is validated and normalized before anything is generated.

  images   jpg/png/webp/heic/avif/bmp/tiff/gif, any color mode -> upright (EXIF), sRGB RGB PNG, max 2048 px side
  videos   used as references -> the sharpest, most varied frames are extracted as reference images
  audio    any format -> 24 kHz mono WAV, silence trimmed, 3-30 s kept (voice reference)

Normalized copies live in <project>/.ugc/assets/, keyed by content hash (re-ingesting is instant). Problems are
collected as clear messages instead of failing deep inside a model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from ugc_studio.state import file_hash

log = logging.getLogger(__name__)
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif", ".bmp", ".tif", ".tiff", ".gif"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".3gp"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma"}
MIN_SIDE = 256
MAX_SIDE = 2048

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # HEIC then fails with a clear message
    pass


@dataclass
class IngestReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    converted: int = 0


def kind(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else "unknown"


def normalize_image(src: Path, out_dir: Path, rep: IngestReport) -> str | None:
    out = out_dir / f"{file_hash(src)}.png"
    if out.is_file():
        return str(out)
    try:
        im = Image.open(src)
        im.load()
    except Exception as e:  # noqa: BLE001 - any decoder error becomes a user-facing message
        rep.errors.append(f"{src.name}: cannot read this image ({type(e).__name__}: {e})")
        return None
    im = ImageOps.exif_transpose(im)  # phone photos are often stored sideways
    if getattr(im, "is_animated", False):
        im.seek(0)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))  # transparent product cut-outs -> white
        bg.alpha_composite(im)
        im = bg
    if im.mode == "CMYK" or (im.info.get("icc_profile") and im.mode != "RGB"):
        try:
            from PIL import ImageCms

            im = ImageCms.profileToProfile(im, ImageCms.ImageCmsProfile(__import__("io").BytesIO(im.info["icc_profile"])),
                                           ImageCms.createProfile("sRGB"), outputMode="RGB") if im.info.get("icc_profile") else im
        except Exception:  # noqa: BLE001 - fall back to a plain conversion
            pass
    im = im.convert("RGB")
    if min(im.size) < MIN_SIDE:
        rep.warnings.append(f"{src.name}: only {im.size[0]}x{im.size[1]} px; identity may be weak (use ≥ 512 px)")
    if max(im.size) > MAX_SIDE:
        k = MAX_SIDE / max(im.size)
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    arr = np.asarray(im.convert("L"), dtype=np.float32)
    if arr.std() < 4:
        rep.warnings.append(f"{src.name}: the image is almost uniform (blank?)")
    out_dir.mkdir(parents=True, exist_ok=True)
    im.save(out)
    rep.converted += 1
    return str(out)


def frames_from_video(src: Path, out_dir: Path, rep: IngestReport, n: int = 3) -> list[str]:
    """Pick `n` sharp, mutually different frames from a video to use as reference images."""
    import av

    tag = file_hash(src)
    done = sorted(out_dir.glob(f"{tag}_f*.png"))
    if len(done) >= n:
        return [str(p) for p in done[:n]]
    try:
        with av.open(str(src)) as c:
            stream = c.streams.video[0]
            total = stream.frames or 0
            step = max(1, total // 60) if total else 5
            cands = []
            for i, f in enumerate(c.decode(video=0)):
                if i % step:
                    continue
                im = ImageOps.exif_transpose(f.to_image()).convert("RGB")
                g = np.asarray(im.convert("L").resize((256, int(256 * im.height / im.width))), dtype=np.float32)
                lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]).var()
                cands.append((lap, g, im))
    except Exception as e:  # noqa: BLE001
        rep.errors.append(f"{src.name}: cannot read this video ({type(e).__name__}: {e})")
        return []
    if not cands:
        rep.errors.append(f"{src.name}: no frames in this video")
        return []
    cands.sort(key=lambda c: c[0], reverse=True)
    sharp = cands[: max(n * 4, 8)]
    chosen = [sharp[0]]
    while len(chosen) < n and len(chosen) < len(sharp):  # farthest-point sampling: varied angles
        nxt = max((c for c in sharp if all(c is not x for x in chosen)),
                  key=lambda c: min(np.abs(c[1] - x[1]).mean() if c[1].shape == x[1].shape else 99 for x in chosen))
        chosen.append(nxt)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for k, (_, _, im) in enumerate(chosen):
        p = out_dir / f"{tag}_f{k}.png"
        im.save(p)
        paths.append(str(p))
    rep.converted += len(paths)
    return paths


def normalize_audio(src: Path, out_dir: Path, rep: IngestReport) -> str | None:
    from ugc_studio.media import ffmpeg

    out = out_dir / f"{file_hash(src)}.wav"
    if out.is_file():
        return str(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        ffmpeg(["-i", str(src), "-vn", "-ac", "1", "-ar", "24000",
                "-af", "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                       "silenceremove=start_periods=1:start_threshold=-45dB,areverse,atrim=duration=30",
                str(out)])
    except RuntimeError as e:
        rep.errors.append(f"{src.name}: cannot read this audio ({str(e)[:200]})")
        return None
    import soundfile as sf

    info = sf.info(str(out))
    if info.duration < 3:
        rep.errors.append(f"{src.name}: voice reference is {info.duration:.1f}s; give at least 3 s of clear speech")
        return None
    rep.converted += 1
    return str(out)


def ingest(project, project_dir: Path) -> IngestReport:
    """Validate and normalize every user-provided file referenced by the project (paths are rewritten in memory)."""
    rep = IngestReport()
    out = Path(project_dir) / ".ugc" / "assets"

    def img(path: str | None, what: str) -> str | None:
        if not path:
            return path
        p = Path(path)
        if not p.is_file():
            rep.errors.append(f"{what}: file not found: {path}")
            return None
        k = kind(p)
        if k == "image":
            return normalize_image(p, out, rep)
        if k == "video":
            frames = frames_from_video(p, out, rep, 1)
            return frames[0] if frames else None
        rep.errors.append(f"{what}: {p.name} is not an image or video")
        return None

    def refs(paths: list[str], what: str) -> list[str]:
        res = []
        for path in paths:
            p = Path(path)
            if not p.is_file():
                rep.errors.append(f"{what}: file not found: {path}")
            elif kind(p) == "video":
                res += frames_from_video(p, out, rep, 3)
            elif kind(p) == "image":
                n = normalize_image(p, out, rep)
                if n:
                    res.append(n)
            else:
                rep.errors.append(f"{what}: {p.name} is not an image or video")
        return res

    for c in project.characters:
        c.images = refs(c.images, f"character {c.id}")
    for pr in project.products:
        pr.images = refs(pr.images, f"product {pr.id}")
    for s in project.scenes:
        if s.kind == "clip" and s.video:
            v = Path(s.video)
            if not v.is_file():
                rep.errors.append(f"scene {s.id}: video not found: {v}")
            else:
                from ugc_studio.media import probe

                try:
                    dur = probe(v)["seconds"]
                except Exception as e:  # noqa: BLE001
                    rep.errors.append(f"scene {s.id}: cannot read video {v.name} ({e})")
                    dur = 0
                if dur and s.clip_in + s.seconds > dur + 0.05:
                    rep.warnings.append(f"scene {s.id}: {v.name} is {dur:.1f}s; using {max(0.5, dur - s.clip_in):.1f}s "
                                        f"from {s.clip_in:.1f}s")
                    s.seconds = round(max(0.5, dur - s.clip_in), 3)
        s.start_image = img(s.start_image, f"scene {s.id} start_image")
        s.end_image = img(s.end_image, f"scene {s.id} end_image")
        s.image = img(s.image, f"scene {s.id} image")
        for dv in s.devices:
            dv.image = img(dv.image, f"scene {s.id} device")
        if s.screen_insert and s.screen_insert.image:
            s.screen_insert.image = img(s.screen_insert.image, f"scene {s.id} screen_insert")
    if project.brand.logo and Path(project.brand.logo).suffix.lower() != ".svg":
        project.brand.logo = img(project.brand.logo, "brand logo")
    if project.voice.reference_audio:
        p = Path(project.voice.reference_audio)
        if not p.is_file():
            rep.errors.append(f"voice.reference_audio not found: {p}")
        else:
            project.voice.reference_audio = normalize_audio(p, out, rep)
    if project.music.mode == "file" and project.music.file and not Path(project.music.file).is_file():
        rep.errors.append(f"music.file not found: {project.music.file}")
    return rep
