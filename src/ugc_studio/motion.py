"""Motion-graphics layer: builds the composition data for the HTML engine and renders it frame-exact (RGBA)."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import subprocess
from pathlib import Path

from ugc_studio.config import MOTION_DIR
from ugc_studio.media import FFMPEG
from ugc_studio.schema import Project
from ugc_studio.timeline import Timeline

log = logging.getLogger(__name__)
ENGINE_FILES = ["index.html", "style.css", "engine.js", "node_modules"]


def lucide_exists(name: str) -> bool:
    return (MOTION_DIR / "node_modules" / "lucide-static" / "icons" / f"{name}.svg").is_file()


def qr_svg(url: str, out: Path, dark: str = "#161320") -> Path:
    import segno

    segno.make(url, error="h").save(str(out), scale=10, border=0, dark=dark, light=None)
    return out


def build_comp(project: Project, tl: Timeline, workdir: Path, width: int, height: int,
               caption_words: list[dict] | None = None, seqs: dict[str, dict] | None = None) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    b = project.brand.model_dump()
    b["logo"] = Path(b["logo"]).resolve().as_uri() if b.get("logo") else None
    scenes = []
    title_seen = False
    for slot in tl.slots:
        sc = project.scene(slot.id)
        d = {
            "id": sc.id, "kind": sc.kind, "start": slot.start, "dur": slot.dur, "transition": slot.transition,
            "transition_s": slot.transition_s, "caption": sc.caption, "beats": slot.beats,
            "headline": sc.headline, "eyebrow": sc.eyebrow, "bullets": sc.bullets, "offer": sc.offer,
            "device": sc.device, "reveal": sc.reveal, "theme": sc.theme,
            "devices": [{"label": dv.label, "image": Path(dv.image).resolve().as_uri() if dv.image else None,
                         "seq": ({"dir": Path(seqs[f"{sc.id}__{k}"]["dir"]).resolve().as_uri(),
                                  "frames": seqs[f"{sc.id}__{k}"]["frames"]}
                                 if seqs and f"{sc.id}__{k}" in seqs else None)}
                        for k, dv in enumerate(sc.devices)],
            "features": [f.model_dump() | {"icon": f.icon if lucide_exists(f.icon) else "sparkles"}
                                              for f in sc.features],
            "image": Path(sc.image).resolve().as_uri() if sc.image else None, "seq": None,
            "show_logo": sc.kind == "title" and not title_seen,
        }
        if sc.kind == "title":
            title_seen = True
        if seqs and sc.id in seqs:
            d["seq"] = {"dir": Path(seqs[sc.id]["dir"]).resolve().as_uri(), "frames": seqs[sc.id]["frames"]}
        if sc.kind == "endcard" and project.brand.url:
            d["qr"] = qr_svg(project.brand.url, workdir / "qr.svg", project.brand.dark).resolve().as_uri()
            d["qr_label"] = {"french": "Scannez-moi", "spanish": "Escanéame", "arabic": "امسح الرمز"}.get(
                project.language.lower(), "Scan me")
        scenes.append(d)
    return {
        "fps": tl.fps, "total": tl.total, "width": width, "height": height, "brand": b,
        "logo_bug": project.logo_bug, "scenes": scenes,
        "captions": {"enabled": project.captions.enabled, "style": project.captions.style,
                     "position": project.captions.position, "words": caption_words or []},
    }


def needs_overlay(project: Project) -> bool:
    return (project.captions.enabled or project.logo_bug or any(s.kind not in ("shot", "clip") or s.caption for s in project.scenes))


def prepare(comp: dict, workdir: Path) -> Path:
    """Per-project engine folder: engine files are symlinked, comp.js is project data."""
    workdir.mkdir(parents=True, exist_ok=True)
    for f in ENGINE_FILES:
        link = workdir / f
        if not link.exists():
            link.symlink_to(MOTION_DIR / f)
    (workdir / "comp.js").write_text("window.COMP = " + json.dumps(comp, ensure_ascii=False) + ";\n")
    return workdir / "index.html"


async def _frames(index: Path, comp: dict, sink, times: list[float] | None = None):
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--allow-file-access-from-files", "--force-color-profile=srgb"])
        page = await b.new_page(viewport={"width": comp["width"], "height": comp["height"]}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(index.as_uri())
        await page.evaluate("window.compReady")
        if errors:
            raise RuntimeError(f"motion engine error: {errors[0]}")
        ts = times if times is not None else [f / comp["fps"] for f in range(round(comp["total"] * comp["fps"]))]
        for k, t in enumerate(ts):
            await page.evaluate(f"window.seek({t:.6f})")
            sink(await page.screenshot(type="png", omit_background=True))
            if times is None and k % (comp["fps"] * 10) == 0:
                log.info("  motion frame %d/%d", k, len(ts))
        await b.close()


def render_overlay(comp: dict, workdir: Path, out: Path) -> Path:
    """RGBA overlay -> ProRes 4444 (single piped input: no multi-input ffmpeg deadlock)."""
    index = prepare(comp, workdir)
    tmp = out.with_suffix(".partial.mov")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(comp["fps"]),
           "-c:v", "png", "-i", "-", "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
           "-alpha_bits", "16", "-vendor", "apl0", str(tmp)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        asyncio.run(_frames(index, comp, proc.stdin.write))
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"overlay encode failed ({rc})")
    tmp.replace(out)
    return out


def stills(comp: dict, workdir: Path, times: list[float]) -> list:
    """PIL RGBA images of the overlay at given times (previews / tests)."""
    from PIL import Image

    index = prepare(comp, workdir)
    frames = []
    asyncio.run(_frames(index, comp, lambda png: frames.append(Image.open(io.BytesIO(png)).convert("RGBA")), times))
    return frames
