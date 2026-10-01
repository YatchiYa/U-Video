"""Rates music candidates with Meta Audiobox Aesthetics (CC-BY-4.0): content enjoyment (CE), content usefulness (CU),
production complexity (PC) and production quality (PQ), each about 1-10. Runs inside vendor/stable-audio-3/.venv.

Usage: python music_judge.py a.wav b.wav ...  → prints {"a.wav": {"CE": .., "CU": .., "PC": .., "PQ": ..}, ...}
"""

import json
import sys


def main(paths: list[str]) -> None:
    from audiobox_aesthetics.infer import initialize_predictor

    rows = initialize_predictor().forward([{"path": p} for p in paths])
    print(json.dumps({p: {k: round(float(v), 3) for k, v in r.items()} for p, r in zip(paths, rows)}), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
