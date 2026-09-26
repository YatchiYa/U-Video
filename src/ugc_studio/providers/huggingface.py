"""Hugging Face Inference Providers (router.huggingface.co): text-to-image with any hosted model.

Auth: HF_TOKEN with the "Inference Providers" permission. Route: UGC_HF_PROVIDER = hf-inference (default, raw
image bytes) or fal-ai (JSON with an image URL). Docs: huggingface.co/docs/inference-providers (checked 2026-09-25).
Find which providers serve a model: https://huggingface.co/api/models/<id>?expand[]=inferenceProviderMapping
"""

from __future__ import annotations

import os

from ugc_studio.providers.base import ImageBackend, ProviderError, check, client, need_key, save_image_bytes

ROUTER = "https://router.huggingface.co"


class HFImage(ImageBackend):
    name = "huggingface"
    supports_references = False  # plain text-to-image: identity comes from the prompt only

    def __init__(self, model: str | None = None):
        self.model = model or "black-forest-labs/FLUX.1-schnell"
        self.route = os.environ.get("UGC_HF_PROVIDER", "").strip() or "hf-inference"

    def generate(self, prompt, width, height, seed, references=None, out_path=None):
        auth = {"Authorization": f"Bearer {need_key('HF_TOKEN', 'Hugging Face')}"}
        w, h = width // 16 * 16, height // 16 * 16
        with client(timeout=300) as c:
            if self.route == "hf-inference":
                r = check(c.post(f"{ROUTER}/hf-inference/models/{self.model}", headers=auth,
                                 json={"inputs": prompt, "parameters": {"width": w, "height": h, "seed": seed}}),
                          "Hugging Face")
                data = r.content
            elif self.route == "fal-ai":  # model = the fal id from inferenceProviderMapping
                j = check(c.post(f"{ROUTER}/fal-ai/{self.model}", headers=auth,
                                 json={"prompt": prompt, "image_size": {"width": w, "height": h}, "seed": seed}),
                          "Hugging Face").json()
                data = check(c.get(j["images"][0]["url"]), "Hugging Face").content
            else:
                raise ProviderError(f"UGC_HF_PROVIDER={self.route!r} is not supported (hf-inference, fal-ai)")
        return save_image_bytes(data, width, height, out_path)
