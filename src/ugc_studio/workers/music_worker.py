"""ACE-Step 1.5 worker. Runs inside vendor/ACE-Step-1.5/.venv. Usage: python music_worker.py job.json

job = {"ace_dir", "caption", "seconds", "bpm"?, "candidates", "seed", "out_dir"}
"""

import json
import os
import shutil
import sys
from pathlib import Path


def main(job_path):
    job = json.loads(Path(job_path).read_text())
    ace = Path(job["ace_dir"])
    sys.path.insert(0, str(ace))
    os.chdir(ace)
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    dit = AceStepHandler()
    msg, ok = dit.initialize_service(project_root=str(ace), config_path="acestep-v15-turbo", device="cuda",
                                     offload_to_cpu=False)
    if not ok:
        raise SystemExit(f"DiT init failed: {msg}")
    llm = LLMHandler()
    msg, ok = llm.initialize(checkpoint_dir=str(ace / "checkpoints"), lm_model_path="acestep-5Hz-lm-1.7B",
                             backend="pt", device="cuda", offload_to_cpu=True, dtype=None)
    if not ok:
        raise SystemExit(f"LM init failed: {msg}")
    for k in range(int(job.get("candidates", 2))):
        params = GenerationParams(task_type="text2music", thinking=True, caption=job["caption"],
                                  lyrics="[Instrumental]", instrumental=True, bpm=job.get("bpm"), timesignature="4",
                                  duration=float(job["seconds"]), inference_steps=8, seed=int(job["seed"]) + k,
                                  fade_out_duration=1.5)
        res = generate_music(dit, llm, params, GenerationConfig(batch_size=1, audio_format="wav"),
                             save_dir=str(out / "_raw"))
        if not res.success:
            raise SystemExit(f"generation failed: {res.error}")
        dst = out / f"cand{k}.wav"
        shutil.copy(res.audios[0]["path"], dst)
        print(json.dumps({"file": str(dst)}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
