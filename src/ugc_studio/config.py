"""Paths, model registry and render presets."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(os.environ.get("UGC_ROOT", Path(__file__).resolve().parents[2]))


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines); real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv(ROOT / ".env")

MODELS_DIR = Path(os.environ.get("UGC_MODELS", ROOT / "models"))
OUTPUTS_DIR = Path(os.environ.get("UGC_OUTPUTS", ROOT / "outputs"))
VENDOR_DIR = ROOT / "vendor"
MOTION_DIR = Path(__file__).parent / "motion"

LTX_DIR = MODELS_DIR / "ltx-2.5"
LTX_REPO = "Lightricks/LTX-2.5"
LTX_FILES = {
    "transformer": "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors",
    "text_encoder": "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors",
    "video_vae": "vae/ltx-2.5-video-vae-bf16.safetensors",
    "audio_vae": "vae/ltx-2.5-audio-vae-bf16.safetensors",
    "spatial_upsampler": "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors",
}

FLUX_DIR = MODELS_DIR / "flux2-klein-4b"
FLUX_REPO = "black-forest-labs/FLUX.2-klein-4B"
DIRECTOR_LLM = os.environ.get("UGC_DIRECTOR_LLM", "Qwen/Qwen3-4B-Instruct-2507")
ASR_MODEL = "openai/whisper-large-v3-turbo"
TTS_PYTHON = VENDOR_DIR / "tts" / ".venv" / "bin" / "python"
TTS_DESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
TTS_CLONE_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
CHATTERBOX_PYTHON = VENDOR_DIR / "chatterbox" / ".venv" / "bin" / "python"
HABIBI_PYTHON = VENDOR_DIR / "habibi" / ".venv" / "bin" / "python"
ACE_DIR = VENDOR_DIR / "ACE-Step-1.5"
ACE_PYTHON = ACE_DIR / ".venv" / "bin" / "python"

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
