"""Stable Audio 3 Medium worker (Stability AI, 1.4B, stereo 44.1 kHz, up to 380 s). Runs inside
vendor/stable-audio-3/.venv (torch 2.7.1 + Flash Attention 2). Stability AI Community License: free under $1M annual
revenue; the weights are gated on Hugging Face (accept the terms, HF_TOKEN in .env).

Usage: python sa3_worker.py job.json
job = {"caption", "seconds", "bpm"?, "candidates", "seed", "out_dir", "first"?: 0, "steps"?: 8}
Candidates are written as cand{first}.wav, cand{first+1}.wav... next to the other engines' candidates.
"""

import json
import sys
from pathlib import Path


def main(job_path: str) -> None:
    import soundfile as sf
    import torch
    from stable_audio_3 import StableAudioModel

    job = json.loads(Path(job_path).read_text())
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    prompt = job["caption"] + (f" {int(job['bpm'])} BPM" if job.get("bpm") else "")
    model = StableAudioModel.from_pretrained("medium")
    for k in range(int(job.get("candidates", 2))):
        with torch.inference_mode():
            # adversarially post-trained: 8 steps, cfg 1 (so no negative prompt)
            audio = model.generate(prompt=prompt, duration=float(job["seconds"]), steps=int(job.get("steps", 8)),
                                   seed=int(job["seed"]) + k)
        sr = model.model.sample_rate
        a = audio[0].float().cpu()  # [channels, samples]
        a = a / max(1.0, float(a.abs().max()) / 0.98)  # keep headroom: the mix sets the final level
        dst = out / f"cand{int(job.get('first', 0)) + k}.wav"
        sf.write(dst, a.T.numpy(), int(sr))
        print(json.dumps({"file": str(dst)}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
