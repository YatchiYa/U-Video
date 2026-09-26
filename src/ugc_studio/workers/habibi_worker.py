"""Habibi-TTS (Arabic dialects; the Specialized MSA/ALG/EGY/IRQ/MAR checkpoints are Apache-2.0).
Runs in vendor/habibi/.venv. Only Specialized checkpoints are used (the Unified one is non-commercial).

Usage: python habibi_worker.py job.json
job = {"dialect": "ALG", "ref_audio": wav, "ref_text": str, "speed": 1.0, "lines": [{"id","text","seed"}], "out_dir"}
"""

import json
import sys
from importlib.resources import files
from pathlib import Path

import soundfile as sf
import torch
from cached_path import cached_path
from f5_tts.infer.utils_infer import load_model, load_vocoder, preprocess_ref_audio_text
from hydra.utils import get_class
from omegaconf import OmegaConf

from habibi_tts.infer.utils_infer import infer_process
from habibi_tts.model.utils import dialect_id_map

# Only the Apache-2.0 Specialized checkpoints. SAU, UAE and Unified are CC-BY-NC-SA: never loaded.
STEPS = {"MSA": 200000, "ALG": 100000, "IRQ": 100000, "EGY": 100000, "MAR": 100000}


def main(job_path):
    job = json.loads(Path(job_path).read_text())
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    d = job["dialect"]
    if d not in STEPS:
        raise SystemExit(f"dialect {d!r} is not available for commercial use (allowed: {', '.join(STEPS)})")
    ckpt = str(cached_path(f"hf://SWivid/Habibi-TTS/Specialized/{d}/model_{STEPS[d]}.safetensors"))
    vocab = str(cached_path(f"hf://SWivid/Habibi-TTS/Specialized/{d}/vocab.txt"))
    cfg = OmegaConf.load(str(files("f5_tts").joinpath("configs/F5TTS_v1_Base.yaml")))
    model = load_model(get_class(f"f5_tts.model.{cfg.model.backbone}"), cfg.model.arch, ckpt,
                       mel_spec_type=cfg.model.mel_spec.mel_spec_type, vocab_file=vocab, device="cuda")
    vocoder = load_vocoder(vocoder_name=cfg.model.mel_spec.mel_spec_type, device="cuda")
    ref_audio, ref_text = preprocess_ref_audio_text(job["ref_audio"], job["ref_text"])
    for line in job["lines"]:
        torch.manual_seed(int(line.get("seed", 7)))
        audio, sr, _ = infer_process(ref_audio, ref_text, line["text"], model, vocoder,
                                     mel_spec_type=cfg.model.mel_spec.mel_spec_type, speed=job.get("speed", 1.0),
                                     device="cuda", dialect_id=dialect_id_map[d])
        p = out / f"{line['id']}.wav"
        sf.write(p, audio, sr)
        print(json.dumps({"id": line["id"], "file": str(p)}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
