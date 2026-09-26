"""Keyframe / reference image generation with FLUX.2 [klein] 4B (text-to-image + multi-reference edit)."""

from __future__ import annotations

import gc
import logging
import os
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
from PIL import Image

from ugc_studio.config import FLUX_DIR, FLUX_REPO

log = logging.getLogger(__name__)
REF_MAX_PIXELS = 600_000  # identity survives at ~0.6 MP; every reference adds attention tokens


def keyframe_size(width: int, height: int, megapixels: float = 1.0) -> tuple[int, int]:
    """Exactly the video's aspect at ~`megapixels`, sides multiple of 16 (FLUX latent grid).
    Video sides are multiples of 64, so any scale of n/4 keeps both sides on the 16 grid."""
    target = (megapixels * 1_000_000 / (width * height)) ** 0.5
    n = max(1, round(target * 4))
    return (width * n // 4, height * n // 4)


def _shrink(im: Image.Image, max_pixels: int) -> Image.Image:
    if im.width * im.height <= max_pixels:
        return im
    k = (max_pixels / (im.width * im.height)) ** 0.5
    return im.resize((max(16, int(im.width * k) // 16 * 16), max(16, int(im.height * k) // 16 * 16)), Image.LANCZOS)


class KeyframeGenerator:
    def __init__(self, steps: int = 4, source: str | None = None):
        from diffusers import Flux2KleinPipeline

        # `source`: another FLUX.2 klein checkpoint (HF repo id or local folder), e.g. from UGC_IMAGE_MODEL
        source = source or (str(FLUX_DIR) if (FLUX_DIR / "model_index.json").is_file() else FLUX_REPO)
        if "9b" in str(source).lower() and os.environ.get("UGC_ALLOW_NONCOMMERCIAL") != "1":
            raise RuntimeError(f"{source}: FLUX.2 klein 9B weights are licensed for non-commercial use only. Use the "
                               "4B (Apache-2.0), or set UGC_ALLOW_NONCOMMERCIAL=1 for research/personal use.")
        log.info("Loading FLUX.2 klein from %s", source)
        self.pipe = Flux2KleinPipeline.from_pretrained(source, dtype=torch.bfloat16)
        # 4B transformer + Qwen3 text encoder do not fit 12 GB together; offload per component.
        self.pipe.enable_model_cpu_offload()
        self.steps = steps

    @torch.inference_mode()
    def generate(
        self,
        prompt: str,
        width: int,
        height: int,
        seed: int,
        references: list[str | Path] | None = None,
        out_path: str | Path | None = None,
    ) -> Image.Image:
        refs_full = [Image.open(r).convert("RGB") for r in references or []]
        # Degrade gracefully under memory pressure: smaller references, then fewer, instead of crashing.
        attempts = [(REF_MAX_PIXELS, len(refs_full)), (REF_MAX_PIXELS // 2, len(refs_full)),
                    (REF_MAX_PIXELS // 2, min(2, len(refs_full))), (REF_MAX_PIXELS // 3, min(1, len(refs_full)))]
        last_err = None
        for max_px, n in attempts:
            refs = [_shrink(r, max_px) for r in refs_full[:n]]
            try:
                image = self.pipe(
                    prompt=prompt,
                    image=refs or None,
                    width=width,
                    height=height,
                    num_inference_steps=self.steps,
                    guidance_scale=1.0,
                    generator=torch.Generator("cpu").manual_seed(seed),
                ).images[0]
                break
            except torch.OutOfMemoryError as e:
                last_err = e
                log.warning("FLUX out of memory with %d refs @ %d px: retrying lighter", n, max_px)
                gc.collect()
                torch.cuda.empty_cache()
        else:
            raise RuntimeError(f"FLUX out of memory even with minimal references: {last_err}")
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            image.save(out_path)
        return image

    def close(self) -> None:
        del self.pipe
        gc.collect()
        torch.cuda.empty_cache()
