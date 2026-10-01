"""Higgs Audio v3 TTS (Boson AI, 4B, 100+ languages, zero-shot cloning). Runs inside vendor/qi21/.venv
(transformers >= 5.5). Research and non-commercial license: personal use only.

Usage: python higgs_worker.py job.json
job = {"ref_audio": path|null, "ref_text": str, "lines": [{"id", "text", "seed", "cfg"?}],
       "out_dir", "temperature"?: 0.8, "top_k"?: 50}
torchaudio (only used to resample the reference) is installed without dependencies: 2.11 is the last release and
its resampler is plain torch, so it works with torch 2.14.
"""

import json
import sys
from pathlib import Path

REPO = "multimodalart/higgs-audio-v3-tts-4b-transformers"  # transformers port of bosonai/higgs-tts-3-4b (= config.HIGGS_REPO)
SR = 24000
FRAMES_PER_SECOND = 75  # upper bound for the token cap; the duration check catches runaways


def main(job_path: str) -> None:
    import soundfile as sf
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    job = json.loads(Path(job_path).read_text())
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(REPO)
    model = AutoModelForCausalLM.from_pretrained(REPO, trust_remote_code=True, dtype=torch.bfloat16).to("cuda").eval()
    ref_codes = None
    if job.get("ref_audio"):
        wav, sr = sf.read(job["ref_audio"], dtype="float32", always_2d=True)
        ref_codes = model._encode_reference(torch.from_numpy(wav[: sr * 30]).mean(dim=1), sr).cpu()
    ref_text = (job.get("ref_text") or "").strip() or None
    for line in job["lines"]:
        text = line["text"].strip()
        # runaway guard: an autoregressive voice sometimes never stops; cap the length and retry once
        limit = 0.12 * len(text) + 4.0
        for extra in range(2):
            torch.manual_seed(int(line.get("seed", 7)) + 101 * extra)
            kw = {"reference_codes": ref_codes, "reference_text": ref_text} if ref_codes is not None else {}
            with torch.inference_mode():
                audio = model.generate_speech(text, tok, max_new_tokens=int(FRAMES_PER_SECOND * limit) + 8,
                                              temperature=float(line.get("temperature", job.get("temperature", 0.8))),
                                              top_k=int(job.get("top_k", 50)), **kw)
            if audio.numel() and audio.numel() / SR < limit - 0.5:
                break
        p = out / f"{line['id']}.wav"
        sf.write(p, audio.numpy(), SR)
        print(json.dumps({"id": line["id"], "file": str(p)}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
