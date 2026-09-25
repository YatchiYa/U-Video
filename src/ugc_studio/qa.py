"""Automatic quality analysis of a rendered video: technical checks, audio, speech accuracy, contact sheets."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import av
import numpy as np
from PIL import Image, ImageDraw

from ugc_studio.media import FFMPEG

log = logging.getLogger(__name__)


@dataclass
class Issue:
    level: str  # "fail" | "warn"
    check: str
    detail: str


@dataclass
class Report:
    path: str
    duration_s: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    frames: int = 0
    has_audio: bool = False
    audio_sample_rate: int = 0
    integrated_lufs: float | None = None
    true_peak_dbfs: float | None = None
    clipping_ratio: float = 0.0
    silence_ratio: float = 0.0
    mean_luma: float = 0.0
    sharpness_median: float = 0.0
    motion_median: float = 0.0
    cuts_s: list[float] = field(default_factory=list)
    black_frames: int = 0
    frozen_spans_s: list[tuple[float, float]] = field(default_factory=list)
    flicker_frames: int = 0
    transcript: str | None = None
    speech_similarity: float | None = None
    contact_sheet: str | None = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if any(i.level == "fail" for i in self.issues):
            return "FAIL"
        return "WARN" if self.issues else "PASS"

    def to_json(self) -> str:
        d = asdict(self)
        d["verdict"] = self.verdict
        return json.dumps(d, indent=2)


def _gray_small(frame: av.VideoFrame, width: int = 192) -> np.ndarray:
    h = max(1, round(frame.height * width / frame.width))
    return np.asarray(frame.to_image().convert("L").resize((width, h), Image.BILINEAR), dtype=np.float32)


def _laplacian_var(g: np.ndarray) -> float:
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def _loudness(path: str) -> tuple[float | None, float | None]:
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    summary = proc.stderr.rsplit("Summary:", 1)[-1]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    return (float(i.group(1)) if i else None, float(tp.group(1)) if tp else None)


def _normalize_words(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split())


def transcribe(path: str | Path, model: str = "openai/whisper-large-v3-turbo") -> str:
    import torch
    from transformers import pipeline

    asr = pipeline(
        "automatic-speech-recognition",
        model=model,
        torch_dtype=torch.float16,
        device="cuda" if torch.cuda.is_available() else "cpu",
    )
    audio = _decode_audio(str(path), 16000)
    if audio is None:
        return ""
    out = asr({"raw": audio.mean(axis=0), "sampling_rate": 16000}, return_timestamps=True)
    del asr
    torch.cuda.empty_cache()
    return out["text"].strip()


def _decode_audio(path: str, rate: int | None = None) -> np.ndarray | None:
    with av.open(path) as c:
        if not c.streams.audio:
            return None
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=rate or c.streams.audio[0].rate)
        chunks = []
        for frame in c.decode(audio=0):
            for rf in resampler.resample(frame):
                chunks.append(rf.to_ndarray())
        for rf in resampler.resample(None):
            chunks.append(rf.to_ndarray())
    return np.concatenate(chunks, axis=1) if chunks else None


def contact_sheet(path: str | Path, out_png: str | Path, every_s: float = 1.0, cols: int = 5, thumb_w: int = 216) -> Path:
    """Grid of frames sampled every `every_s` seconds, stamped with their timestamp."""
    thumbs: list[tuple[float, Image.Image]] = []
    next_t = 0.0
    with av.open(str(path)) as c:
        stream = c.streams.video[0]
        for frame in c.decode(video=0):
            t = float(frame.pts * stream.time_base)
            if t + 1e-6 >= next_t:
                img = frame.to_image()
                thumbs.append((t, img.resize((thumb_w, round(img.height * thumb_w / img.width)))))
                next_t += every_s
    if not thumbs:
        raise ValueError(f"No frames in {path}")
    th = thumbs[0][1].height
    rows = -(-len(thumbs) // cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * th), "black")
    draw = ImageDraw.Draw(sheet)
    for n, (t, img) in enumerate(thumbs):
        x, y = (n % cols) * thumb_w, (n // cols) * th
        sheet.paste(img, (x, y))
        # Label in the bottom-right corner, where titles and captions rarely sit.
        lx, ly = x + thumb_w - 50, y + th - 16
        draw.rectangle([lx, ly, lx + 50, ly + 16], fill="black")
        draw.text((lx + 3, ly + 2), f"{t:5.1f}s", fill="yellow")
    sheet.save(out_png)
    return Path(out_png)


def analyze(
    path: str | Path,
    expected_speech: str | None = None,
    expected_seconds: float | None = None,
    run_asr: bool = True,
    sheet_every_s: float = 1.0,
    ignore: list[tuple[float, float]] | None = None,
    language: str | None = None,
    names: list[str] | None = None,
) -> Report:
    """`ignore`: time windows (s) of intentional effects (flash, whip...) excluded from flicker/cut checks."""
    path = str(path)
    r = Report(path=path)
    grays: list[np.ndarray] = []
    lumas: list[float] = []
    sharp: list[float] = []
    with av.open(path) as c:
        vs = c.streams.video[0]
        r.width, r.height = vs.codec_context.width, vs.codec_context.height
        r.fps = float(vs.average_rate or 0)
        r.has_audio = bool(c.streams.audio)
        if r.has_audio:
            r.audio_sample_rate = c.streams.audio[0].rate
        for frame in c.decode(video=0):
            g = _gray_small(frame)
            grays.append(g)
            lumas.append(float(g.mean()))
            sharp.append(_laplacian_var(g))
    r.frames = len(grays)
    r.duration_s = r.frames / r.fps if r.fps else 0.0
    if r.frames < 2:
        r.issues.append(Issue("fail", "frames", f"only {r.frames} frames decoded"))
        return r

    def intended(i: int) -> bool:
        t = i / r.fps
        return any(a - 0.05 <= t <= b + 0.05 for a, b in ignore or [])

    diffs = np.array([float(np.abs(grays[i] - grays[i - 1]).mean()) for i in range(1, r.frames)])
    luma = np.array(lumas)
    r.mean_luma = float(luma.mean())
    r.sharpness_median = float(np.median(sharp))
    r.motion_median = float(np.median(diffs))

    # Cuts: frame difference far above the local motion level.
    base = max(r.motion_median, 0.5)
    cut_idx = [i + 1 for i, d in enumerate(diffs) if d > max(12.0, 6 * base)]
    r.cuts_s = [round(i / r.fps, 2) for i in cut_idx]

    r.black_frames = int((luma < 12).sum())
    if r.black_frames:
        r.issues.append(Issue("fail", "black_frames", f"{r.black_frames} near-black frames"))

    # Frozen: >= 0.75 s with essentially no pixel change.
    still = diffs < 0.15
    run_start = None
    for i, s in enumerate([*still, False]):
        if s and run_start is None:
            run_start = i
        elif not s and run_start is not None:
            if (i - run_start) / r.fps >= 0.75:
                r.frozen_spans_s.append((round(run_start / r.fps, 2), round(i / r.fps, 2)))
            run_start = None
    if r.frozen_spans_s:
        r.issues.append(Issue("warn", "frozen", f"static spans at {r.frozen_spans_s}"))

    # Flicker: brightness jump between consecutive frames that is not a cut.
    dl = np.abs(np.diff(luma))
    cut_set = set(cut_idx)
    r.flicker_frames = int(sum(1 for i, d in enumerate(dl) if d > 6.0 and (i + 1) not in cut_set and not intended(i + 1)))
    if r.flicker_frames > 2:
        r.issues.append(Issue("warn", "flicker", f"{r.flicker_frames} frames with abrupt brightness jumps"))

    if r.mean_luma < 40:
        r.issues.append(Issue("warn", "exposure", f"dark overall (mean luma {r.mean_luma:.0f}/255)"))
    elif r.mean_luma > 215:
        r.issues.append(Issue("warn", "exposure", f"washed out (mean luma {r.mean_luma:.0f}/255)"))

    # Blur = a frame much softer than its own neighbourhood (±1 s). A global median would wrongly flag cinematic
    # depth-of-field shots next to razor-sharp graphics.
    w = max(1, int(r.fps))
    sh = np.array(sharp)
    soft = [i for i in range(len(sh))
            if sh[i] < 0.35 * np.median(sh[max(0, i - w): i + w + 1]) and not intended(i)]
    if len(soft) > 0.03 * r.frames:
        r.issues.append(Issue("warn", "blur", f"{len(soft)} frames much softer than median"))

    if expected_seconds and abs(r.duration_s - expected_seconds) > 0.5:
        r.issues.append(Issue("warn", "duration", f"{r.duration_s:.2f}s vs expected {expected_seconds:.2f}s"))

    # Audio.
    if not r.has_audio:
        r.issues.append(Issue("fail", "audio", "no audio stream"))
    else:
        a = _decode_audio(path)
        if a is None or a.size == 0:
            r.issues.append(Issue("fail", "audio", "audio stream empty"))
        else:
            r.clipping_ratio = float((np.abs(a) >= 0.999).mean())
            win = max(1, r.audio_sample_rate // 20)
            mono = a.mean(axis=0)
            n = len(mono) // win
            rms = np.sqrt((mono[: n * win].reshape(n, win) ** 2).mean(axis=1) + 1e-12)
            r.silence_ratio = float((20 * np.log10(rms) < -50).mean())
            r.integrated_lufs, r.true_peak_dbfs = _loudness(path)
            if r.clipping_ratio > 1e-4:
                r.issues.append(Issue("warn", "clipping", f"{r.clipping_ratio:.4%} samples clipped"))
            if r.silence_ratio > 0.5:
                r.issues.append(Issue("warn", "silence", f"{r.silence_ratio:.0%} of audio is silent"))
            if r.integrated_lufs is not None and not -18 <= r.integrated_lufs <= -10:
                r.issues.append(Issue("warn", "loudness", f"{r.integrated_lufs:.1f} LUFS (target -14)"))

    if run_asr and r.has_audio:
        from ugc_studio import asr

        r.transcript = asr.transcribe(str(path), language)["text"]
        if expected_speech:
            r.speech_similarity = round(asr.similarity(expected_speech, r.transcript, language, names or []), 3)
            if r.speech_similarity < 0.6:
                r.issues.append(Issue("fail", "speech", f"transcript matches script at {r.speech_similarity:.0%}"))
            elif r.speech_similarity < 0.85:
                r.issues.append(Issue("warn", "speech", f"transcript matches script at {r.speech_similarity:.0%}"))

    sheet = Path(path).with_suffix(".contact.png")
    r.contact_sheet = str(contact_sheet(path, sheet, every_s=sheet_every_s))
    return r
