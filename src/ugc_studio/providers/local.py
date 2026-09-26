"""Local open-source backends (default): FLUX.2 klein images, LTX-2.5 video (render.ShotRenderer), ACE-Step music.
Narration engines (Qwen3-TTS, Chatterbox, Habibi) run in their own environments, driven by voice.py.
Checkpoints are chosen with UGC_* variables (config.py / .env.example)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ugc_studio.config import ACE_DIR, ACE_PYTHON, FLUX_STEPS, ROOT
from ugc_studio.providers.base import ImageBackend, MusicBackend, ProviderError


class LocalImage(ImageBackend):
    name = "local (FLUX.2 klein)"

    def __init__(self, model: str | None = None, steps: int = FLUX_STEPS):
        from ugc_studio.keyframes import KeyframeGenerator

        self.g = KeyframeGenerator(steps=steps, source=model)

    def generate(self, prompt, width, height, seed, references=None, out_path=None):
        return self.g.generate(prompt, width, height, seed, references=references, out_path=out_path)

    def close(self) -> None:
        self.g.close()


class AceMusic(MusicBackend):
    name = "local (ACE-Step 1.5)"
    WORKER = Path(__file__).resolve().parents[1] / "workers" / "music_worker.py"

    def __init__(self, model: str | None = None):
        if not ACE_PYTHON.is_file():
            raise ProviderError(f"Music environment missing ({ACE_PYTHON}). Run `ugc setup` or set music.mode: none.")

    def generate(self, caption, seconds, bpm, seed, candidates, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        job = {"ace_dir": str(ACE_DIR), "caption": caption, "seconds": seconds, "bpm": bpm, "candidates": candidates,
               "seed": seed, "out_dir": str(out_dir)}
        jp = out_dir / "job.json"
        jp.write_text(json.dumps(job))
        proc = subprocess.run([str(ACE_PYTHON), str(self.WORKER), str(jp)], capture_output=True, text=True, cwd=ROOT)
        if proc.returncode != 0:
            raise ProviderError(f"Music worker failed:\n{proc.stderr[-3000:]}")
