"""French TV voice-over with Qwen3-TTS: design one announcer voice, then clone it for every line.

Run with vendor/tts/.venv/bin/python. Writes vo/<id>.wav (24 kHz mono) and vo/manifest.json.
Transcript validation runs afterwards in the main env (Whisper), see check_vo.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

HERE = Path(__file__).parent
OUT = HERE / "vo"

INSTRUCT = (
    "A warm, confident, professional French male voice-over artist for a premium national TV commercial. "
    "Rich medium-low pitch, clear and elegant diction, friendly and inspiring energy, natural pacing, "
    "standard French accent, recorded in a studio with a high-end microphone."
)
REF_TEXT = (
    "Chaque jour, des milliers de cafés et de restaurants accueillent leurs clients avec le sourire. "
    "Aujourd'hui, il existe une façon plus simple de leur présenter votre carte."
)

# Spoken text uses phonetic spellings where TTS would misread the brand or URL.
LINES = {
    "vo01": "Des menus abîmés… des prix raturés… des clients qui attendent.",
    "vo02": "Il est temps de passer au digital.",
    "vo03": "Voici Dé-Zèd Menu : le menu QR trilingue pour les cafés et les restaurants.",
    "vo04": "Vos clients scannent le QR code…",
    "vo05": "et votre carte s'ouvre instantanément. Aucune application à installer.",
    "vo06": "En français, en arabe, en anglais : un seul QR code.",
    "vo07": "Photographiez simplement votre carte papier.",
    "vo08": "Catégories, plats et prix sont lus et traduits. Votre menu est en ligne en deux minutes.",
    "vo09": "Pas le temps ? Envoyez-nous votre carte : on s'occupe de tout, en vingt-quatre heures.",
    "vo10": "Réservations, statistiques, promotions : tout se gère depuis votre espace.",
    "vo11": "Dé-Zèd Menu. Trente jours gratuits, sans carte bancaire. Rendez-vous sur dé-zèd tiret menu point com.",
}


def load(repo: str) -> Qwen3TTSModel:
    return Qwen3TTSModel.from_pretrained(repo, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")


def design(candidates: int = 3) -> None:
    OUT.mkdir(exist_ok=True)
    m = load("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
    for k in range(candidates):
        torch.manual_seed(1000 + k)
        wavs, sr = m.generate_voice_design(text=REF_TEXT, language="French", instruct=INSTRUCT)
        sf.write(OUT / f"ref_candidate{k}.wav", wavs[0], sr)
        print(f"ref_candidate{k}: {len(wavs[0]) / sr:.2f}s", flush=True)


def clone(ref: str, ids: list[str], seed: int = 7) -> None:
    m = load("Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    prompt = m.create_voice_clone_prompt(ref_audio=str(OUT / ref), ref_text=REF_TEXT)
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for vid in ids:
        torch.manual_seed(seed)
        wavs, sr = m.generate_voice_clone(text=LINES[vid], language="French", voice_clone_prompt=prompt)
        wav = np.asarray(wavs[0], dtype=np.float32)
        sf.write(OUT / f"{vid}.wav", wav, sr)
        manifest[vid] = {"text": LINES[vid], "seconds": round(len(wav) / sr, 3), "seed": seed, "ref": ref}
        print(f"{vid}: {len(wav) / sr:.2f}s", flush=True)
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "design":
        design()
    elif cmd == "clone":
        ref, seed, ids = sys.argv[2], int(sys.argv[3]), sys.argv[4:] or list(LINES)
        clone(ref, ids, seed)
