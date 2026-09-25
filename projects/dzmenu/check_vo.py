"""Validate voice-over lines with Whisper (French) and store word timestamps in vo/manifest.json.

Usage: python check_vo.py [ids...]   (main env). Exit code 1 if any line scores below the threshold.
"""

from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from transformers import pipeline

HERE = Path(__file__).parent
VO = HERE / "vo"
THRESHOLD = 0.9

# Spoken forms that Whisper legitimately writes differently from our phonetic TTS spelling.
EQUIV = {"dé-zèd": "dz", "dézèd": "dz", "dz-menu": "dz menu", "tiret": "", "point com": "com", "vingt-quatre": "24",
         "24h": "24", "heures": "heures", "qr": "qr", "q r": "qr"}


def norm(text: str) -> list[str]:
    t = text.lower().replace("’", "'")
    for a, b in EQUIV.items():
        t = t.replace(a, b)
    t = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿœæ' ]+", " ", t)
    # French plural -s/-x is silent: "réservations" and "réservation" sound identical.
    return [w[:-1] if len(w) > 3 and w[-1] in "sx" else w for w in t.split()]


def main(ids: list[str]) -> int:
    manifest = json.loads((VO / "manifest.json").read_text())
    ids = ids or sorted(manifest)
    asr = pipeline("automatic-speech-recognition", model="openai/whisper-large-v3-turbo", dtype=torch.float16, device="cuda")
    bad = 0
    for vid in ids:
        wav, sr = sf.read(VO / f"{vid}.wav", dtype="float32")
        if wav.ndim > 1:
            wav = wav.mean(axis=1)
        out = asr({"raw": wav, "sampling_rate": sr}, return_timestamps="word",
                  generate_kwargs={"language": "french", "task": "transcribe"})
        words = [{"w": c["text"].strip(), "t0": round(c["timestamp"][0], 3), "t1": round(c["timestamp"][1] or c["timestamp"][0], 3)}
                 for c in out["chunks"]]
        score = SequenceMatcher(None, norm(manifest[vid]["text"]), norm(out["text"])).ratio()
        # Speech bounds (for tight placement): first/last sample above -40 dBFS.
        env = np.abs(wav) > 10 ** (-40 / 20)
        idx = np.flatnonzero(env)
        manifest[vid].update(transcript=out["text"].strip(), score=round(score, 3), words=words,
                             speech_start=round(idx[0] / sr, 3) if idx.size else 0.0,
                             speech_end=round(idx[-1] / sr, 3) if idx.size else 0.0)
        flag = "OK " if score >= THRESHOLD else "BAD"
        bad += score < THRESHOLD
        print(f"{flag} {vid} {score:.2f} {manifest[vid]['seconds']:.2f}s | {out['text'].strip()}")
    (VO / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
