"""Chatterbox Multilingual (MIT, 23 languages incl. Arabic). Runs in vendor/chatterbox/.venv.

Usage: python chatterbox_worker.py job.json
job = {"language_id": "ar", "ref_audio": path|null, "exaggeration": 0.5, "cfg": 0.5,
       "lines": [{"id", "text", "seed"}], "out_dir"}
"""

import json
import re
import sys
from pathlib import Path

import soundfile as sf
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

ARABIC = re.compile(r"[\u0621-\u064A\u0671-\u06D3]")  # letters only: ، ؛ ؟ stay punctuation


def diacritize(lines: list[str]) -> list[str]:
    """Arabic: add tashkeel (CATT, Apache-2.0) so the voice pronounces every word right, keeping the original
    punctuation (it drives the intonation: questions rise, commas pause)."""
    from catt_tashkeel import CATTEncoderDecoder

    model = CATTEncoderDecoder()
    out = []
    for text in lines:
        tokens = re.findall(r"[\w\u064B-\u0652\u0670]+|[^\w\s]|\s+", text)
        words = [t for t in tokens if ARABIC.search(t)]
        if not words:
            out.append(text)
            continue
        vowelled = model.do_tashkeel_batch([" ".join(words)], verbose=False)[0].split()
        if len(vowelled) != len(words):  # never risk a wrong mapping: keep the plain line
            out.append(text)
            continue
        it = iter(vowelled)
        out.append("".join(next(it) if ARABIC.search(t) else t for t in tokens))
    return out


def main(job_path):
    job = json.loads(Path(job_path).read_text())
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    texts = [line["text"] for line in job["lines"]]
    if job["language_id"] == "ar" and job.get("tashkeel", True):
        texts = diacritize(texts)
    # v3 (June 2026): better speaker similarity, fewer hallucinations; UGC_CHATTERBOX_T3=v2 to go back
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model=job.get("t3_model") or "v3")
    for line, text in zip(job["lines"], texts):
        torch.manual_seed(int(line.get("seed", 7)))
        kw = {"language_id": job["language_id"], "exaggeration": line.get("exaggeration", job.get("exaggeration", 0.5)),
              "cfg_weight": line.get("cfg", job.get("cfg", 0.5))}
        if job.get("ref_audio"):
            kw["audio_prompt_path"] = job["ref_audio"]
        wav = model.generate(text, **kw)
        p = out / f"{line['id']}.wav"
        sf.write(p, wav.squeeze().cpu().numpy(), model.sr)
        print(json.dumps({"id": line["id"], "file": str(p)}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
