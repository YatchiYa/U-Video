"""Test fixtures: stub renderers replace the AI models (FLUX, LTX, TTS) so the whole pipeline is exercised
end to end on CPU with synthetic media: no model is loaded and nothing is generated."""

from __future__ import annotations

import colorsys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from ugc_studio.media import ffmpeg


class Calls:
    def __init__(self):
        self.keyframes: list[str] = []
        self.shots: list[str] = []
        self.retakes: list[tuple] = []
        self.garble: set[str] = set()  # clip stems whose speech a stub Whisper will "mishear"
        self.bad_visual: set[str] = set()  # clip stems the stub visual judge will reject


@pytest.fixture
def calls(monkeypatch):
    c = Calls()

    class StubKeyframes:
        def __init__(self, steps=4, source=None):
            pass

        def generate(self, prompt, width, height, seed, references=None, out_path=None):
            hue = (seed % 97) / 97
            rgb = tuple(int(255 * v) for v in colorsys.hsv_to_rgb(hue, 0.6, 0.9))
            im = Image.new("RGB", (width, height), rgb)
            ImageDraw.Draw(im).rectangle([width // 4, height // 4, width // 2, height // 2], fill=(20, 20, 20))
            im.save(out_path)
            import re as _re

            name = Path(out_path).name
            base = _re.sub(r"\.cand\d+", "", name)
            if name == base or ".cand0." in name:  # best-of-N: count each keyframe once, by its final name
                c.keyframes.append(base)
            return im

        def close(self):
            pass

    class StubShot:
        def __init__(self, offload="cpu", quantization="fp8-cast"):
            pass

        def render(self, prompt, out_path, width, height, num_frames, seed, images=None, fps=24):
            # Output depends on prompt + seed (like a real model), so changed inputs give changed content.
            import zlib

            h = zlib.crc32(f"{prompt}|{seed}".encode())
            sources = ["testsrc2", "smptebars", "rgbtestsrc", "mandelbrot"]
            src = sources[h % len(sources)]
            vf = []
            if "chroma-key green" in prompt:  # simulate the AI drawing a green phone screen (dark bezel around it)
                src = "color=c=0x302838"
                vf = ["-vf", f"drawbox=x={width // 3 - 8}:y={height // 3 - 8}:w={width // 4 + 16}:h={height // 3 + 16}"
                             f":color=0x101010:t=fill,drawbox=x={width // 3}:y={height // 3}:w={width // 4}:h={height // 3}"
                             ":color=0x00FF00:t=fill"]
            lav = f"{src}:size={width}x{height}:rate={fps}" if "=" in src else f"{src}=size={width}x{height}:rate={fps}"
            ffmpeg(["-f", "lavfi", "-i", lav, "-f", "lavfi", "-i",
                    f"sine=frequency={200 + h % 700}:sample_rate=48000", *vf, "-frames:v", str(num_frames),
                    "-t", f"{num_frames / fps:.4f}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(out_path)])
            Path(str(out_path) + ".prompt.txt").write_text(prompt)
            c.shots.append(Path(out_path).stem)
            return Path(out_path)

        def render_long(self, prompt, out_path, width, height, segments, seed, images, fps, workdir):
            total = sum(segments) - (len(segments) - 1)
            return self.render(prompt, out_path, width, height, total, seed, images, fps)

        def close(self):
            pass

    class StubRetake:
        def __init__(self, offload="cpu", quantization="fp8-cast"):
            pass

        def retake(self, src, out_path, prompt, start, end, seed, video=True, audio=False):
            ffmpeg(["-i", str(src), "-vf", f"negate=enable='between(t,{start},{end})'", "-c:a", "copy",
                    str(out_path)])
            c.retakes.append((Path(src).name, start, end))
            return Path(out_path)

        def close(self):
            pass

    def stub_transcribe(path_or_audio, language=None, rate=16000, device=None):
        import re

        side = Path(str(path_or_audio) + ".prompt.txt") if isinstance(path_or_audio, (str, Path)) else None
        if not side or not side.is_file():
            return {"text": "", "words": []}
        m = re.search(r'"(.+?)"', side.read_text())
        text = m.group(1) if m else ""
        if Path(path_or_audio).stem in c.garble:
            text = "mumble " + " ".join(text.split()[: len(text.split()) // 2])
        return {"text": text, "words": [{"w": w, "t0": 0.2 + 0.3 * i, "t1": 0.45 + 0.3 * i}
                                        for i, w in enumerate(text.split())]}

    import ugc_studio.asr as asr_mod
    import ugc_studio.keyframes as kf
    import ugc_studio.render as rd

    monkeypatch.setattr(asr_mod, "transcribe", stub_transcribe)
    import ugc_studio.phonetics as ph_mod

    monkeypatch.setattr(ph_mod, "check", lambda path, script, language: {"score": 1.0, "flagged": [], "heard": ""})
    import ugc_studio.judge as judge_mod

    # Visual judges: real models are too heavy for unit tests; stubs return passing scores unless told otherwise.
    monkeypatch.setattr(judge_mod, "prompt_score", lambda image, text: 30.0)
    monkeypatch.setattr(judge_mod, "identity_score", lambda image, refs: 0.5 if refs else 1.0)
    monkeypatch.setattr(judge_mod, "clip_checks",
                        lambda path, refs=None: {"ok": Path(path).stem not in c.bad_visual, "identity": [0.5] if refs else None,
                                                 "issues": [] if Path(path).stem not in c.bad_visual else ["identity drift (0.05)"]})

    monkeypatch.setattr(kf, "KeyframeGenerator", StubKeyframes)
    monkeypatch.setattr(rd, "ShotRenderer", StubShot)
    monkeypatch.setattr(rd, "RetakeRenderer", StubRetake)
    return c


def write_project(folder: Path, yaml_text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.yaml").write_text(yaml_text)
    return folder
