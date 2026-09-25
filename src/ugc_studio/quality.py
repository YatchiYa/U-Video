"""Speech quality: a predicted listener rating (MOS 1-5) for a voice take, without a reference recording.

TorchAudio SQUIM subjective model, on CPU. Used to pick the best-sounding take among takes that say every word right.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from ugc_studio.config import ROOT

# Any clean, unrelated speech works as SQUIM's "non-matching reference".
NMR = ROOT / "src" / "ugc_studio" / "assets" / "nmr_speech.wav"


@lru_cache(maxsize=1)
def _model():
    from torchaudio.pipelines import SQUIM_SUBJECTIVE

    return SQUIM_SUBJECTIVE.get_model().eval()


def _load(path) -> "np.ndarray":
    import torch
    import torchaudio

    y, sr = sf.read(str(path), dtype="float32")
    y = y.mean(1) if y.ndim > 1 else y
    return torchaudio.functional.resample(torch.from_numpy(np.ascontiguousarray(y))[None], sr, 16000)


def mos(path: str | Path) -> float:
    import torch

    with torch.no_grad():
        return float(_model()(_load(path), _load(NMR))[0])
