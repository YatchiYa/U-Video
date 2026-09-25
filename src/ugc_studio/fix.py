"""Surgical repairs. A fix is stored in the project (scene.fixes) and re-applied on every build, so repairs are
non-destructive, reproducible and undoable. Only the affected scene and the final edit are rebuilt.

  interpolate  rebuild a few bad frames from their neighbours (optical flow, seconds, no AI)
  freeze       hold the last good frame over a short glitch
  retake       regenerate only a time window of the clip with LTX-2.5 (rest untouched)
  reshoot      (not a Fix entry) new seed and/or prompt for the whole shot; keyframes and seams are kept
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ugc_studio.media import interpolate_frames, probe, read_frames, write_video_with_audio
from ugc_studio.schema import Fix, Project

log = logging.getLogger(__name__)
INTERPOLATE_MAX = 0.5  # seconds: longer gaps need a retake, flow can't invent that much motion
RETAKE_MIN = 1.0  # seconds: LTX needs some context to regenerate a window cleanly


def plan_fix(t_local: float, duration: float, mode: str, clip_seconds: float) -> Fix:
    """Turn "something is wrong at t (for ~duration)" into a concrete, correctly sized fix."""
    if mode == "auto":
        mode = "interpolate" if duration <= 0.25 else "retake"
    if mode in ("interpolate", "freeze"):
        half = max(duration, 1 / 24) / 2
        a, b = max(0.0, t_local - half), min(clip_seconds, t_local + half)
        if b - a > INTERPOLATE_MAX:
            raise ValueError(f"{b - a:.2f}s is too long to interpolate (max {INTERPOLATE_MAX}s): use --mode retake")
        return Fix(kind=mode, start=round(a, 4), end=round(max(b, a + 1 / 48), 4))
    if mode == "retake":
        w = max(RETAKE_MIN, duration + 0.5)
        a = max(0.0, t_local - w / 2)
        b = min(clip_seconds, a + w)
        a = max(0.0, b - w)
        return Fix(kind="retake", start=round(a, 3), end=round(b, 3))
    raise ValueError(f"unknown fix mode {mode!r}")


def apply_fixes(src: Path, fixes: list[Fix], out: Path, scene_prompt: str, seed: int, retaker=None) -> Path:
    """Apply fixes in order; each step reads the previous result. `retaker` is a lazy RetakeRenderer factory."""
    cur = src
    work = out.parent / f".{out.stem}_steps"
    work.mkdir(parents=True, exist_ok=True)
    for k, fx in enumerate(fixes):
        step = work / f"{k:02d}_{fx.kind}.mp4"
        if fx.kind in ("interpolate", "freeze"):
            info = probe(cur)
            frames = read_frames(cur)
            fps = info["fps"]
            a = max(0, int(fx.start * fps))
            b = min(len(frames) - 1, max(a, int(round(fx.end * fps)) - 1))
            if fx.kind == "interpolate":
                interpolate_frames(frames, a, b)
            else:
                hold = frames[a - 1] if a > 0 else frames[min(b + 1, len(frames) - 1)]
                for i in range(a, b + 1):
                    frames[i] = hold.copy()
            write_video_with_audio(frames, fps, cur, step)
            log.info("fix %s frames %d-%d of %s", fx.kind, a, b, src.name)
        elif fx.kind == "retake":
            if retaker is None:
                raise RuntimeError("retake fix requires the LTX retake pipeline")
            r = retaker()
            r.retake(cur, step, fx.prompt or scene_prompt, fx.start, fx.end, fx.seed if fx.seed is not None else seed + 911 + k,
                     video=fx.video, audio=fx.audio)
            log.info("fix retake %.2f-%.2fs of %s", fx.start, fx.end, src.name)
        cur = step
    shutil.copy(cur, out)
    return out


def add_fix(project: Project, scene_id: str, fx: Fix) -> None:
    project.scene(scene_id).fixes.append(fx)


def undo_fix(project: Project, scene_id: str) -> Fix | None:
    fixes = project.scene(scene_id).fixes
    return fixes.pop() if fixes else None
