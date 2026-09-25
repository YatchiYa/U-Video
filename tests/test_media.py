"""Media toolkit + motion engine tests (synthetic media, no AI models)."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from ugc_studio import motion, timeline
from ugc_studio.media import color_match_lut, conform, ffmpeg, interpolate_frames, probe, sample_frames
from ugc_studio.schema import Project


@pytest.fixture
def clip(tmp_path):
    out = tmp_path / "src.mp4"
    ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-frames:v", "121", "-t", str(121 / 25), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)])
    return out


def test_conform_exact_frames_crop_and_stretch(tmp_path, clip):
    out = conform(clip, tmp_path / "c.mov", fps=25, width=360, height=640, start=1.0, duration=3.0, stretch=1.1)
    p = probe(out)
    assert (p["frames"], p["width"], p["height"], p["audio"]) == (75, 360, 640, True)


def test_color_match_moves_toward_reference(tmp_path, clip):
    ref = tmp_path / "ref.mp4"
    ffmpeg(["-i", str(clip), "-vf", "eq=brightness=0.2:saturation=0.4", "-an", str(ref)])
    lut = color_match_lut(sample_frames(clip), sample_frames(ref), tmp_path / "m.cube", strength=1.0)
    graded = conform(clip, tmp_path / "g.mov", fps=25, width=640, height=360, lut=lut)
    mean = lambda p: float(np.mean([f.mean() for f in sample_frames(p)]))  # noqa: E731
    assert abs(mean(graded) - mean(ref)) < abs(mean(clip) - mean(ref))


def test_optical_flow_repair_is_near_perfect():
    truth = []
    for i in range(30):
        f = np.zeros((180, 320, 3), np.uint8)
        cv2.rectangle(f, (20 + 8 * i, 60), (60 + 8 * i, 100), (255, 200, 0), -1)
        truth.append(f)
    bad = [t.copy() for t in truth]
    for i in (10, 11, 12):
        bad[i] = np.full_like(bad[i], 255)
    interpolate_frames(bad, 10, 12)
    err = max(float(np.abs(bad[i].astype(int) - truth[i].astype(int)).mean()) for i in (10, 11, 12))
    assert err < 3


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920)])
def test_motion_engine_renders_all_scene_kinds(tmp_path, size):
    p = Project.model_validate({
        "title": "t", "mode": "promo", "fps": 25, "logo_bug": True, "captions": {"enabled": True},
        "brand": {"name": "Acme", "url": "https://acme.test", "offer": "Free trial", "tagline": "Simpler."},
        "scenes": [{"id": "a", "prompt": "p", "seconds": 2, "caption": ["Hello"]},
                   {"id": "b", "kind": "title", "seconds": 2, "headline": "Meet Acme", "transition": {"type": "brand"}},
                   {"id": "c", "kind": "features", "seconds": 2, "headline": "All", "features": [{"title": "Fast"}],
                    "transition": {"type": "slide"}},
                   {"id": "d", "kind": "endcard", "seconds": 2, "transition": {"type": "circle"}}]})
    tl = timeline.build(p)
    comp = motion.build_comp(p, tl, tmp_path / "m", *size, caption_words=[{"w": "hello", "t0": 0.2, "t1": 0.6}])
    frames = motion.stills(comp, tmp_path / "m", [0.4, tl.slot("b").start + 1.0, tl.slot("d").start + 1.2])
    alpha = [np.asarray(f)[..., 3] for f in frames]
    assert alpha[0].mean() < 200  # live-action overlay is mostly transparent
    assert alpha[1].min() == 255 and alpha[2].min() == 255  # graphics scenes are opaque
    assert frames[0].size == size


def test_no_brand_transition_leaves_live_action_uncovered(tmp_path):
    """Regression: the wipe bands must stay off-screen when no brand/wipe transition is used."""
    p = Project.model_validate({
        "title": "t", "mode": "faceless", "aspect": "9:16",
        "scenes": [{"id": "a", "prompt": "p", "seconds": 2, "caption": ["Hi"]},
                   {"id": "b", "prompt": "q", "seconds": 2, "transition": {"type": "whip", "seconds": 0.3}},
                   {"id": "c", "prompt": "r", "seconds": 2, "transition": {"type": "fadewhite", "seconds": 0.25}}]})
    tl = timeline.build(p)
    comp = motion.build_comp(p, tl, tmp_path / "m", 1080, 1920)
    for f in motion.stills(comp, tmp_path / "m", [0.1, 1.0, tl.slot("b").start + 1.0, tl.total - 0.2]):
        a = np.asarray(f)[..., 3]
        assert (a > 200).mean() < 0.25, "overlay covers the live action"


def test_first_frame_shows_opening_caption(tmp_path):
    """Regression: frame 0 (the TikTok thumbnail) must already show the opening hook text."""
    p = Project.model_validate({"title": "t", "mode": "faceless", "aspect": "9:16",
                                "scenes": [{"id": "a", "prompt": "p", "seconds": 2, "caption": ["HOOK TEXT"]}]})
    tl = timeline.build(p)
    comp = motion.build_comp(p, tl, tmp_path / "m", 1080, 1920)
    a = np.asarray(motion.stills(comp, tmp_path / "m", [0.0])[0])[..., 3]
    assert (a > 200).sum() > 5000, "no caption pixels on frame 0"


def test_devices_fan_and_spin_reveal_render(tmp_path):
    """3D features: spin reveal on a dark screen scene and a 3-device fan, in 9:16."""
    from PIL import Image

    img = tmp_path / "screen.png"
    Image.new("RGB", (390, 844), (240, 240, 250)).save(img)
    p = Project.model_validate({
        "title": "t", "mode": "promo", "aspect": "9:16", "brand": {"name": "Acme", "url": "https://acme.test"},
        "scenes": [{"id": "r", "kind": "screen", "seconds": 3, "image": str(img), "reveal": "spin", "theme": "dark",
                    "headline": "Hello"},
                   {"id": "d", "kind": "devices", "seconds": 3, "headline": "3 langs", "transition": {"type": "zoom"},
                    "devices": [{"image": str(img), "label": "FR"}, {"image": str(img), "label": "العربية"},
                                {"image": str(img), "label": "EN"}]}]})
    tl = timeline.build(p)
    comp = motion.build_comp(p, tl, tmp_path / "m", 1080, 1920)
    frames = motion.stills(comp, tmp_path / "m", [2.5, tl.slot("d").start + 2.0])
    for f in frames:
        rgb = np.asarray(f.convert("RGB")).astype(int)
        assert np.asarray(f)[..., 3].min() == 255  # opaque graphics scene
        assert (rgb.sum(-1) > 600).mean() > 0.05  # light screens visible on the dark background
