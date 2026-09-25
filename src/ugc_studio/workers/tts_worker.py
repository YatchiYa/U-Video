"""Qwen3-TTS worker. Runs inside vendor/tts/.venv (isolated deps). Usage: python tts_worker.py job.json

job = {"design_model", "clone_model", "instruct", "language", "ref_audio"?, "ref_text",
       "design_candidates": int, "lines": [{"id", "text", "seed"}], "out_dir"}
Writes <out_dir>/<id>.wav (and ref_candidate<k>.wav when designing) and prints one JSON line per file.
"""

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel


def load(repo):
    return Qwen3TTSModel.from_pretrained(repo, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")


def main(job_path):
    job = json.loads(Path(job_path).read_text())
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    if job.get("design_candidates"):
        m = load(job["design_model"])
        for k in range(job["design_candidates"]):
            torch.manual_seed(1000 + k)
            wavs, sr = m.generate_voice_design(text=job["ref_text"], language=job["language"], instruct=job["instruct"])
            p = out / f"ref_candidate{k}.wav"
            sf.write(p, wavs[0], sr)
            print(json.dumps({"file": str(p), "seconds": len(wavs[0]) / sr}), flush=True)
        del m
        torch.cuda.empty_cache()
    if job.get("lines"):
        m = load(job["clone_model"])
        prompt = m.create_voice_clone_prompt(ref_audio=job["ref_audio"], ref_text=job["ref_text"])
        for line in job["lines"]:
            torch.manual_seed(int(line.get("seed", 7)))
            wavs, sr = m.generate_voice_clone(text=line["text"], language=job["language"], voice_clone_prompt=prompt)
            wav = np.asarray(wavs[0], dtype=np.float32)
            p = out / f"{line['id']}.wav"
            sf.write(p, wav, sr)
            print(json.dumps({"id": line["id"], "file": str(p), "seconds": len(wav) / sr}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
