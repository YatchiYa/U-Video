"""Music bed: original instrumental (ACE-Step 1.5, MIT) or your own file; best candidate chosen by analysis."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from ugc_studio.config import ACE_DIR, ACE_PYTHON, ROOT
from ugc_studio.schema import Project
from ugc_studio.state import State, ref

log = logging.getLogger(__name__)
WORKER = Path(__file__).parent / "workers" / "music_worker.py"

MOOD = {
    "ugc": "light, feel-good lo-fi pop instrumental, soft beat, warm and friendly, unobtrusive",
    "influencer": "trendy upbeat pop instrumental, catchy groove, modern and confident, social-media energy",
    "faceless": "viral cinematic trap-pop instrumental, punchy drums, suspenseful build, bold modern energy",
    "promo": "uplifting modern commercial pop instrumental, warm, optimistic, premium TV advertisement",
}


def score(path: Path) -> dict:
    """Groove regularity + steady energy (no collapse at the end) + no clipping."""
    x, sr = sf.read(path, dtype="float32")
    mono = x.mean(1) if x.ndim > 1 else x
    hop = 512
    n = len(mono) // hop
    e = np.sqrt((mono[: n * hop].reshape(n, hop) ** 2).mean(1))
    on = np.maximum(0, np.diff(e))
    on = (on - on.mean()) / (on.std() + 1e-9)
    ac = np.correlate(on, on, "full")[len(on) - 1:]
    ac /= ac[0] + 1e-9
    lo, hi = int(0.3 * sr / hop), int(1.2 * sr / hop)
    rhythm = float(ac[lo:hi].max())
    q = len(mono) // 4
    quarters = [20 * np.log10(np.sqrt((mono[i * q:(i + 1) * q] ** 2).mean()) + 1e-9) for i in range(4)]
    spread = float(max(quarters[:3]) - min(quarters[:3]))  # last quarter may fade out
    clip = float((np.abs(x) >= 0.999).mean())
    return {"rhythm": round(rhythm, 3), "spread_db": round(spread, 2), "clip": clip,
            "total": round(rhythm - 0.05 * spread - 50 * clip, 3)}


def build(project: Project, state: State, workdir: Path, seconds: float) -> Path | None:
    m = project.music
    if m.mode == "none":
        return None
    if m.mode == "file":
        if not m.file or not Path(m.file).is_file():
            raise FileNotFoundError(f"music.file not found: {m.file}")
        return Path(m.file)
    from ugc_studio.schema import Music

    # A custom prompt is the user's intent: don't dilute it with the mode's default mood.
    mood = f" {MOOD[project.mode]}." if m.prompt == Music().prompt else ""
    caption = f"{m.prompt}.{mood} Instrumental, no vocals."
    inputs = {"caption": caption, "seconds": round(seconds, 1), "bpm": m.bpm, "seed": project.seed}
    out = workdir / "bed.wav"
    if state.fresh("music", inputs):
        return out
    if not ACE_PYTHON.is_file():
        raise FileNotFoundError(f"Music environment missing ({ACE_PYTHON}). Run `ugc setup` or set music.mode: none.")
    workdir.mkdir(parents=True, exist_ok=True)
    job = {"ace_dir": str(ACE_DIR), "caption": caption, "seconds": seconds, "bpm": m.bpm, "candidates": 2,
           "seed": 5000 + project.seed, "out_dir": str(workdir)}
    jp = workdir / "job.json"
    jp.write_text(json.dumps(job))
    proc = subprocess.run([str(ACE_PYTHON), str(WORKER), str(jp)], capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"Music worker failed:\n{proc.stderr[-3000:]}")
    scored = sorted(((score(p), p) for p in workdir.glob("cand*.wav")), key=lambda t: t[0]["total"], reverse=True)
    best = scored[0][1]
    shutil.copy(best, out)
    state.commit("music", inputs, [out], scores={p.name: s for s, p in scored}, chosen=best.name)
    log.info("Music: chose %s %s", best.name, scored[0][0])
    return out


def music_ref(project: Project) -> dict:
    return {"music": ref(project.music.file) if project.music.mode == "file" else project.music.model_dump()}
