"""LTX-2.5 distilled: shot generation (start/end keyframes, long-shot continuation) and time-window retakes."""

from __future__ import annotations

import gc
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch

from ugc_studio.config import FPS, ltx_path, missing_ltx_files
from ugc_studio.media import extract_frame

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageCondition:
    path: str
    frame_idx: int = 0  # 0 = first frame; num_frames-1 = land exactly on this image at the end
    strength: float = 1.0


def _model_paths():
    from ltx_pipelines.utils.model_paths import ModelPaths

    return ModelPaths.from_split(
        transformer_path=str(ltx_path("transformer")),
        text_encoder_path=str(ltx_path("text_encoder")),
        video_vae_path=str(ltx_path("video_vae")),
        audio_vae_path=str(ltx_path("audio_vae")),
    )


def _policy(quantization: str | None):
    from ltx_pipelines.utils.quantization_factory import QuantizationKind

    return QuantizationKind(quantization).to_policy(checkpoint_path=str(ltx_path("transformer"))) if quantization else None


def _check_models() -> None:
    missing = missing_ltx_files()
    if missing:
        raise FileNotFoundError(f"LTX-2.5 weights missing: {missing}. Run `ugc models download`.")


def _free() -> None:
    gc.collect()
    torch.cuda.empty_cache()


class ShotRenderer:
    """DistilledPipeline built once and reused for every shot (FP8-cast weights streamed from CPU RAM)."""

    def __init__(self, offload: str = "cpu", quantization: str | None = "fp8-cast"):
        _check_models()
        from ltx_pipelines.distilled import DistilledPipeline
        from ltx_pipelines.utils.types import OffloadMode

        self.pipeline = DistilledPipeline(
            model_paths=_model_paths(),
            spatial_upsampler_path=str(ltx_path("spatial_upsampler")),
            loras=[],
            quantization=_policy(quantization),
            offload_mode=OffloadMode(offload),
        )

    @torch.inference_mode()
    def render(self, prompt: str, out_path: str | Path, width: int, height: int, num_frames: int, seed: int,
               images: list[ImageCondition] | None = None, fps: int = FPS) -> Path:
        from ltx_core.model.video_vae import AUTO_TILING, get_video_chunks_number
        from ltx_pipelines.utils.args import ImageConditioningInput
        from ltx_pipelines.utils.media_io import encode_video

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        conds = [ImageConditioningInput(c.path, min(c.frame_idx, num_frames - 1), c.strength) for c in images or []]
        t0 = time.time()
        result = self.pipeline(prompt=prompt, seed=seed, height=height, width=width, num_frames=num_frames,
                               frame_rate=float(fps), images=conds, tiling_config=AUTO_TILING)
        tmp = out_path.with_suffix(".partial.mp4")
        encode_video(video=result.video, fps=fps, audio=result.audio, output_path=str(tmp),
                     video_chunks_number=get_video_chunks_number(result.num_frames, result.tiling_config))
        os.replace(tmp, out_path)  # atomic: an interrupted render never leaves a "valid-looking" clip
        log.info("Rendered %s (%d frames %dx%d) in %.1fs", out_path.name, num_frames, width, height, time.time() - t0)
        del result
        _free()
        return out_path

    def render_long(self, prompt: str, out_path: str | Path, width: int, height: int, segments: list[int], seed: int,
                    images: list[ImageCondition], fps: int, workdir: Path) -> Path:
        """Shot longer than one generation: each segment continues from the previous segment's last frame.
        An end keyframe (frame_idx > 0) applies to the last segment only."""
        from ugc_studio.media import ffmpeg

        start = [c for c in images if c.frame_idx == 0]
        end = [c for c in images if c.frame_idx > 0]
        parts = []
        for k, n in enumerate(segments):
            conds = list(start) if k == 0 else [ImageCondition(str(extract_frame(parts[-1], workdir / f"seg{k}_in.png")))]
            if k == len(segments) - 1:
                conds += [ImageCondition(c.path, n - 1, c.strength) for c in end]
            part = workdir / f"seg{k}.mp4"
            self.render(prompt, part, width, height, n, seed + k, conds, fps)
            parts.append(part)
        # Join: drop the duplicated first frame of every continuation segment.
        inputs, chains = [], []
        for k, p in enumerate(parts):
            inputs += ["-i", str(p)]
            d = 1 if k else 0
            chains.append(f"[{k}:v]trim=start_frame={d},setpts=PTS-STARTPTS[v{k}];"
                          f"[{k}:a]atrim=start={d / fps:.5f},asetpts=PTS-STARTPTS[a{k}]")
        cat = "".join(f"[v{k}][a{k}]" for k in range(len(parts)))
        ffmpeg([*inputs, "-filter_complex", ";".join(chains) + f";{cat}concat=n={len(parts)}:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "12", "-preset", "medium", "-c:a", "aac",
                "-b:a", "256k", str(out_path)])
        return Path(out_path)

    def close(self) -> None:
        del self.pipeline
        _free()


class RetakeRenderer:
    """Regenerates only [start, end] of an existing clip; everything outside the window is preserved."""

    def __init__(self, offload: str = "cpu", quantization: str | None = "fp8-cast"):
        _check_models()
        from ltx_pipelines.retake import RetakePipeline
        from ltx_pipelines.utils.types import OffloadMode

        self.pipeline = RetakePipeline(model_paths=_model_paths(), loras=(), quantization=_policy(quantization),
                                       distilled=True, offload_mode=OffloadMode(offload))

    @torch.inference_mode()
    def retake(self, src: str | Path, out_path: str | Path, prompt: str, start: float, end: float, seed: int,
               video: bool = True, audio: bool = False) -> Path:
        from ltx_core.model.video_vae import AUTO_TILING, get_video_chunks_number
        from ltx_pipelines.utils.constants import detect_params
        from ltx_pipelines.utils.media_io import encode_video, get_videostream_metadata

        meta = get_videostream_metadata(str(src))
        params = detect_params(str(ltx_path("transformer")))
        result = self.pipeline(video_path=str(src), prompt=prompt, start_time=start, end_time=end, seed=seed,
                               video_guider_params=params.video_guider_params,
                               audio_guider_params=params.audio_guider_params, regenerate_video=video,
                               regenerate_audio=audio, tiling_config=AUTO_TILING)
        tmp = Path(out_path).with_suffix(".partial.mp4")
        encode_video(video=result.video, fps=int(round(meta.fps)), audio=result.audio, output_path=str(tmp),
                     video_chunks_number=get_video_chunks_number(result.num_frames, result.tiling_config))
        os.replace(tmp, out_path)
        del result
        _free()
        return Path(out_path)

    def close(self) -> None:
        del self.pipeline
        _free()
