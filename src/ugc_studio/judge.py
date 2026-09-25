"""Visual judges (CPU, so they never compete with the generators for VRAM).

  prompt_score(image, text)      CLIP ViT-L/14 image-text similarity: does the frame show what was asked?
  identity_score(image, refs)    DINOv2 feature similarity to reference photos: is it the same person/cat/product?
  clip_checks(video)             per-shot technical checks (black, frozen, identity drift)

Scores are used relatively (best-of-N) and with conservative absolute floors calibrated on real renders.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

CLIP_MODEL = "openai/clip-vit-large-patch14"
IDENTITY_MIN = 0.20  # calibrated: same subject 0.36-0.57, different subject 0.00-0.05
PROMPT_MIN = 18.0  # calibrated: matching image 26-35, unrelated image ~6
DINO_MODEL = "facebook/dinov2-base"


@lru_cache(maxsize=1)
def _clip():
    import torch
    from transformers import CLIPModel, CLIPProcessor

    torch.set_num_threads(max(4, (torch.get_num_threads() or 8)))
    return CLIPProcessor.from_pretrained(CLIP_MODEL), CLIPModel.from_pretrained(CLIP_MODEL).eval()


@lru_cache(maxsize=1)
def _dino():
    from transformers import AutoImageProcessor, AutoModel

    return AutoImageProcessor.from_pretrained(DINO_MODEL), AutoModel.from_pretrained(DINO_MODEL).eval()


def _img(x) -> Image.Image:
    return x.convert("RGB") if isinstance(x, Image.Image) else Image.open(x).convert("RGB")


def prompt_score(image, text: str) -> float:
    """Cosine similarity (x100) between the image and the first 77 tokens of the text."""
    import torch

    proc, model = _clip()
    with torch.inference_mode():
        inp = proc(text=[text], images=[_img(image)], return_tensors="pt", padding="max_length", truncation=True)
        out = model(**inp)
        a = out.image_embeds / out.image_embeds.norm(dim=-1, keepdim=True)
        b = out.text_embeds / out.text_embeds.norm(dim=-1, keepdim=True)
    return float((a * b).sum()) * 100


def _dino_feats(images: list) -> np.ndarray:
    import torch

    proc, model = _dino()
    with torch.inference_mode():
        out = model(**proc(images=[_img(i) for i in images], return_tensors="pt"))
        f = out.pooler_output
        f = f / f.norm(dim=-1, keepdim=True)
    return f.numpy()


def identity_score(image, refs: list) -> float:
    """Max cosine similarity (0-1) between the image and any reference (DINOv2 global features)."""
    if not refs:
        return 1.0
    f = _dino_feats([image, *refs])
    return float((f[1:] @ f[0]).max())


def best_of(candidates: list, prompt: str, refs: list, w_identity: float = 40.0) -> tuple[int, list[dict]]:
    """Rank candidate images: prompt adherence + identity to references. Returns (best index, scores)."""
    scores = []
    for c in candidates:
        p = prompt_score(c, prompt)
        i = identity_score(c, refs) if refs else None
        scores.append({"prompt": round(p, 2), "identity": None if i is None else round(i, 3),
                       "total": round(p + (w_identity * i if i is not None else 0), 2)})
    return int(np.argmax([s["total"] for s in scores])), scores


def sample_video(path: str | Path, n: int = 8) -> list[Image.Image]:
    import av

    with av.open(str(path)) as c:
        frames = [f.to_image() for f in c.decode(video=0)]
    idx = np.linspace(0, len(frames) - 1, min(n, len(frames))).round().astype(int)
    return [frames[i] for i in idx]


def clip_checks(path: str | Path, refs: list | None = None) -> dict:
    """Per-shot checks right after generation: black / frozen video and identity drift along the shot."""
    import av

    lum, diffs, prev = [], [], None
    with av.open(str(path)) as c:
        for f in c.decode(video=0):
            g = np.asarray(f.to_image().convert("L").resize((96, 170)), dtype=np.float32)
            lum.append(g.mean())
            if prev is not None:
                diffs.append(float(np.abs(g - prev).mean()))
            prev = g
    issues = []
    lum = np.array(lum)
    if (lum < 12).mean() > 0.05:
        issues.append(f"{int((lum < 12).sum())} black frames")
    if diffs and np.percentile(diffs, 90) < 0.25:
        issues.append("almost no motion (frozen shot)")
    ident = None
    if refs:
        frames = sample_video(path, 5)
        f = _dino_feats([*frames, *refs])
        k = len(frames)
        per = (f[:k] @ f[k:].T).max(1)
        ident = [round(float(x), 3) for x in per]
        if min(per) < IDENTITY_MIN:
            issues.append(f"identity drift (similarity {min(per):.2f})")
    return {"ok": not issues, "issues": issues, "identity": ident}
