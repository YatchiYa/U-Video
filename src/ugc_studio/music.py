"""Music bed: original instrumental (ACE-Step 1.5, plus Stable Audio 3 when installed) or your own file; the best
candidate is chosen by a listener model (Audiobox Aesthetics) and a groove/level analysis."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import numpy as np
import soundfile as sf

from ugc_studio.schema import Project
from ugc_studio.state import State, ref

log = logging.getLogger(__name__)

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


def aesthetics(paths: list[Path]) -> dict[str, dict]:
    """Audiobox Aesthetics ratings per file (empty when the Stable Audio environment isn't installed)."""
    import json
    import subprocess

    from ugc_studio.config import ROOT, SA3_PYTHON, STABLE_AUDIO

    if not (STABLE_AUDIO and SA3_PYTHON.is_file()) or not paths:
        return {}
    judge = Path(__file__).parent / "workers" / "music_judge.py"
    proc = subprocess.run([str(SA3_PYTHON), str(judge), *map(str, paths)], capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        log.warning("Music judge unavailable: %s", proc.stderr.strip().splitlines()[-1:] or proc.returncode)
        return {}
    return json.loads(proc.stdout.strip().splitlines()[-1])


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
    from ugc_studio import providers
    from ugc_studio.images import provider_tag

    from ugc_studio.config import ACE_CONFIG
    from ugc_studio.providers.local import StableAudioMusic

    inputs = {"caption": caption, "seconds": round(seconds, 1), "bpm": m.bpm, "seed": project.seed,
              **provider_tag(project, "music"),
              **({"ace": ACE_CONFIG} if ACE_CONFIG != "acestep-v15-turbo" else {}),
              **({"sa3": 1} if StableAudioMusic.available() and providers.choice(project, "music").provider in ("local", "auto")
                 else {})}
    out = workdir / "bed.wav"
    if state.fresh("music", inputs):
        return out
    workdir.mkdir(parents=True, exist_ok=True)
    for old in workdir.glob("cand*.wav"):  # candidates from another provider/run must not compete
        old.unlink()
    backend = providers.create(project, "music")
    backend.generate(caption, seconds, m.bpm, 5000 + project.seed, 2, workdir)
    if not any(workdir.glob("cand*.wav")):
        raise RuntimeError(f"{backend.name} produced no music")
    cands = sorted(workdir.glob("cand*.wav"))
    rated = aesthetics(cands)
    scored = []
    for p in cands:
        s = score(p)
        a = rated.get(str(p))
        if a:  # a listener model beats the groove heuristic: enjoyment first, then production quality
            s = {**s, **a, "total": round(a["CE"] + 0.5 * a["PQ"] + s["rhythm"] - 0.05 * s["spread_db"] - 50 * s["clip"], 3)}
        scored.append((s, p))
    scored.sort(key=lambda t: t[0]["total"], reverse=True)
    best = scored[0][1]
    shutil.copy(best, out)
    state.commit("music", inputs, [out], scores={p.name: s for s, p in scored}, chosen=best.name)
    log.info("Music: chose %s %s", best.name, scored[0][0])
    return out


def music_ref(project: Project) -> dict:
    return {"music": ref(project.music.file) if project.music.mode == "file" else project.music.model_dump()}
