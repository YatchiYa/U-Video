"""End-to-end pipeline tests with stubbed models (see conftest.py)."""

from __future__ import annotations

import textwrap

import pytest

from ugc_studio.engine import Studio
from ugc_studio.fix import plan_fix
from ugc_studio.media import probe
from ugc_studio.schema import Project
from ugc_studio.timeline import Timeline

from conftest import write_project

UGC = textwrap.dedent("""
    title: Test UGC
    mode: ugc
    aspect: "9:16"
    quality: draft
    fps: 24
    music: {mode: none}
    captions: {enabled: false}
    characters:
      - {id: hero, description: a 30-year-old woman with short black hair}
    scenes:
      - {id: s01, prompt: she waves at the camera, seconds: 3, characters: [hero], dialogue: Hi there}
      - {id: s02, prompt: she holds up the bottle, seconds: 3, characters: [hero], continuity: match,
         transition: {type: dissolve, seconds: 0.4}}
      - {id: s03, prompt: she smiles, seconds: 3, characters: [hero], continuity: continue}
      - {id: s04, prompt: close up of the bottle, seconds: 2, transition: {type: whip, seconds: 0.3}}
""")


def _build(folder):
    st = Studio(folder)
    res = st.build(deliveries=("web",))
    return st, res


def test_full_build_is_frame_exact(tmp_path, calls):
    folder = write_project(tmp_path / "p", UGC)
    st, res = _build(folder)
    tl = Timeline.load(folder / "timeline.json")
    web = probe(res.deliveries["web"])
    assert web["frames"] == round(tl.total * 24)
    assert (web["width"], web["height"]) == (1080, 1920)
    assert web["audio"]
    # match seam: s01 got an end frame = s02's start; continue: s03 has no generated start frame
    assert "seam_s01_s02.png" in calls.keyframes
    assert "s03_start.png" not in calls.keyframes
    assert calls.shots == ["s01", "s02", "s03", "s04"]


def test_rebuild_is_fully_cached(tmp_path, calls):
    folder = write_project(tmp_path / "p", UGC)
    _build(folder)
    n_kf, n_shots = len(calls.keyframes), len(calls.shots)
    _build(folder)
    assert len(calls.keyframes) == n_kf and len(calls.shots) == n_shots


def test_editing_one_scene_rebuilds_only_what_depends_on_it(tmp_path, calls):
    folder = write_project(tmp_path / "p", UGC)
    _build(folder)
    calls.shots.clear()
    calls.keyframes.clear()
    text = (folder / "project.yaml").read_text().replace("close up of the bottle", "macro shot of the bottle")
    (folder / "project.yaml").write_text(text)
    _build(folder)
    assert calls.shots == ["s04"]  # s04's prompt changed; nothing else is re-rendered
    assert calls.keyframes == ["s04_start.png"]


def test_changing_upstream_shot_rerenders_its_continuation(tmp_path, calls):
    folder = write_project(tmp_path / "p", UGC)
    _build(folder)
    calls.shots.clear()
    text = (folder / "project.yaml").read_text().replace("she holds up the bottle", "she holds up the jar")
    (folder / "project.yaml").write_text(text)
    _build(folder)
    # s03 continues from s02's last frame, so it must follow; s01 (seam owner) and s04 stay cached
    assert calls.shots == ["s02", "s03"]


def test_fix_interpolate_touches_only_that_shot(tmp_path, calls):
    folder = write_project(tmp_path / "p", UGC)
    st, res = _build(folder)
    tl = Timeline.load(folder / "timeline.json")
    slot, local = tl.locate(tl.slot("s04").start + 0.5)
    assert slot.id == "s04"
    fx = plan_fix(local, 0.1, "auto", 2.0)
    assert fx.kind == "interpolate"
    st.project.scene("s04").fixes.append(fx)
    st.save_project()
    calls.shots.clear()
    st2, res2 = _build(folder)
    assert calls.shots == []  # no shot re-rendered
    assert Project.load(folder / "project.yaml").scene("s04").fixes[0].kind == "interpolate"
    from ugc_studio.media import probe as _p
    assert _p(folder / "fixed" / "s04.mp4")["frames"] == _p(folder / "clips" / "s04.mp4")["frames"]  # no frame lost
    assert probe(res2.deliveries["web"])["frames"] == probe(res.deliveries["web"])["frames"]


def test_fix_retake_regenerates_only_the_window(tmp_path, calls):
    folder = write_project(tmp_path / "p", UGC)
    st, _ = _build(folder)
    fx = plan_fix(1.2, 0.6, "retake", 3.0)
    assert fx.end - fx.start >= 1.0
    st.project.scene("s01").fixes.append(fx)
    st.save_project()
    calls.shots.clear()
    _build(folder)
    assert calls.shots == [] and len(calls.retakes) == 1


