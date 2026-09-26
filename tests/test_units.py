"""Unit tests: schema validation, timeline math, director assembly for every mode, fix planning, CLI."""

from __future__ import annotations

import textwrap

import pytest
from typer.testing import CliRunner

from ugc_studio import director, timeline
from ugc_studio.cli import app
from ugc_studio.fix import plan_fix
from ugc_studio.schema import Brand, Project

from conftest import write_project


# ---------------------------------------------------------------- schema
def test_schema_rejects_unknown_character():
    with pytest.raises(ValueError, match="unknown character"):
        Project.model_validate({"title": "x", "scenes": [{"id": "a", "prompt": "p", "characters": ["ghost"]}]})


def test_schema_rejects_duplicate_ids_and_typos():
    with pytest.raises(ValueError, match="duplicate"):
        Project.model_validate({"title": "x", "scenes": [{"id": "a", "prompt": "p"}, {"id": "a", "prompt": "q"}]})
    with pytest.raises(ValueError):  # typo in a field name is an error, not silently ignored
        Project.model_validate({"title": "x", "scenes": [{"id": "a", "promt": "p"}]})


def test_schema_dialogue_and_voiceover_are_exclusive():
    with pytest.raises(ValueError, match="either dialogue"):
        Project.model_validate({"title": "x", "scenes": [{"id": "a", "prompt": "p", "dialogue": "hi", "voiceover": "yo"}]})


def test_v1_storyboard_migrates():
    p = Project.load("examples/glow_drops_20s.yaml")
    assert p.mode == "ugc" and len(p.scenes) == 4 and p.scenes[0].characters == ["hero"]


# ---------------------------------------------------------------- timeline
def _promo(target=None):
    return Project.model_validate({
        "title": "t", "mode": "promo", "fps": 25, "target_seconds": target,
        "scenes": [{"id": "a", "prompt": "p", "seconds": 3},
                   {"id": "b", "kind": "title", "seconds": 2, "transition": {"type": "brand", "seconds": 0.8}},
                   {"id": "c", "kind": "endcard", "seconds": 2, "transition": {"type": "fade", "seconds": 0.5}}]})


def test_timeline_overlaps_and_locate():
    tl = timeline.build(_promo())
    a, b, c = tl.slots
    assert b.start == pytest.approx(a.dur - 0.8, abs=1e-3)
    assert c.start == pytest.approx(b.start + b.dur - 0.5, abs=1e-3)
    slot, local = tl.locate(1.0)
    assert slot.id == "a" and local == pytest.approx(1.0)
    assert tl.locate(tl.total - 0.1)[0].id == "c"
    with pytest.raises(ValueError):
        tl.locate(tl.total + 5)


def test_timeline_fits_target_exactly():
    tl = timeline.build(_promo(target=10))
    assert tl.total == 10
    assert tl.slots[-1].start + tl.slots[-1].dur == pytest.approx(10, abs=1e-3)


# ---------------------------------------------------------------- director assembly (no LLM)
SHOTS = [{"setting": "a bright kitchen", "action": "she holds the serum bottle", "camera": "handheld selfie",
          "dialogue": "Okay you need to hear about this", "same_setup_as_previous": False},
         {"setting": "same kitchen", "action": "she applies it", "camera": "close-up",
          "dialogue": "two drops every morning and done", "same_setup_as_previous": True}]


@pytest.mark.parametrize("mode", ["ugc", "influencer"])
def test_assemble_on_camera_modes(mode):
    p = director.assemble(mode, {"title": "T", "character": "a woman", "voice_style": "warm", "shots": SHOTS},
                          seconds=10, aspect="9:16", quality="draft", language="English", seed=1,
                          persona="mia" if mode == "influencer" else None, product_desc="a serum")
    assert p.scenes[1].continuity == "continue" and p.scenes[0].dialogue
    assert p.scenes[0].products == ["product"]  # the visual mentions the bottle
    assert (p.characters[0].persona == "mia") == (mode == "influencer")
    assert p.captions.enabled == (mode == "influencer")


def test_assemble_faceless():
    beats = {"title": "T", "shots": [{"visual": "storm over the ocean", "narration": "Nobody tells you this"},
                                     {"visual": "a lighthouse at night", "narration": "but it changes everything"}]}
    p = director.assemble("faceless", beats, seconds=6, aspect="9:16", quality="draft", language="English", seed=1)
    assert all(s.voiceover for s in p.scenes) and p.captions.enabled and p.captions.position == "middle"


