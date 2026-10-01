"""Local open-source backends (default): FLUX.2 klein images, LTX-2.5 video (render.ShotRenderer), ACE-Step music.
Narration engines (Qwen3-TTS, Chatterbox, Habibi) run in their own environments, driven by voice.py.
Checkpoints are chosen with UGC_* variables (config.py / .env.example)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ugc_studio.config import ACE_CONFIG, ACE_DIR, ACE_PYTHON, FLUX_STEPS, ROOT
from ugc_studio.providers.base import ImageBackend, MusicBackend, ProviderError


def _cached(repo: str, filename: str) -> str | None:
    """Path of a file already in the Hugging Face cache (no download), else None."""
    from huggingface_hub import try_to_load_from_cache

    p = try_to_load_from_cache(repo, filename)
    return p if isinstance(p, str) else None


def _fit(im, max_pixels: int = 1_048_576):
    """Reference images at ~1 MP, sides on the 16-pixel grid (edit models work in 16-px patches)."""
    from PIL import Image

    im = im.convert("RGB")
    k = min(1.0, (max_pixels / (im.width * im.height)) ** 0.5)
    w, h = max(16, int(im.width * k) // 16 * 16), max(16, int(im.height * k) // 16 * 16)
    return im.resize((w, h), Image.LANCZOS) if (w, h) != im.size else im


class FluxImage(ImageBackend):
    """FLUX.2 klein 4B (Apache-2.0): fast text-to-image and multi-reference edits. The safe fallback."""

    name = "local (FLUX.2 klein)"

    def __init__(self, model: str | None = None, steps: int = FLUX_STEPS):
        from ugc_studio.keyframes import KeyframeGenerator

        self.g = KeyframeGenerator(steps=steps, source=model)

    def generate(self, prompt, width, height, seed, references=None, out_path=None):
        return self.g.generate(prompt, width, height, seed, references=references, out_path=out_path)

    def close(self) -> None:
        self.g.close()


class QwenEditImage(ImageBackend):
    """Qwen-Image-Edit-2511 (20B, Apache-2.0): multi-reference editing with strong identity consistency.
    12 GB recipe: GGUF Q4_K_M transformer + Lightning 4-step LoRA (Apache-2.0), text encoder and transformer streamed
    block by block from RAM (group offload). About a minute per keyframe instead of ~15 at 40 steps."""

    name = "local (Qwen-Image-Edit-2511)"
    REPO = "Qwen/Qwen-Image-Edit-2511"
    GGUF = ("unsloth/Qwen-Image-Edit-2511-GGUF", "qwen-image-edit-2511-Q4_K_M.gguf")
    LORA = ("lightx2v/Qwen-Image-Edit-2511-Lightning", "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors")

    @classmethod
    def available(cls) -> bool:
        return bool(cls._gguf_path() and _cached(*cls.LORA) and _cached(cls.REPO, "text_encoder/config.json"))

    @classmethod
    def _gguf_path(cls) -> str | None:
        import os

        custom = os.environ.get("UGC_QWEN_EDIT_GGUF", "").strip()
        if custom:
            return custom
        from huggingface_hub import scan_cache_dir

        try:
            for repo in scan_cache_dir().repos:
                if repo.repo_id == cls.GGUF[0]:
                    for rev in repo.revisions:
                        for f in rev.files:
                            if f.file_name.lower().endswith("q4_k_m.gguf"):
                                return str(f.file_path)
        except Exception:  # noqa: BLE001 - no cache yet
            return None
        return None

    def __init__(self, model: str | None = None):
        import math

        import torch
        from diffusers import (FlowMatchEulerDiscreteScheduler, GGUFQuantizationConfig, QwenImageEditPlusPipeline,
                               QwenImageTransformer2DModel)
        from diffusers.hooks import apply_group_offloading

        gguf = model or self._gguf_path()
        if not gguf:
            raise ProviderError("Qwen-Image-Edit-2511 weights missing: run `ugc models download --only qwen-edit`.")
        cuda, cpu = torch.device("cuda"), torch.device("cpu")
        # Lightning's official scheduler settings (4 steps, no CFG)
        sched = FlowMatchEulerDiscreteScheduler.from_config({
            "base_image_seq_len": 256, "base_shift": math.log(3), "invert_sigmas": False, "max_image_seq_len": 8192,
            "max_shift": math.log(3), "num_train_timesteps": 1000, "shift": 1.0, "shift_terminal": None,
            "stochastic_sampling": False, "time_shift_type": "exponential", "use_beta_sigmas": False,
            "use_dynamic_shifting": True, "use_exponential_sigmas": False, "use_karras_sigmas": False})
        # config= is required: the 2511 transformer config (zero_cond_t) is not inferable from the GGUF file
        tr = QwenImageTransformer2DModel.from_single_file(
            gguf, quantization_config=GGUFQuantizationConfig(compute_dtype=torch.bfloat16), config=self.REPO,
            subfolder="transformer", torch_dtype=torch.bfloat16)
        self.pipe = QwenImageEditPlusPipeline.from_pretrained(self.REPO, transformer=tr, scheduler=sched,
                                                              torch_dtype=torch.bfloat16)
        self.pipe.load_lora_weights(self.LORA[0], weight_name=self.LORA[1])
        tr.enable_group_offload(onload_device=cuda, offload_device=cpu, offload_type="block_level",
                                num_blocks_per_group=1, use_stream=True, low_cpu_mem_usage=True)
        # the text encoder (Qwen2.5-VL, 16 GB) nests its layers below `model.`: block-level offload would see one
        # single block and move everything to the GPU at once; leaf-level streams it layer by layer
        apply_group_offloading(self.pipe.text_encoder, onload_device=cuda, offload_device=cpu,
                               offload_type="leaf_level", use_stream=True, low_cpu_mem_usage=True)
        self.pipe.vae.enable_group_offload(onload_device=cuda, offload_type="leaf_level")
        self.torch = torch

    def generate(self, prompt, width, height, seed, references=None, out_path=None):
        from PIL import Image

        refs = [_fit(Image.open(r)) for r in (references or [])][:4]
        if not refs:
            raise ProviderError("Qwen-Image-Edit needs at least one reference image")
        with self.torch.inference_mode():
            image = self.pipe(image=refs, prompt=prompt, negative_prompt=" ", true_cfg_scale=1.0,
                              num_inference_steps=4, width=width, height=height,
                              generator=self.torch.Generator("cpu").manual_seed(seed)).images[0]
        if image.size != (width, height):
            image = image.resize((width, height), Image.LANCZOS)
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            image.save(out_path)
        return image

    def close(self) -> None:
        import gc

        del self.pipe
        gc.collect()
        self.torch.cuda.empty_cache()


class ZImageImage(ImageBackend):
    """Z-Image Turbo (6B, Apache-2.0): photoreal text-to-image in 8 steps (no reference images).
    12 GB recipe: transformer stored in fp8 (layerwise casting), components offloaded between uses."""

    name = "local (Z-Image Turbo)"
    supports_references = False
    REPO = "Tongyi-MAI/Z-Image-Turbo"

    @classmethod
    def available(cls) -> bool:
        return bool(_cached(cls.REPO, "transformer/config.json") and _cached(cls.REPO, "model_index.json"))

    def __init__(self, model: str | None = None):
        import torch
        from diffusers import ZImagePipeline

        self.torch = torch
        self.pipe = ZImagePipeline.from_pretrained(model or self.REPO, torch_dtype=torch.bfloat16,
                                                   low_cpu_mem_usage=False)
        self.pipe.transformer.enable_layerwise_casting(storage_dtype=torch.float8_e4m3fn,
                                                       compute_dtype=torch.bfloat16)
        self.pipe.enable_model_cpu_offload()

    def generate(self, prompt, width, height, seed, references=None, out_path=None):
        with self.torch.inference_mode():
            image = self.pipe(prompt=prompt, width=width, height=height, num_inference_steps=9, guidance_scale=0.0,
                              generator=self.torch.Generator("cuda").manual_seed(seed)).images[0]
        if out_path:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            image.save(out_path)
        return image

    def close(self) -> None:
        import gc

        del self.pipe
        gc.collect()
        self.torch.cuda.empty_cache()


class Qwen21Image(ImageBackend):
    """Qwen-Image-2.1 (best open image model for generation and multi-reference editing, up to 10 references).
    Needs newer diffusers/transformers than the main environment: runs as a persistent worker in vendor/qi21
    (loaded once per keyframe batch). Research license: personal use."""

    name = "local (Qwen-Image-2.1)"
    supports_references = True
    REPO = "Qwen/Qwen-Image-2.1"
    GGUF_REPO = "unsloth/Qwen-Image-2.1-GGUF"
    WORKER = Path(__file__).resolve().parents[1] / "workers" / "image_worker.py"

    @classmethod
    def python(cls) -> Path:
        from ugc_studio.config import VENDOR_DIR

        return VENDOR_DIR / "qi21" / ".venv" / "bin" / "python"

    @classmethod
    def _gguf(cls) -> str | None:
        import os

        custom = (os.environ.get("UGC_QWEN21_GGUF") or "").strip()
        if custom:
            return custom
        from huggingface_hub import scan_cache_dir

        quant = (os.environ.get("UGC_QWEN21_QUANT") or "Q5_K_M").lower()
        try:
            for repo in scan_cache_dir().repos:
                if repo.repo_id == cls.GGUF_REPO:
                    for rev in repo.revisions:
                        for f in rev.files:
                            if f.file_name.lower().endswith(f"{quant}.gguf"):
                                return str(f.file_path)
        except Exception:  # noqa: BLE001
            return None
        return None

    @classmethod
    def available(cls) -> bool:
        return bool(cls.python().is_file() and cls._gguf() and _cached(cls.REPO, "text_encoder/config.json"))

    def __init__(self, model: str | None = None, steps: int | None = None):
        import os

        gguf = model or self._gguf()
        if not gguf or not self.python().is_file():
            raise ProviderError("Qwen-Image-2.1 is not installed: `ugc setup` then `ugc models download --only qwen21`.")
        self.steps = steps or int(os.environ.get("UGC_QWEN21_STEPS") or 24)
        import tempfile

        self.log = Path(tempfile.gettempdir()) / "ugc-qwen21-worker.log"
        with self.log.open("w") as err:
            self.proc = subprocess.Popen([str(self.python()), str(self.WORKER), gguf, self.REPO],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1)
        ready = self._read()
        if not ready.get("ready"):
            raise ProviderError(f"Qwen-Image-2.1 worker failed to start: {ready}")

    def _read(self) -> dict:
        while True:
            line = self.proc.stdout.readline()
            if not line:
                code = self.proc.wait(timeout=30)
                tail = self.log.read_text(errors="replace").strip().splitlines()[-3:]
                raise ProviderError(f"Qwen-Image-2.1 worker stopped (exit code {code}): {' | '.join(tail)}")
            line = line.strip()
            if line.startswith("{"):
                return json.loads(line)

    def generate(self, prompt, width, height, seed, references=None, out_path=None):
        from PIL import Image

        out = Path(out_path) if out_path else Path(f"/tmp/qi21_{seed}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        self.proc.stdin.write(json.dumps({"prompt": prompt, "width": width // 16 * 16, "height": height // 16 * 16,
                                          "seed": seed, "references": [str(r) for r in references or []],
                                          "out": str(out), "steps": self.steps}) + "\n")
        self.proc.stdin.flush()
        res = self._read()
        if not res.get("ok"):
            raise ProviderError(f"Qwen-Image-2.1: {res.get('error')}")
        im = Image.open(out)
        if im.size != (width, height):
            im = im.resize((width, height), Image.LANCZOS)
            im.save(out)
        return im

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps({"quit": True}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(timeout=60)
            except Exception:  # noqa: BLE001
                self.proc.kill()


class LocalImage(ImageBackend):
    """Local keyframes, best engine per frame:
      any frame                                   -> Qwen-Image-2.1 when installed (generation + editing)
      with references (a person/product to keep)  -> else Qwen-Image-Edit-2511 when downloaded, else FLUX.2 klein
      without references                          -> else Z-Image Turbo when downloaded, else FLUX.2 klein
    UGC_KEYFRAME_EDIT (qwen-edit | flux) and UGC_KEYFRAME_T2I (zimage | flux) force a choice. `model` = a FLUX.2
    klein checkpoint (UGC_IMAGE_MODEL). One engine is loaded at a time (they don't fit in RAM together)."""

    name = "local"

    def __init__(self, model: str | None = None, steps: int = FLUX_STEPS):
        import os

        self.flux_model, self.steps = model, steps
        best = "qwen21" if Qwen21Image.available() else None  # one engine for every frame: no reloads
        edit = (os.environ.get("UGC_KEYFRAME_EDIT", "").strip() or best
                or ("qwen-edit" if QwenEditImage.available() else "flux"))
        t2i = (os.environ.get("UGC_KEYFRAME_T2I", "").strip() or best
               or ("zimage" if ZImageImage.available() else "flux"))
        self.route = {"refs": edit, "text": t2i}
        self.engine, self.g = None, None
        self.name = f"local ({edit} for references, {t2i} for text)"

    def _use(self, engine: str) -> ImageBackend:
        if engine != self.engine:
            if self.g is not None:
                self.g.close()
            cls = {"qwen21": Qwen21Image, "qwen-edit": QwenEditImage, "zimage": ZImageImage}.get(engine)
            self.g = cls() if cls else FluxImage(self.flux_model, self.steps)
            self.engine = engine
        return self.g

    def generate(self, prompt, width, height, seed, references=None, out_path=None):
        engine = self.route["refs"] if references else self.route["text"]
        return self._use(engine).generate(prompt, width, height, seed, references=references, out_path=out_path)

    def close(self) -> None:
        if self.g is not None:
            self.g.close()
            self.g, self.engine = None, None


class AceMusic(MusicBackend):
    name = "local (ACE-Step 1.5)"
    WORKER = Path(__file__).resolve().parents[1] / "workers" / "music_worker.py"

    def __init__(self, model: str | None = None):
        self.config = model or ACE_CONFIG  # UGC_MUSIC_MODEL / UGC_ACE_CONFIG, e.g. acestep-v15-xl-turbo
        if not ACE_PYTHON.is_file():
            raise ProviderError(f"Music environment missing ({ACE_PYTHON}). Run `ugc setup` or set music.mode: none.")

    def generate(self, caption, seconds, bpm, seed, candidates, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        job = {"ace_dir": str(ACE_DIR), "caption": caption, "seconds": seconds, "bpm": bpm, "candidates": candidates,
               "seed": seed, "out_dir": str(out_dir), "config": self.config}
        jp = out_dir / "job.json"
        jp.write_text(json.dumps(job))
        proc = subprocess.run([str(ACE_PYTHON), str(self.WORKER), str(jp)], capture_output=True, text=True, cwd=ROOT)
        if proc.returncode != 0:
            raise ProviderError(f"Music worker failed:\n{proc.stderr[-3000:]}")



class StableAudioMusic(MusicBackend):
    name = "local (Stable Audio 3 Medium)"
    WORKER = Path(__file__).resolve().parents[1] / "workers" / "sa3_worker.py"

    @classmethod
    def available(cls) -> bool:
        from ugc_studio.config import SA3_PYTHON, SA3_REPO, STABLE_AUDIO

        return bool(STABLE_AUDIO and SA3_PYTHON.is_file() and _cached(SA3_REPO, "model.safetensors"))

    def generate(self, caption, seconds, bpm, seed, candidates, out_dir, first: int = 0):
        from ugc_studio.config import SA3_PYTHON

        out_dir.mkdir(parents=True, exist_ok=True)
        jp = out_dir / "job_sa3.json"
        jp.write_text(json.dumps({"caption": caption, "seconds": seconds, "bpm": bpm, "candidates": candidates,
                                  "seed": seed, "out_dir": str(out_dir), "first": first}))
        proc = subprocess.run([str(SA3_PYTHON), str(self.WORKER), str(jp)], capture_output=True, text=True, cwd=ROOT)
        if proc.returncode != 0:
            raise ProviderError(f"Stable Audio worker failed:\n{proc.stderr[-3000:]}")


class LocalMusic(MusicBackend):
    """ACE-Step candidates, plus Stable Audio 3 candidates when installed: on 4 briefs each engine won some
    (Stable Audio: calm/news and pop; ACE-Step: trap), so both compete and music.score keeps the best."""

    def __init__(self, model: str | None = None):
        self.ace = AceMusic(model)
        self.sa3 = StableAudioMusic() if StableAudioMusic.available() else None
        self.name = self.ace.name + (" + Stable Audio 3" if self.sa3 else "")

    def generate(self, caption, seconds, bpm, seed, candidates, out_dir):
        self.ace.generate(caption, seconds, bpm, seed, candidates, out_dir)
        if self.sa3:
            self.sa3.generate(caption, seconds, bpm, seed, candidates, out_dir, first=len(list(out_dir.glob("cand*.wav"))))