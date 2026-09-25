"""Final delivery QA for the DZ-MeNU spot: specs, loudness, speech, picture checks, QR scannability."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

import av
import numpy as np
import torch
import zxingcpp
from transformers import pipeline

sys.path.insert(0, str(Path(__file__).parent))
from check_vo import norm  # noqa: E402

from ugc_studio.media import FFMPEG  # noqa: E402
from ugc_studio.qa import _decode_audio, analyze  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "out"
SPEC = {"frames": 1500, "fps": 25, "w": 1920, "h": 1080}


def loudness(path: Path) -> tuple[float, float]:
    err = subprocess.run([FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af",
                          "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    summary = err.rsplit("Summary:", 1)[-1]
    return (float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1)),
            float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary).group(1)))


def specs(path: Path) -> dict:
    with av.open(str(path)) as c:
        v, a = c.streams.video[0], c.streams.audio[0]
        n = sum(1 for _ in c.decode(video=0))
        return {"frames": n, "fps": float(v.average_rate), "w": v.codec_context.width, "h": v.codec_context.height,
                "vcodec": v.codec_context.name, "pix_fmt": v.codec_context.pix_fmt, "acodec": a.codec_context.name,
                "arate": a.rate}


def qr_scans(path: Path, times: list[float]) -> dict[float, str | None]:
    found = {}
    with av.open(str(path)) as c:
        stream = c.streams.video[0]
        want = sorted(times)
        for frame in c.decode(video=0):
            t = float(frame.pts * stream.time_base)
            while want and t + 1e-3 >= want[0]:
                res = zxingcpp.read_barcodes(frame.to_ndarray(format="rgb24"))
                found[want.pop(0)] = res[0].text if res else None
            if not want:
                break
    return found


def main() -> int:
    report, ok = {}, True
    targets = {"dzmenu_tv_1080p25.mp4": (-23.0, 0.5, -2.0), "dzmenu_web_1080p.mp4": (-14.0, 1.0, -1.0),
               "dzmenu_tv_master_1080p25.mov": (-23.0, 0.5, -2.0)}
    for name, (lufs_t, tol, tp_max) in targets.items():
        p = OUT / name
        s = specs(p)
        i, tp = loudness(p)
        checks = {
            "frames": s["frames"] == SPEC["frames"], "fps": abs(s["fps"] - SPEC["fps"]) < 1e-6,
            "size": (s["w"], s["h"]) == (SPEC["w"], SPEC["h"]), "audio_48k": s["arate"] == 48000,
            "loudness": abs(i - lufs_t) <= tol, "true_peak": tp <= tp_max,
        }
        ok &= all(checks.values())
        report[name] = {**s, "lufs": i, "true_peak": tp, "checks": checks}
        print(f"{name}: {s['vcodec']} {s['w']}x{s['h']} {s['fps']}fps {s['frames']}f | {s['acodec']} {s['arate']}Hz | "
              f"{i} LUFS TP {tp} | {'PASS' if all(checks.values()) else 'FAIL ' + str([k for k, v in checks.items() if not v])}")

    web = OUT / "dzmenu_web_1080p.mp4"
    vo = json.loads((HERE / "vo" / "manifest.json").read_text())
    script = " ".join(vo[k]["text"] for k in sorted(vo) if k.startswith("vo"))
    asr = pipeline("automatic-speech-recognition", model="openai/whisper-large-v3-turbo", dtype=torch.float16,
                   device="cuda")
    audio = _decode_audio(str(web), 16000).mean(0)
    text = asr({"raw": audio, "sampling_rate": 16000}, return_timestamps=True,
               generate_kwargs={"language": "french"})["text"].strip()
    score = SequenceMatcher(None, norm(script), norm(text)).ratio()
    ok &= score >= 0.95
    print(f"speech: {score:.3f} | {text}")

    r = analyze(web, run_asr=False)
    report["picture"] = {"black_frames": r.black_frames, "frozen": r.frozen_spans_s, "flicker": r.flicker_frames,
                         "contact_sheet": r.contact_sheet}
    ok &= r.black_frames == 0
    print(f"picture: black {r.black_frames} | frozen {r.frozen_spans_s} | flicker {r.flicker_frames}")

    tl = json.loads((HERE / "timeline.json").read_text())
    end = tl["scenes"]["s_end"]
    times = [round(end["start"] + x, 2) for x in np.arange(2.0, end["dur"] - 0.2, 1.0)]
    scans = qr_scans(web, times)
    good = sum(1 for v in scans.values() if v == "https://dz-menu.com/fr")
    ok &= good == len(scans)
    print(f"QR: {good}/{len(scans)} end-card frames decode to https://dz-menu.com/fr")

    report.update(speech={"score": round(score, 3), "transcript": text}, qr={str(k): v for k, v in scans.items()},
                  verdict="PASS" if ok else "FAIL")
    (OUT / "qa_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print("VERDICT:", report["verdict"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