def test_assemble_promo_from_site():
    beats = {"title": "Acme", "tagline": "Simpler menus", "offer": "30 days free",
             "hook": [{"visual": "a crowded café", "narration": "Paper menus again?", "caption": "Paper menus?"}],
             "reveal": {"headline": "Meet Acme", "narration": "Meet Acme, the QR menu."},
             "screens": [{"page": "https://acme.test/menu", "eyebrow": "No app", "headline": "Scan and go",
                          "bullets": ["a", "b"], "narration": "Scan it and your menu opens."}],
             "features": {"headline": "All in one", "narration": "Everything in one place.",
                          "items": [{"title": "Fast", "icon": "zap"}, {"title": "Bad", "icon": "nope"},
                                    {"title": "Safe", "icon": "lock"}]},
             "lifestyle": {"visual": "friends laughing at dinner", "caption": "Enjoy"},
             "end": {"narration": "Acme. Thirty days free at acme dot test."}}
    site = {"url": "https://acme.test", "links": ["https://acme.test/menu"]}
    p = director.assemble("promo", beats, seconds=30, aspect="16:9", quality="tv", language="English", seed=1,
                          brand=Brand(name="Acme", url="https://acme.test"), site=site)
    kinds = [s.kind for s in p.scenes]
    assert kinds[0] == "shot" and "title" in kinds and "screen" in kinds and kinds[-1] == "endcard"
    assert p.scene("screen1").url == "https://acme.test/menu"
    assert p.scene("features").features[1].icon == "sparkles"  # invalid icon replaced
    assert p.target_seconds == 30 and p.brand.offer == "30 days free"


def test_brand_from_site_prefers_logo_colors():
    b = director.brand_from_site({"title": "Acme — menus", "url": "https://acme.test", "palette": {"primary": "#6c2bd9"},
                                  "font_heading": '"Bricolage Grotesque", Inter', "font_body": "Inter, sans"})
    assert b.name == "Acme" and b.primary == "#6c2bd9" and b.font_heading == "Bricolage Grotesque Variable"


# ---------------------------------------------------------------- fix planning
def test_plan_fix_sizes():
    assert plan_fix(2.0, 0.1, "auto", 5.0).kind == "interpolate"
    r = plan_fix(0.2, 0.4, "auto", 5.0)
    assert r.kind == "retake" and r.start == 0.0 and r.end - r.start >= 1.0
    r = plan_fix(4.9, 0.3, "retake", 5.0)
    assert r.end <= 5.0 and r.end - r.start >= 1.0
    with pytest.raises(ValueError, match="too long"):
        plan_fix(2.0, 1.5, "interpolate", 5.0)


# ---------------------------------------------------------------- CLI
runner = CliRunner()


def test_cli_discovery_commands():
    for cmd in (["modes"], ["transitions"], ["styles"], ["icons"], ["--help"]):
        r = runner.invoke(app, cmd)
        assert r.exit_code == 0, r.output


