"""Ingestion: any user file format works or fails with a clear message."""

from __future__ import annotations

import textwrap

import numpy as np
from PIL import Image

from ugc_studio import assets
from ugc_studio.engine import Studio
from ugc_studio.media import ffmpeg

from conftest import write_project


def _photo(path, size=(800, 1000), mode="RGB", color=(120, 80, 60)):
    im = Image.new(mode, size, color if mode != "RGBA" else (*color, 0))
    if mode == "RGBA":
        im.paste((*color, 255), (200, 200, 600, 800))
    im.save(path)
    return path


def test_images_any_format_are_normalized(tmp_path):
    rep = assets.IngestReport()
    out = tmp_path / "a"
    for name, mode in [("x.jpg", "RGB"), ("x.webp", "RGB"), ("x.png", "RGBA"), ("x.tiff", "CMYK"), ("x.heic", "RGB")]:
        src = _photo(tmp_path / name, mode=mode if mode != "CMYK" else "CMYK",
                     color=(10, 20, 30, 40) if mode == "CMYK" else (120, 80, 60))
        n = assets.normalize_image(src, out, rep)
        im = Image.open(n)
        assert im.mode == "RGB" and n.endswith(".png"), name
    assert not rep.errors
    # transparent background became white
    assert Image.open(assets.normalize_image(tmp_path / "x.png", out, rep)).getpixel((5, 5)) == (255, 255, 255)


def test_exif_rotation_is_applied(tmp_path):
    im = Image.new("RGB", (400, 800), (200, 0, 0))
    exif = im.getexif()
    exif[0x0112] = 6  # rotate 90 degrees on display
    im.save(tmp_path / "rot.jpg", exif=exif)
    n = assets.normalize_image(tmp_path / "rot.jpg", tmp_path / "a", assets.IngestReport())
    assert Image.open(n).size == (800, 400)


def test_video_reference_gives_sharp_varied_frames(tmp_path):
    v = tmp_path / "cat.mp4"
    ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "4", "-pix_fmt", "yuv420p", str(v)])
    frames = assets.frames_from_video(v, tmp_path / "a", assets.IngestReport(), 3)
    assert len(frames) == 3 and len({Image.open(f).tobytes()[:5000] for f in frames}) == 3


def test_bad_files_give_clear_errors(tmp_path, calls):
    (tmp_path / "broken.jpg").write_bytes(b"not an image")
    folder = write_project(tmp_path / "p", textwrap.dedent(f"""
        title: T
        music: {{mode: none}}
        characters: [{{id: c, description: x, images: ["{tmp_path}/broken.jpg", "{tmp_path}/missing.png"]}}]
        scenes: [{{id: a, prompt: p, characters: [c]}}]
    """))
    st = Studio(folder)
    assert any("broken.jpg" in e and "cannot read" in e for e in st.ingest.errors)
    assert any("missing.png" in e for e in st.ingest.errors)


def test_video_file_as_character_reference_end_to_end(tmp_path, calls):
    v = tmp_path / "pet.mp4"
    ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-t", "3", "-pix_fmt", "yuv420p", str(v)])
    folder = write_project(tmp_path / "p", textwrap.dedent(f"""
        title: T
        quality: draft
        music: {{mode: none}}
        characters: [{{id: pet, description: a cat, images: ["{v}"]}}]
        scenes: [{{id: a, prompt: the cat jumps, seconds: 2, characters: [pet]}}]
    """))
    st = Studio(folder)
    assert not st.ingest.errors and len(st.project.characters[0].images) == 3
    res = st.build()
    assert res.deliveries["web"].is_file()