PROMO = textwrap.dedent("""
    title: Test Promo
    mode: promo
    style: promo
    aspect: "16:9"
    quality: draft
    fps: 25
    target_seconds: 14
    logo_bug: true
    voice: {enabled: false}
    music: {mode: none}
    brand: {name: Acme, url: "https://example.com", offer: "30 days free", tagline: "Everything, simpler."}
    products:
      - {id: app, description: a sleek mobile app}
    scenes:
      - {id: hook, prompt: a busy café, seconds: 3, caption: ["Too many paper menus?"]}
      - {id: title, kind: title, seconds: 2.5, headline: Meet Acme, transition: {type: brand, seconds: 0.8}}
      - {id: gen, kind: image, seconds: 2.5, start_prompt: the app on a phone, products: [app],
         transition: {type: circle, seconds: 0.6}}
      - {id: feats, kind: features, seconds: 3, headline: Everything in one place,
         features: [{title: Fast, icon: zap}, {title: Simple, icon: sparkles}], transition: {type: slide, seconds: 0.5}}
      - {id: end, kind: endcard, seconds: 2, transition: {type: brand, seconds: 0.8}}
""")


def test_promo_hits_exact_target_length(tmp_path, calls):
    folder = write_project(tmp_path / "promo", PROMO)
    st, res = _build(folder)
    web = probe(res.deliveries["web"])
    assert web["frames"] == 14 * 25
    assert (web["width"], web["height"]) == (1920, 1080)
    assert "gen_image.png" in calls.keyframes  # generated still for the image scene
    assert "ref_app.png" in calls.keyframes  # product reference generated from its description


def test_target_too_short_is_a_clear_error(tmp_path, calls):
    folder = write_project(tmp_path / "promo", PROMO.replace("target_seconds: 14", "target_seconds: 5"))
    with pytest.raises(ValueError, match="target_seconds"):
        _build(folder)


def test_two_live_action_runs_keep_their_own_sound(tmp_path, calls):
    """Regression: shots separated by a graphics scene form two runs; each run's audio must stay in place."""
    import numpy as np

    from ugc_studio.asr import load_audio

    folder = write_project(tmp_path / "runs", textwrap.dedent("""
        title: Two runs
        mode: ugc
        quality: draft
        music: {mode: none}
        scenes:
          - {id: a1, prompt: first talking shot, seconds: 2}
          - {id: a2, prompt: second talking shot, seconds: 2}
          - {id: mid, kind: title, seconds: 2, headline: Break, transition: {type: brand, seconds: 0.8}}
          - {id: b1, prompt: third talking shot, seconds: 2, transition: {type: circle, seconds: 0.5}}
          - {id: b2, prompt: fourth talking shot, seconds: 2, transition: {type: whip, seconds: 0.3}}
    """))
    st, res = _build(folder)
    tl = Timeline.load(folder / "timeline.json")
    audio = load_audio(str(folder / "render" / "base.mov"), 16000)

    def level(t0, t1):
        seg = audio[int(t0 * 16000):int(t1 * 16000)]
        return 20 * np.log10(np.sqrt((seg ** 2).mean()) + 1e-9)

    b = tl.slot("b1")
    assert level(b.start + 0.3, b.start + b.dur - 0.3) > -40, "second run is silent"
    assert level(tl.slot("a1").start + 0.3, tl.slot("a1").start + 1.5) > -40
    # each run's own tone: the stub encodes a prompt-dependent frequency, so compare spectra of a1 and b1
    def peak_hz(t0):
        seg = audio[int(t0 * 16000):int((t0 + 0.5) * 16000)]
        return np.argmax(np.abs(np.fft.rfft(seg))) * 16000 / len(seg)
    assert abs(peak_hz(tl.slot("a1").start + 0.4) - peak_hz(b.start + 0.4)) > 5


def test_misspoken_line_is_reshot_automatically(tmp_path, calls):
    """A take whose speech doesn't match the script is re-shot with a new seed; the best take is kept."""
    folder = write_project(tmp_path / "speech", UGC)
    calls.garble.add("s01")  # the first take of s01 is "mispronounced"
    st, res = _build(folder)
    assert calls.shots.count("s01") == 1 and "s01.take1" in calls.shots
    a = st.state.get("clip:s01")
    assert a["speech"] == 1.0 and len(a["speech_tries"]) == 2 and a["speech_tries"][0] < a["speech_tries"][1]
    # the accepted take is cached: a rebuild re-shoots nothing
    calls.shots.clear()
    _build(folder)
    assert calls.shots == []


