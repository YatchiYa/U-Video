"""Paths, model registry and render presets."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(os.environ.get("UGC_ROOT", Path(__file__).resolve().parents[2]))


def parse_dotenv(text: str) -> dict[str, str]:
    """KEY=VALUE lines; `# comments` on their own line or after a value (unless quoted); empty values allowed."""
    import re

    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        m = re.match(r"""^(['"])(.*?)\1""", value)
        value = m.group(2) if m else ("" if value.startswith("#") else re.split(r"\s+#", value, maxsplit=1)[0].strip())
        out[key.strip()] = value
    return out


def _load_dotenv(path: Path) -> None:
    """Load .env; real environment variables win."""
    if path.is_file():
        for key, value in parse_dotenv(path.read_text()).items():
            os.environ.setdefault(key, value)


_load_dotenv(ROOT / ".env")

def env(name: str, default: str) -> str:
    """UGC_* setting: the environment (or .env) wins over the built-in default. Empty values fall back too, and so
    do values that are really a comment (`KEY=   # note` read by a parser that keeps inline comments)."""
    value = (os.environ.get(name) or "").strip()
    return default if not value or value.startswith("#") else value


MODELS_DIR = Path(env("UGC_MODELS", str(ROOT / "models")))
OUTPUTS_DIR = Path(env("UGC_OUTPUTS", str(ROOT / "outputs")))
VENDOR_DIR = Path(env("UGC_VENDOR", str(ROOT / "vendor")))
MOTION_DIR = Path(__file__).parent / "motion"

# ---- local models (every one can be swapped for another open-source checkpoint with an env var; see .env.example)
LTX_DIR = Path(env("UGC_LTX_DIR", str(MODELS_DIR / "ltx-2.5")))
LTX_REPO = env("UGC_LTX_REPO", "Lightricks/LTX-2.5")
LTX_FILES = {
    "transformer": env("UGC_LTX_TRANSFORMER", "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors"),
    "text_encoder": env("UGC_LTX_TEXT_ENCODER", "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"),
    "video_vae": env("UGC_LTX_VIDEO_VAE", "vae/ltx-2.5-video-vae-bf16.safetensors"),
    "audio_vae": env("UGC_LTX_AUDIO_VAE", "vae/ltx-2.5-audio-vae-bf16.safetensors"),
    "spatial_upsampler": env("UGC_LTX_UPSAMPLER",
                             "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"),
}
LTX_QUANTIZATION = env("UGC_LTX_QUANTIZATION", "fp8-cast")  # "none" = full bf16 (needs a bigger GPU)
LTX_OFFLOAD = env("UGC_LTX_OFFLOAD", "cpu")                  # cpu | none

FLUX_DIR = Path(env("UGC_FLUX_DIR", str(MODELS_DIR / "flux2-klein-4b")))
FLUX_REPO = env("UGC_FLUX_REPO", "black-forest-labs/FLUX.2-klein-4B")
FLUX_STEPS = int(env("UGC_FLUX_STEPS", "4"))
DIRECTOR_LLM = env("UGC_DIRECTOR_LLM", "Qwen/Qwen3.5-9B")          # script writer (Apache-2.0)
DIRECTOR_4BIT = env("UGC_DIRECTOR_4BIT", "1") == "1"                # NF4: a 9B model in ~6 GB of VRAM
ASR_MODEL = env("UGC_ASR_MODEL", "openai/whisper-large-v3-turbo")
# Arabic speech checks: Qwen3-ASR (Apache-2.0, far better than Whisper on Arabic) as a second opinion next to
# Whisper (which keeps the word timings). UGC_ARABIC_ASR=whisper turns the second opinion off.
ARABIC_ASR = env("UGC_ARABIC_ASR", "Qwen/Qwen3-ASR-1.7B-hf")
PHONEME_MODEL = env("UGC_PHONEME_MODEL", "facebook/wav2vec2-xlsr-53-espeak-cv-ft")
CLIP_MODEL = env("UGC_CLIP_MODEL", "openai/clip-vit-large-patch14")
DINO_MODEL = env("UGC_DINO_MODEL", "facebook/dinov2-base")
TTS_PYTHON = VENDOR_DIR / "tts" / ".venv" / "bin" / "python"
TTS_DESIGN_MODEL = env("UGC_TTS_DESIGN_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
TTS_CLONE_MODEL = env("UGC_TTS_CLONE_MODEL", "Qwen/Qwen3-TTS-12Hz-1.7B-Base")
CHATTERBOX_PYTHON = VENDOR_DIR / "chatterbox" / ".venv" / "bin" / "python"
CHATTERBOX_T3 = env("UGC_CHATTERBOX_T3", "v3")  # Chatterbox Multilingual text-to-token model: v3 | v2
HABIBI_PYTHON = VENDOR_DIR / "habibi" / ".venv" / "bin" / "python"
ACE_DIR = Path(env("UGC_ACE_DIR", str(VENDOR_DIR / "ACE-Step-1.5")))
ACE_PYTHON = ACE_DIR / ".venv" / "bin" / "python"
ACE_CONFIG = env("UGC_ACE_CONFIG", "acestep-v15-turbo")  # acestep-v15-xl-turbo = XL (better audio, ~20 GB download)

# LTX-2.5 distilled: frames must be 8k+1; 121 frames is the trained maximum per generation.
MAX_SHOT_FRAMES = 121
FPS = 24  # default for UGC; promo/TV projects use 25


def ltx_path(component: str) -> Path:
    return LTX_DIR / LTX_FILES[component]


def missing_ltx_files() -> list[str]:
    return [rel for rel in LTX_FILES.values() if not (LTX_DIR / rel).is_file()]


def frames_for_seconds(seconds: float, fps: int = FPS) -> int:
    """Nearest valid LTX frame count (8k+1), clamped to [9, MAX_SHOT_FRAMES]."""
    k = max(1, round(seconds * fps / 8))
    return min(8 * k + 1, MAX_SHOT_FRAMES)


def segment_frames(seconds: float, fps: int) -> list[int]:
    """Split a shot longer than one generation into continuation segments (each 8k+1 frames).
    Segments after the first overlap the previous one by 1 frame (the conditioning frame), which is dropped."""
    total = max(9, round(seconds * fps))
    if total <= MAX_SHOT_FRAMES + 8:  # within 1/3 s of the limit: one generation, not two (e.g. 5 s at 25 fps)
        return [frames_for_seconds(seconds, fps)]
    n = math.ceil((total - 1) / (MAX_SHOT_FRAMES - 1))
    per = (total - 1) / n + 1
    return [min(MAX_SHOT_FRAMES, 8 * max(1, round((per - 1) / 8)) + 1) for _ in range(n)]


@dataclass(frozen=True)
class Resolution:
    width: int
    height: int


# Two-stage LTX pipelines need both sides divisible by 64. "tv" is native 1080p (cropped 1088 -> 1080).
RESOLUTIONS: dict[str, dict[str, Resolution]] = {
    "9:16": {"draft": Resolution(448, 768), "standard": Resolution(576, 1024), "high": Resolution(704, 1280),
             "tv": Resolution(1088, 1920)},
    "16:9": {"draft": Resolution(768, 448), "standard": Resolution(1024, 576), "high": Resolution(1280, 704),
             "tv": Resolution(1920, 1088)},
    "1:1": {"draft": Resolution(576, 576), "standard": Resolution(768, 768), "high": Resolution(1024, 1024),
            "tv": Resolution(1088, 1088)},
    "4:5": {"draft": Resolution(512, 640), "standard": Resolution(768, 960), "high": Resolution(1024, 1280),
            "tv": Resolution(1088, 1344)},
}

# Final delivery canvas per aspect (what the edit outputs).
CANVAS: dict[str, Resolution] = {
    "9:16": Resolution(1080, 1920), "16:9": Resolution(1920, 1080), "1:1": Resolution(1080, 1080),
    "4:5": Resolution(1080, 1350),
}

# Measured on RTX 4000 Ada Laptop 12 GB, fp8-cast + CPU offload, 115 W (seconds per 121-frame shot).
RENDER_SECONDS_ESTIMATE = {"draft": 90, "standard": 180, "high": 260, "tv": 380}


def resolution(aspect: str, quality: str) -> Resolution:
    try:
        return RESOLUTIONS[aspect][quality]
    except KeyError as e:
        raise ValueError(
            f"Unknown aspect/quality {aspect!r}/{quality!r}. "
            f"Aspects: {list(RESOLUTIONS)}; qualities: {list(RESOLUTIONS['9:16'])}"
        ) from e
