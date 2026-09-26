"""Speech quality of a voice take, without a reference recording.

TorchAudio SQUIM *objective* model (weights CC-BY-4.0, trained on DNS 2020): estimates PESQ (≈1 to 4.5, the ITU
measure of perceived speech quality). Used to pick the best-sounding take among takes that say every word right.
The SQUIM *subjective* (MOS) model is not used: its weights are CC-BY-NC-4.0 (non-commercial).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf


@lru_cache(maxsize=1)
def _model():
    from torchaudio.pipelines import SQUIM_OBJECTIVE

    return SQUIM_OBJECTIVE.get_model().eval()


def _load(path):
    import torch
    import torchaudio

    y, sr = sf.read(str(path), dtype="float32")
    y = y.mean(1) if y.ndim > 1 else y
    return torchaudio.functional.resample(torch.from_numpy(np.ascontiguousarray(y))[None], sr, 16000)


def score(path: str | Path) -> float:
    """Estimated PESQ of the take (higher = cleaner, more natural)."""
    import torch

    with torch.no_grad():
        _stoi, pesq, _si_sdr = _model()(_load(path))
    return float(pesq[0])