def test_screen_insert_puts_the_real_app_on_the_phone(tmp_path, calls):
    """A shot with screen_insert is generated with a green screen, then the app image is composited onto it."""
    import numpy as np
    from PIL import Image

    from ugc_studio.composite import green_mask
    from ugc_studio.media import read_frames

    app = tmp_path / "app.png"
    Image.new("RGB", (390, 844), (108, 43, 217)).save(app)
    folder = write_project(tmp_path / "ins", textwrap.dedent(f"""
        title: Insert
        mode: ugc
        quality: draft
        music: {{mode: none}}
        scenes:
          - id: s01
            prompt: a hand holds a phone
            seconds: 2
            screen_insert: {{image: "{app}"}}
    """))
    st, res = _build(folder)
    frames = read_frames(folder / "fixed" / "s01.screen.mp4")
    assert st.state.get("insert:s01")["keyed"] == len(frames)
    h, w = frames[0].shape[:2]
    box = (slice(h // 3 + 3, h // 3 + h // 3 - 3), slice(w // 3 + 3, w // 3 + w // 4 - 3))
    assert max((green_mask(f)[box] > 0).mean() for f in frames) < 0.001  # the green screen is fully replaced
    mid = frames[len(frames) // 2]
    assert (np.abs(mid.astype(int) - (108, 43, 217)).sum(-1) < 60).mean() > 0.02  # the app color is on screen


def test_visual_gate_reshoots_a_drifting_shot(tmp_path, calls):
    """Any shot whose subject drifts (or goes black/frozen) is re-shot automatically, best take kept."""
    folder = write_project(tmp_path / "vis", UGC)
    calls.bad_visual.add("s04")
    st, res = _build(folder)
    assert "s04.take1" in calls.shots
    a = st.state.get("clip:s04")
    assert a["qc_ok"] is True and a["seed_used"] != st._shot_seed(3)


def test_best_of_n_rejects_a_keyframe_below_the_identity_floor(tmp_path, calls, monkeypatch):
    import ugc_studio.judge as judge_mod

    seen = []

    def ident(image, refs):
        seen.append(str(image))
        return 0.05 if ".cand0." in str(image) else 0.5  # first candidate is "someone else"

    monkeypatch.setattr(judge_mod, "identity_score", ident)
    folder = write_project(tmp_path / "bo", UGC)
    st, _ = _build(folder)
    rep = st.state.get("kf:s01:start")
    assert rep is not None
    assert any(".cand0." in s for s in seen) and any(".cand1." in s for s in seen)


def test_your_own_footage_as_a_clip_scene(tmp_path, calls):
    """kind: clip uses your video (window clip_in..clip_in+seconds) as a live-action shot, with no AI render."""
    from ugc_studio.media import ffmpeg as _ff

    v = tmp_path / "mine.mp4"
    _ff(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30", "-f", "lavfi", "-i", "sine=frequency=500:sample_rate=44100",
         "-t", "6", "-pix_fmt", "yuv420p", "-c:a", "aac", str(v)])
    folder = write_project(tmp_path / "clip", textwrap.dedent(f"""
        title: Footage
        mode: faceless
        quality: draft
        voice: {{enabled: false}}
        music: {{mode: none}}
        scenes:
          - {{id: mine, kind: clip, video: "{v}", clip_in: 1.5, seconds: 3, caption: ["My own footage"]}}
          - {{id: ai, prompt: a sunset, seconds: 2, transition: {{type: dissolve, seconds: 0.4}}}}
          - {{id: end, kind: endcard, seconds: 2, transition: {{type: fade, seconds: 0.4}}}}
    """))
    st, res = _build(folder)
    assert calls.shots == ["ai"]  # the clip is not generated
    web = probe(res.deliveries["web"])
    tl = Timeline.load(folder / "timeline.json")
    assert web["frames"] == round(tl.total * 24) and (web["width"], web["height"]) == (1080, 1920)
    assert tl.slot("mine").dur == pytest.approx(3.0, abs=0.05)


def test_your_own_voiceover_file_drives_the_edit(tmp_path, calls, monkeypatch):
    """voice.file: your recording is cut per scene (by sentence) and becomes the narration + captions."""
    import ugc_studio.asr as asr_mod
    from ugc_studio.media import ffmpeg as _ff

    vo = tmp_path / "vo.mp3"
    _ff(["-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100", "-t", "7", str(vo)])
    words = [("Bienvenue", 0.2, 0.7), ("chez", 0.7, 0.9), ("nous.", 0.9, 1.3), ("Le", 2.0, 2.2), ("menu", 2.2, 2.6),
             ("est", 2.6, 2.8), ("en", 2.8, 2.9), ("ligne.", 2.9, 3.4), ("Scannez", 4.2, 4.8), ("maintenant.", 4.8, 5.6)]
    monkeypatch.setattr(asr_mod, "transcribe", lambda path, language=None, rate=16000, device=None: {
        "text": " ".join(w for w, _, _ in words), "words": [{"w": w, "t0": a, "t1": b} for w, a, b in words]})
    folder = write_project(tmp_path / "vo", textwrap.dedent(f"""
        title: My voice
        mode: faceless
        quality: draft
        voice: {{file: "{vo}"}}
        music: {{mode: none}}
        captions: {{enabled: true}}
        scenes:
          - {{id: a, prompt: a café, seconds: 2}}
          - {{id: b, prompt: a phone, seconds: 2}}
          - {{id: c, prompt: a smile, seconds: 2}}
    """))
    st, res = _build(folder)
    tl = Timeline.load(folder / "timeline.json")
    assert all(s.vo_file for s in tl.slots)  # each scene got its sentence
    assert st.project.scene("c").voiceover.startswith("Scannez")
    assert probe(res.deliveries["web"])["audio"]