def test_cli_plan_status_fix_undo(tmp_path, calls):
    folder = write_project(tmp_path / "p", textwrap.dedent("""
        title: CLI test
        mode: ugc
        quality: draft
        music: {mode: none}
        scenes:
          - {id: s01, prompt: a person waves, seconds: 2}
          - {id: s02, prompt: a person smiles, seconds: 2, transition: {type: dissolve, seconds: 0.3}}
    """))
    r = runner.invoke(app, ["plan", str(folder)])
    assert r.exit_code == 0 and "Render plan" in r.output
    r = runner.invoke(app, ["render", str(folder), "--yes", "--no-qa"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["status", str(folder)])
    assert r.exit_code == 0 and "s02" in r.output
    r = runner.invoke(app, ["fix", str(folder), "--at", "2.5", "--duration", "0.08"])
    assert r.exit_code == 0 and "interpolate" in r.output, r.output
    assert Project.load(folder / "project.yaml").scene("s02").fixes
    calls.shots.clear()
    r = runner.invoke(app, ["render", str(folder), "--yes", "--no-qa"])
    assert r.exit_code == 0 and calls.shots == []
    r = runner.invoke(app, ["fix", str(folder), "--undo", "s02"])
    assert r.exit_code == 0 and not Project.load(folder / "project.yaml").scene("s02").fixes


def test_cli_invalid_project_gives_readable_error(tmp_path):
    folder = write_project(tmp_path / "bad", "title: x\nstyle: influencer\nscenes:\n  - {id: a, prompt: p}\n")
    r = runner.invoke(app, ["plan", str(folder)])
    assert r.exit_code == 1
    assert "style" in r.output and "Traceback" not in r.output


def test_reference_images_are_shrunk_for_memory():
    from PIL import Image

    from ugc_studio.keyframes import REF_MAX_PIXELS, _shrink

    small = _shrink(Image.new("RGB", (1088, 1920)), REF_MAX_PIXELS)
    assert small.width * small.height <= REF_MAX_PIXELS and small.width % 16 == 0


def test_captions_use_script_words_with_heard_timing():
    from ugc_studio.asr import align_to_script

    heard = [{"w": w, "t0": 10 + i * 0.3, "t1": 10.25 + i * 0.3} for i, w in
             enumerate("sans carte banser allez foncer".split())] + [{"w": "Sous-titrage", "t0": 20, "t1": 21}]
    out = align_to_script("Sans carte bancaire. Allez, foncez !", heard, 9.8, 12.0)
    assert [w["w"] for w in out] == ["Sans", "carte", "bancaire.", "Allez,", "foncez!"]
    assert out[0]["t0"] == 10 and out[-1]["t0"] == pytest.approx(11.2)


def test_pronunciation_dictionary_and_brand_equivalence():
    from ugc_studio.asr import similarity
    from ugc_studio.voice import spoken

    p = Project.model_validate({"title": "x", "pronounce": {"DZ-MeNU": "Dé-Zèd Menu"},
                                "scenes": [{"id": "a", "prompt": "p"}]})
    assert spoken(p, "DZ-MeNU. Trente jours gratuits.") == "Dé-Zèd Menu. Trente jours gratuits."
    assert similarity("DZ-MeNU. Trente jours gratuits.", "DZ Menu, 30 jours gratuits.") == 1.0
    assert similarity("Dé-Zèd Menu, trente jours gratuits.", "DZ Menu, 30 jours gratuits.") == 1.0


def test_narrated_shot_keeps_its_intended_length():
    """Regression: a 5 s transformation shot with a short voice line must not be cut to the line's length."""
    from ugc_studio.timeline import VoiceLine

    p = Project.model_validate({"title": "x", "mode": "promo", "fps": 25,
                                "scenes": [{"id": "m", "prompt": "a paper menu turns into a phone", "seconds": 5,
                                            "voiceover": "Short line."},
                                           {"id": "e", "kind": "endcard", "seconds": 3}]})
    tl = timeline.build(p, {"m": VoiceLine("x.wav", 0.1, 1.6)})
    assert tl.slot("m").dur == pytest.approx(121 / 25, abs=0.01)


def test_phonetic_rules_substitution_vs_elision():
    """Unit check of the phoneme comparison with synthetic phoneme strings (no audio model)."""
    import ugc_studio.phonetics as ph

    exp = [("trente", ["t", "ʁ", "ɑ̃", "t"]), ("bancaire", ["b", "ɑ̃", "k", "ɛ", "ʁ"])]

    def run(heard):
        orig_e, orig_h = ph.expected_words, ph.heard_phonemes
        ph.expected_words = lambda text, lang: exp
        ph.heard_phonemes = lambda path: heard
        try:
            return [f["word"] for f in ph.check("x", "trente bancaire", "French")["flagged"]]
        finally:
            ph.expected_words, ph.heard_phonemes = orig_e, orig_h

    assert run(["t", "ʁ", "ɑ̃", "b", "ɑ̃", "k", "ɛ", "ʁ"]) == []            # final t elided: fine
    assert run(["t", "ʁ", "ɑ̃", "t", "b", "ɑ̃", "ʃ", "ɛ", "ʁ"]) == ["bancaire"]  # k -> ʃ: flagged


def test_invented_words_after_the_line_are_cut(tmp_path, monkeypatch):
    """TTS runaway ("...فقط لتعشر من أبعضه"): audio after the last scripted word is removed."""
    import numpy as np
    import soundfile as sf

    import ugc_studio.asr as asr_mod
    from ugc_studio.voice import trim_to_script

    wav = tmp_path / "l.wav"
    sf.write(wav, np.zeros(24000 * 6, np.float32), 24000)
    heard = [{"w": w, "t0": 0.3 + 0.4 * i, "t1": 0.6 + 0.4 * i} for i, w in
             enumerate("تصبح قائمتك رقمية في دقيقتين فقط لتعشر من أبعضه ألا".split())]
    monkeypatch.setattr(asr_mod, "transcribe", lambda p, language=None, rate=16000, device=None: {"text": "", "words": []})
    trim_to_script(wav, {"text": "", "words": heard}, "تصبح قائمتك رقمية في دقيقتين فقط.",
                   "تصبح قائمتك رقمية في دقيقتين فقط.", "Arabic")
    dur = sf.info(str(wav)).duration
    assert abs(dur - (heard[5]["t1"] + 0.25)) < 0.02  # ends right after "فقط"


def test_word_check_tolerates_brand_spelling_and_digits_but_not_errors():
    from ugc_studio.asr import similarity

    names = ["DZ-MeNU", "دي زاد مينيو"]
    assert similarity("مع دي زاد مينيو، تصبح قائمتك رقمية", "مع ديزا دامينيو تصبح قائمتك رقمية", "Arabic", names) == 1.0
    assert similarity("ثلاثون يوماً مجاناً", "30 يوماً مجاناً", "Arabic") == 1.0
    assert similarity("sans carte bancaire", "sans carte banchaire", "French", names) < 0.9


def test_tts_breath_after_the_last_word_is_cut(tmp_path):
    import numpy as np
    import soundfile as sf

    from ugc_studio.voice import cut_tail

    sr = 24000
    t = np.arange(sr * 2) / sr
    speech = 0.3 * np.sin(2 * np.pi * 220 * t)
    breath = 0.03 * np.random.default_rng(0).standard_normal(sr)  # -30 dB mumble 0.6 s after the words
    wav = np.concatenate([speech, np.zeros(int(sr * 0.6)), breath]).astype(np.float32)
    p = tmp_path / "l.wav"
    sf.write(p, wav, sr)
    assert cut_tail(p, 2.0)
    assert abs(sf.info(str(p)).duration - 2.12) < 0.05


def test_misspelled_brand_at_the_start_is_not_cut(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf

    import ugc_studio.asr as asr_mod
    from ugc_studio.voice import trim_to_script

    wav = tmp_path / "l.wav"
    sf.write(wav, np.zeros(24000 * 4, np.float32), 24000)
    heard = [{"w": w, "t0": 0.2 + 0.4 * i, "t1": 0.5 + 0.4 * i} for i, w in
             enumerate("ماء ديزا دامينيو تصبح قائمتك رقمية".split())]
    monkeypatch.setattr(asr_mod, "transcribe", lambda *a, **k: {"text": "", "words": []})
    trim_to_script(wav, {"text": "", "words": heard}, "مع DZ-MeNU، تصبح قائمتك رقمية.",
                   "مع دي زاد مينيو، تصبح قائمتك رقمية.", "Arabic")
    assert sf.info(str(wav)).duration == 4.0  # nothing cut: the head is the (misheard) brand


def test_missing_brand_is_an_error():
    from ugc_studio.asr import similarity

    names = ["DZ-MeNU", "دي زاد مينيو"]
    assert similarity("مع دي زاد مينيو، تصبح قائمتك رقمية في دقيقتين فقط.", "تصبح قائمتك رقمية في دقيقتين فقط",
                      "Arabic", names) < 0.9


def test_stray_sound_after_the_line_marks_script_end(tmp_path):
    import numpy as np
    import soundfile as sf

    from ugc_studio.voice import trim_to_script

    wav = tmp_path / "l.wav"
    sf.write(wav, np.zeros(24000 * 5, np.float32), 24000)
    heard = [{"w": "بدون", "t0": 2.5, "t1": 2.8}, {"w": "بطاقة", "t0": 2.8, "t1": 3.2},
             {"w": "بنكية", "t0": 3.2, "t1": 3.8}, {"w": "و...", "t0": 4.5, "t1": 4.9}]
    tr = trim_to_script(wav, {"text": "", "words": heard}, "بدون بطاقة بنكية.", "بدون بطاقة بنكية.", "Arabic")
    assert tr["script_end"] == 3.8


def test_devices_in_keyframes_are_unbranded():
    from ugc_studio.schema import Project
    from ugc_studio.styles import keyframe_prompt

    p = Project.model_validate({"title": "t", "scenes": [
        {"id": "a", "prompt": "a woman at her desk, laptop open behind her"},
        {"id": "b", "prompt": "a woman at her desk, a plain laptop (no logo) behind her"}]})
    assert "no visible logos" in keyframe_prompt(p, p.scenes[0])
    assert "no visible logos" not in keyframe_prompt(p, p.scenes[1])


def test_words_split_or_joined_differently_count_as_said():
    from ugc_studio.asr import similarity

    assert similarity("ويخرجلك الأساسي في ثواني", "ويخرج لك الأساسي في ثواني", "Arabic") == 1.0
    assert similarity("ويخرجلك الأساسي", "ويخرج الأساسي", "Arabic") < 1.0


def test_best_sounding_take_with_every_word_right_is_kept(tmp_path, monkeypatch):
    from pathlib import Path

    import numpy as np
    import soundfile as sf

    import ugc_studio.asr as asr_mod
    import ugc_studio.phonetics as ph_mod
    import ugc_studio.quality as q_mod
    import ugc_studio.voice as v_mod
    from ugc_studio.schema import Project
    from ugc_studio.state import State

    line = "Bonjour à tous et bienvenue"
    p = Project.model_validate({"title": "t", "language": "French",
                                "voice": {"candidates": 3, "min_accuracy": 1.0, "engine": "chatterbox"},
                                "scenes": [{"id": "a", "kind": "title", "voiceover": line}]})
    heard = {"a": "Bonjour à tous", "a.take1": line, "a.take2": line}   # take 0 misses words
    rating = {"a": 4.9, "a.take1": 3.8, "a.take2": 4.4}

    def fake_worker(job, workdir, engine="qwen"):
        Path(job["out_dir"]).mkdir(parents=True, exist_ok=True)
        for item in job["lines"]:
            y = np.full(24000, rating[item["id"]] / 10, np.float32)  # amplitude encodes which take it is
            sf.write(Path(job["out_dir"]) / f"{item['id']}.wav", y, 24000)

    def take_of(path):
        amp = round(float(sf.read(str(path))[0][0]) * 10, 1)
        return next(k for k, v in rating.items() if abs(v - amp) < 0.05)

    monkeypatch.setattr(v_mod, "_run_worker", fake_worker)
    monkeypatch.setattr(asr_mod, "transcribe", lambda path, language=None, **k: {
        "text": heard[take_of(path)], "words": [{"w": w, "t0": 0.1 * i, "t1": 0.1 * i + 0.08}
                                               for i, w in enumerate(heard[take_of(path)].split())]})
    monkeypatch.setattr(asr_mod, "unload", lambda: None)
    monkeypatch.setattr(ph_mod, "check", lambda path, script, language: {"score": 1.0, "flagged": []})
    monkeypatch.setattr(v_mod, "cut_tail", lambda *a, **k: False)
    monkeypatch.setattr(q_mod, "score", lambda path: rating[take_of(path)])
    st = State(tmp_path)
    v_mod.build(p, st, tmp_path / "voice")
    assert st.get("voice:a")["quality"] == 4.4 and st.get("voice:a")["score"] == 1.0
    assert take_of(tmp_path / "voice" / "a.wav") == "a.take2"


def test_dotenv_example_parses_to_clean_values():
    from ugc_studio.config import ROOT, parse_dotenv

    d = parse_dotenv((ROOT / ".env.example").read_text())
    assert d["UGC_VIDEO_PROVIDER"] == "local" and d["UGC_IMAGE_MODEL"] == "" and d["UGC_HF_PROVIDER"] == "hf-inference"
    assert all("#" not in v for v in d.values())
    assert parse_dotenv('A="x # y"\nB=tok # note\nC=\nD=a#b') == {"A": "x # y", "B": "tok", "C": "", "D": "a#b"}


def test_stale_lines_detects_new_text_take_and_engine(tmp_path):
    from ugc_studio.schema import Project
    from ugc_studio.state import State
    from ugc_studio.voice import stale_lines

    p = Project.model_validate({"title": "t", "language": "French", "voice": {"engine": "chatterbox"},
                                "scenes": [{"id": "a", "kind": "title", "voiceover": "Bonjour"},
                                           {"id": "b", "kind": "title", "voiceover": "Salut"}]})
    st = State(tmp_path)
    (tmp_path / "a.wav").write_bytes(b"x")
    for sid, text in (("a", "Bonjour"), ("b", "Salut")):
        st.commit(f"voice:{sid}", {"t": text}, [tmp_path / "a.wav"], transcript=text, text=text, engine="chatterbox",
                  take=0)
    assert stale_lines(p, st) == []
    p.scenes[0].voiceover = "Bonsoir"
    p.scenes[1].voice_take = 1
    assert stale_lines(p, st) == ["a", "b"]
    p.scenes[0].voiceover, p.scenes[1].voice_take = "Bonjour", 0
    p.voice.engine = "qwen"
    assert stale_lines(p, st) == ["a", "b"]


def test_voice_commands_never_render_video(tmp_path):
    from typer.testing import CliRunner

    from ugc_studio.cli import app

    (tmp_path / "project.yaml").write_text(textwrap.dedent("""
        title: t
        mode: faceless
        quality: draft
        music: {mode: none}
        scenes:
          - {id: s01, prompt: a city at night, seconds: 3, voiceover: Hello there}
    """))
    r = CliRunner().invoke(app, ["voice", "set", str(tmp_path), "s01", "Good evening"])
    assert r.exit_code == 1 and "needs new video" in r.output.replace("\n", " ")
    assert "Good evening" in (tmp_path / "project.yaml").read_text()  # the text change itself is saved
    assert (tmp_path / "project.yaml.bak").is_file()


def test_dialect_spelling_tolerance_is_opt_in_and_word_by_word():
    from ugc_studio.asr import similarity

    assert similarity("الدوسيات بزاف والوقت قليل", "الدوسيات بالزاف والوقت قليل", "Arabic") < 1.0   # strict
    assert similarity("الدوسيات بزاف والوقت قليل", "الدوسيات بالزاف والوقت قليل", "Arabic", spelling=0.8) == 1.0
    assert similarity("الدوسيات بزاف والوقت قليل", "الدوسيات والوقت قليل", "Arabic", spelling=0.8) < 1.0  # missing word


def test_second_opinion_only_for_arabic(monkeypatch):
    import ugc_studio.asr as asr_mod

    assert asr_mod.second_opinion("x.wav", "French") is None
    monkeypatch.setattr(asr_mod, "ARABIC_ASR", "whisper")
    assert asr_mod.second_opinion("x.wav", "Arabic") is None


def test_local_keyframes_route_to_the_best_available_engine(monkeypatch):
    import ugc_studio.providers.local as loc

    made = []

    class Fake:
        def __init__(self, *a, **k):
            made.append(type(self).__name__)

        def generate(self, *a, **k):
            return "img"

        def close(self):
            made.append("close")

    for n in ("FluxImage", "QwenEditImage", "ZImageImage"):
        fake = type(n, (Fake,), {"available": classmethod(lambda cls: True)})
        monkeypatch.setattr(loc, n, fake)
    monkeypatch.delenv("UGC_KEYFRAME_EDIT", raising=False)
    monkeypatch.delenv("UGC_KEYFRAME_T2I", raising=False)
    r = loc.LocalImage()
    assert r.route == {"refs": "qwen-edit", "text": "zimage"}
    r.generate("p", 512, 512, 1, references=["a.png"])
    r.generate("p", 512, 512, 1, references=["b.png"])   # same engine: not reloaded
    r.generate("p", 512, 512, 1)                          # text only: switch engine (the other is closed first)
    assert made == ["QwenEditImage", "close", "ZImageImage"]
    monkeypatch.setattr(loc.QwenEditImage, "available", classmethod(lambda cls: False))
    monkeypatch.setattr(loc.ZImageImage, "available", classmethod(lambda cls: False))
    assert loc.LocalImage().route == {"refs": "flux", "text": "flux"}
    monkeypatch.setenv("UGC_KEYFRAME_EDIT", "flux")
    assert loc.LocalImage().route["refs"] == "flux"


def test_env_example_is_safe_for_docker_compose():
    """Compose keeps an inline comment after an empty value (`KEY=   # note` -> "# note"): comments on own lines."""
    import re

    from ugc_studio.config import ROOT, env

    lines = (ROOT / ".env.example").read_text().splitlines()
    assert not [ln for ln in lines if re.match(r"^[A-Z0-9_]+=\S*\s+#", ln)]
    import os
    os.environ["UGC_TEST_COMMENT"] = "# [4]"
    assert env("UGC_TEST_COMMENT", "4") == "4"
