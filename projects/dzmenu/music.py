"""Original instrumental music bed for the spot with ACE-Step 1.5 (MIT). Run with the ACE-Step venv.

Usage: python music.py <seconds> [candidates]
Writes music/cand<k>.wav; pick the best with score_music.py (main env) -> music/bed.wav
"""

import os
import shutil
import sys
from pathlib import Path

ACE = Path(__file__).resolve().parents[2] / "vendor" / "ACE-Step-1.5"
sys.path.insert(0, str(ACE))
os.chdir(ACE)

from acestep.handler import AceStepHandler  # noqa: E402
from acestep.inference import GenerationConfig, GenerationParams, generate_music  # noqa: E402
from acestep.llm_inference import LLMHandler  # noqa: E402

OUT = Path(__file__).parent / "music"
CAPTION = (
    "Uplifting modern commercial pop instrumental for a premium TV advertisement, warm and optimistic, "
    "bright plucked oud melody with light darbuka and riq percussion, soft claps, warm Rhodes piano chords, "
    "deep round bass, airy pads, clean punchy mix, gentle intro building to a confident, feel-good chorus, "
    "polished resolved ending, no vocals"
)


def main(seconds: float, candidates: int) -> None:
    OUT.mkdir(exist_ok=True)
    dit = AceStepHandler()
    msg, ok = dit.initialize_service(project_root=str(ACE), config_path="acestep-v15-turbo", device="cuda",
                                     offload_to_cpu=False)
    if not ok:
        raise SystemExit(f"DiT init failed: {msg}")
    llm = LLMHandler()
    msg, ok = llm.initialize(checkpoint_dir=str(ACE / "checkpoints"), lm_model_path="acestep-5Hz-lm-1.7B",
                             backend="pt", device="cuda", offload_to_cpu=True, dtype=None)
    if not ok:
        raise SystemExit(f"LM init failed: {msg}")
    for k in range(candidates):
        params = GenerationParams(task_type="text2music", thinking=True, caption=CAPTION, lyrics="[Instrumental]",
                                  instrumental=True, bpm=112, keyscale="D Major", timesignature="4",
                                  duration=seconds, inference_steps=8, seed=5000 + k,
                                  fade_out_duration=1.5)
        res = generate_music(dit, llm, params, GenerationConfig(batch_size=1, audio_format="wav"),
                             save_dir=str(OUT / "_raw"))
        if not res.success:
            raise SystemExit(f"generation failed: {res.error}")
        src = Path(res.audios[0]["path"])
        shutil.copy(src, OUT / f"cand{k}.wav")
        print(f"cand{k} -> {src.name}", flush=True)


if __name__ == "__main__":
    main(float(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 3)
