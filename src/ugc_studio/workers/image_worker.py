"""Persistent keyframe worker for image models that need newer libraries than the main environment
(Qwen-Image-2.1: diffusers main + transformers >= 5.17). Runs inside vendor/qi21/.venv.

Protocol (JSON lines): the worker prints {"ready": true} once the model is loaded, then for every request line
{"prompt", "width", "height", "seed", "references": [paths], "out": path, "steps"?} it writes the image and prints
{"ok": true, "seconds": s} or {"ok": false, "error": msg}. A line {"quit": true} (or end of input) stops it.

12 GB recipe: transformer from the GGUF Q5_K_M file (5.4 GB, fully on the GPU), the Qwen3-VL-8B text encoder
streamed layer by layer from RAM (group offload), the VAE on the CPU (see vae_on_cpu).
"""

import gc
import json
import os
import sys
import time
import traceback

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def load(gguf: str, repo: str):
    import torch
    from diffusers import (
        GGUFQuantizationConfig,
        QwenImage21Pipeline,
        QwenImage21Transformer2DModel,
    )
    from diffusers.hooks import apply_group_offloading

    cuda, cpu = torch.device("cuda"), torch.device("cpu")
    tr = QwenImage21Transformer2DModel.from_single_file(
        gguf, quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16), config=repo,
        subfolder="transformer", torch_dtype=torch.bfloat16)
    unpack_non_linear(tr)
    pipe = QwenImage21Pipeline.from_pretrained(repo, transformer=tr, torch_dtype=torch.bfloat16)
    pipe.transformer.to(cuda)
    # No CUDA stream prefetch: it records the layer order of the first call, and a later call that uses the vision
    # tower (references) or skips it (text only) then fails with a device mismatch. The encoder runs once per image.
    apply_group_offloading(pipe.text_encoder, onload_device=cuda, offload_device=cpu, offload_type="leaf_level")
    vae_on_cpu(pipe.vae)
    return pipe


def vae_on_cpu(vae) -> None:
    """The VAE runs on the CPU in float32 (~70 s per 1920x1088 image with 61 GB RAM). On the GPU a full TV-size
    decode needs more than 11 GB, and its tiled decode leaves thin pink vertical lines every 192 px (tile blending)."""
    import torch

    vae.to("cpu", torch.float32)
    encode, decode = vae._encode, vae._decode

    def _encode(x):
        return encode(x.to("cpu", torch.float32)).to(x.device, x.dtype)

    def _decode(z, return_dict=True):
        return decode(z.to("cpu", torch.float32), return_dict=return_dict)

    vae._encode, vae._decode = _encode, _decode


def unpack_non_linear(model) -> None:
    """diffusers only dequantizes GGUF weights inside Linear layers. The unsloth file stores txt_in.text_norm as BF16,
    which then reaches the RMSNorm as raw bytes (8192 uint8 for 4096 values): unpack such weights once."""
    import torch
    from diffusers.quantizers.gguf.utils import GGUFParameter, dequantize_gguf_tensor

    for module in model.modules():
        if isinstance(module, torch.nn.Linear):
            continue
        for name, p in list(module.named_parameters(recurse=False)):
            if isinstance(p, GGUFParameter):
                value = dequantize_gguf_tensor(p).to(torch.bfloat16)
                setattr(module, name, torch.nn.Parameter(torch.Tensor(value).as_subclass(torch.Tensor),
                                                         requires_grad=False))


def fit(im, max_pixels: int = 629_146):
    """References at up to ~0.6 MP by default (identity survives; every reference costs attention)."""
    from PIL import Image

    im = im.convert("RGB")
    k = min(1.0, (max_pixels / (im.width * im.height)) ** 0.5)
    size = (max(16, int(im.width * k) // 16 * 16), max(16, int(im.height * k) // 16 * 16))
    return im.resize(size, Image.LANCZOS) if size != im.size else im


# 12 GB budget: the transformer fits ~14k tokens (1 token = 16x16 px), output image and references together. The
# pipeline resizes every reference to output_resolution² pixels (1024² by default: 3 references + a 1920x1088 frame
# = 20k tokens). Tried in order; last resort: render smaller and upscale.
ATTEMPTS = [(0.5, 1.0), (0.3, 1.0), (0.3, 0.75)]  # (megapixels per reference, output scale)


def render(pipe, req: dict):
    import torch
    from PIL import Image

    for k, (ref_mp, scale) in enumerate(ATTEMPTS):
        refs = [fit(Image.open(r), int(ref_mp * 1_048_576)) for r in req.get("references") or []][:10]
        kw = {"image": refs if len(refs) > 1 else refs[0],
              "output_resolution": int((ref_mp * 1_048_576) ** 0.5) // 16 * 16} if refs else {}
        w, h = (int(req["width"] * scale) // 16 * 16, int(req["height"] * scale) // 16 * 16)
        gc.collect()  # a failed attempt's activations must be gone before the next one
        torch.cuda.empty_cache()
        try:
            with torch.inference_mode():
                return pipe(prompt=req["prompt"], width=w, height=h, num_inference_steps=int(req.get("steps") or 24),
                            generator=torch.Generator("cuda").manual_seed(int(req["seed"])), **kw).images[0]
        except torch.OutOfMemoryError:
            if k == len(ATTEMPTS) - 1:
                raise
            print(f"out of memory at refs {ref_mp} MP, scale {scale}: retrying smaller", file=sys.stderr, flush=True)


def main() -> None:
    import torch
    from PIL import Image

    gguf, repo = sys.argv[1], sys.argv[2]
    pipe = load(gguf, repo)
    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        if not line.strip():
            continue
        req = json.loads(line)
        if req.get("quit"):
            break
        t0 = time.time()
        try:
            image = render(pipe, req)
            if image.size != (req["width"], req["height"]):
                image = image.resize((req["width"], req["height"]), Image.LANCZOS)
            image.save(req["out"])
            print(json.dumps({"ok": True, "seconds": round(time.time() - t0, 1)}), flush=True)
        except Exception as e:  # noqa: BLE001 - reported to the caller, the worker keeps running
            traceback.print_exc()
            torch.cuda.empty_cache()
            print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}), flush=True)


if __name__ == "__main__":
    main()
