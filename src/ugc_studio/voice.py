"""Narration (promo / faceless): design one voice, clone it for every line, validate each line with Whisper."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from ugc_studio import asr, phonetics, quality
from ugc_studio.config import CHATTERBOX_PYTHON, HABIBI_PYTHON, ROOT, TTS_CLONE_MODEL, TTS_DESIGN_MODEL, TTS_PYTHON
from ugc_studio.schema import Project
from ugc_studio.state import State, ref
from ugc_studio.timeline import VoiceLine

log = logging.getLogger(__name__)
WORKERS = Path(__file__).parent / "workers"
WORKER = WORKERS / "tts_worker.py"
CHATTERBOX_LANGS = {"arabic": "ar", "danish": "da", "german": "de", "greek": "el", "english": "en", "spanish": "es",
                    "finnish": "fi", "french": "fr", "hebrew": "he", "hindi": "hi", "italian": "it", "japanese": "ja",
                    "korean": "ko", "malay": "ms", "dutch": "nl", "norwegian": "no", "polish": "pl",
                    "portuguese": "pt", "russian": "ru", "swedish": "sv", "swahili": "sw", "turkish": "tr",
                    "chinese": "zh"}
AR_REF_TEXT = ("في كل يوم، يكتشف آلاف الناس شيئًا جديدًا. واليوم، هناك طريقة أبسط للحصول على ما تحتاجه بالضبط، "
               "في ثوانٍ معدودة.")
TTS_LANGUAGES = {"chinese", "english", "japanese", "korean", "german", "french", "russian", "portuguese", "spanish",
                 "italian"}
REF_TEXT = {
    "english": "Every day, thousands of people discover something new. Today, there is a simpler way to get "
               "exactly what you need, in just a few seconds.",
    "french": "Chaque jour, des milliers de personnes découvrent quelque chose de nouveau. Aujourd'hui, il existe une "
              "façon plus simple d'obtenir exactement ce dont vous avez besoin.",
    "spanish": "Cada día, miles de personas descubren algo nuevo. Hoy existe una forma más sencilla de conseguir "
               "exactamente lo que necesitas, en pocos segundos.",
    "german": "Jeden Tag entdecken Tausende von Menschen etwas Neues. Heute gibt es einen einfacheren Weg, genau das "
              "zu bekommen, was Sie brauchen.",
    "italian": "Ogni giorno, migliaia di persone scoprono qualcosa di nuovo. Oggi esiste un modo più semplice per "
               "ottenere esattamente ciò di cui hai bisogno.",
    "portuguese": "Todos os dias, milhares de pessoas descobrem algo novo. Hoje existe uma forma mais simples de "
                  "conseguir exatamente o que você precisa.",
}
PASS = 0.9


def _run_worker(job: dict, workdir: Path, engine: str = "qwen") -> None:
    python, worker = {"qwen": (TTS_PYTHON, WORKER),
                      "chatterbox": (CHATTERBOX_PYTHON, WORKERS / "chatterbox_worker.py"),
                      "habibi": (HABIBI_PYTHON, WORKERS / "habibi_worker.py")}[engine]
    if not python.is_file():
        raise FileNotFoundError(f"{engine} voice environment missing ({python}). Run `ugc setup`.")
    workdir.mkdir(parents=True, exist_ok=True)
    jp = workdir / f"job_{engine}.json"
    jp.write_text(json.dumps(job, ensure_ascii=False))
    proc = subprocess.run([str(python), str(worker), str(jp)], capture_output=True, text=True, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"{engine} voice worker failed:\n{proc.stderr[-3000:]}")


def pick_engine(project: Project) -> str:
    v, lang = project.voice, project.language.lower()
    if v.engine != "auto":
        return v.engine
    if v.dialect and v.dialect != "MSA" and lang == "arabic":
        return "habibi"
    if lang in TTS_LANGUAGES:
        return "qwen"
    if lang in CHATTERBOX_LANGS:
        return "chatterbox"
    raise ValueError(f"No local voice for {project.language}. Supported: {sorted(TTS_LANGUAGES | set(CHATTERBOX_LANGS))}"
                     " (Arabic dialects via voice.dialect). Or record it yourself: voice.file: your_voiceover.mp3")


def _speech_bounds(path: Path) -> tuple[float, float]:
    wav, sr = sf.read(path, dtype="float32")
    wav = wav.mean(1) if wav.ndim > 1 else wav
    idx = np.flatnonzero(np.abs(wav) > 10 ** (-40 / 20))
    return (idx[0] / sr, idx[-1] / sr) if idx.size else (0.0, len(wav) / sr)


def check_language(project: Project) -> None:
    pick_engine(project)  # raises a clear message when no engine speaks the language
    lang = project.language.lower()
    if False and lang not in TTS_LANGUAGES:
        raise ValueError(
            f"Narration in {project.language} is not supported by the local TTS (supported: "
            f"{', '.join(sorted(TTS_LANGUAGES))}). For {project.language}, use on-camera dialogue "
            "(ugc / influencer mode: the video model speaks it), or set voice.enabled: false and add a voice-over "
            "file as music.file."
        )


def reference_voice(project: Project, state: State, workdir: Path) -> tuple[Path, str]:
    """The voice every line is cloned from: your recording, or a designed voice (best of 3 by accuracy)."""
    v = project.voice
    if v.reference_audio:
        text = v.reference_text or asr.transcribe(v.reference_audio, project.language)["text"]
        return Path(v.reference_audio), text
    lang = project.language.lower()
    text = REF_TEXT.get(lang) or next((s.voiceover for s in project.scenes if s.voiceover), "")
    inputs = {"instruct": v.description, "language": lang, "text": text, "model": TTS_DESIGN_MODEL}
    key = "voice:ref"
    out = workdir / "ref.wav"
    if state.fresh(key, inputs):
        return out, text
    _run_worker({"design_model": TTS_DESIGN_MODEL, "instruct": v.description, "language": project.language,
                 "ref_text": text, "design_candidates": 3, "out_dir": str(workdir)}, workdir)
    scores = []
    for k in range(3):
        p = workdir / f"ref_candidate{k}.wav"
        heard = asr.transcribe(str(p), project.language)["text"]
        scores.append((asr.similarity(text, heard, project.language), -abs(len(heard) - len(text)), k))
    best = max(scores)[2]
    shutil.copy(workdir / f"ref_candidate{best}.wav", out)
    state.commit(key, inputs, [out], candidates=[round(s[0], 3) for s in scores], chosen=best)
    log.info("Voice designed: candidate %d (accuracy %s)", best, [round(s[0], 2) for s in scores])
    return out, text


def _habibi_reference(project: Project, state: State, workdir: Path) -> tuple[Path, str]:
    v = project.voice
    if v.reference_audio:
        text = v.reference_text or asr.transcribe(v.reference_audio, "arabic")["text"]
        return Path(v.reference_audio), text
    inputs = {"text": AR_REF_TEXT, "engine": "chatterbox-ref"}
    out = workdir / "ref_ar.wav"
    if not state.fresh("voice:ref_ar", inputs):
        _run_worker({"language_id": "ar", "ref_audio": None, "out_dir": str(workdir),
                     "lines": [{"id": "ref_ar", "text": AR_REF_TEXT, "seed": 11}]}, workdir, "chatterbox")
        state.commit("voice:ref_ar", inputs, [out])
    return out, AR_REF_TEXT


def from_file(project: Project, state: State, workdir: Path) -> dict[str, VoiceLine]:
    """Your own voice-over: transcribed with word timings, then cut into one segment per narrated scene.
    Scenes with `voiceover` text are matched to where that text is spoken; if no scene has text, the sentences
    are distributed over the scenes in order (proportionally to their `seconds`) and become their captions."""
    import av

    from ugc_studio.media import ffmpeg

    src = Path(project.voice.file)
    inputs = {"file": ref(src), "language": project.language, "scenes": [s.voiceover for s in project.scenes]}
    tr_key = "voicefile:transcript"
    if not state.fresh(tr_key, {"file": ref(src), "language": project.language}):
        tr = asr.transcribe(str(src), project.language)
        (workdir / "voicefile.json").parent.mkdir(parents=True, exist_ok=True)
        (workdir / "voicefile.json").write_text(json.dumps(tr, ensure_ascii=False))
        state.commit(tr_key, {"file": ref(src), "language": project.language}, [workdir / "voicefile.json"])
    tr = json.loads((workdir / "voicefile.json").read_text())
    words = tr["words"]
    if not words:
        raise ValueError(f"{src.name}: no speech found in the voice-over file")
    with av.open(str(src)) as c:
        total = float(c.duration or 0) / 1e6 or words[-1]["t1"] + 0.3
    scenes = [s for s in project.scenes]
    spans: dict[str, tuple[float, float, str]] = {}
    texted = [s for s in scenes if s.voiceover]
    if texted:
        cursor = 0
        for s in texted:
            n = len(s.voiceover.split())
            seg = asr.align_to_script(s.voiceover, words[cursor:], words[min(cursor, len(words) - 1)]["t0"],
                                      words[min(len(words) - 1, cursor + n + 4)]["t1"])
            t0, t1 = seg[0]["t0"], seg[-1]["t1"]
            spans[s.id] = (t0, t1, s.voiceover)
            cursor = next((k for k, w in enumerate(words) if w["t0"] >= t1 - 0.05), len(words) - 1)
    else:
        # sentences: split at punctuation or pauses > 0.35 s
        sents, cur = [], []
        for k, w in enumerate(words):
            cur.append(w)
            gap = words[k + 1]["t0"] - w["t1"] if k + 1 < len(words) else 9
            if w["w"].rstrip()[-1:] in ".!?؟…" or gap > 0.35:
                sents.append(cur)
                cur = []
        if cur:
            sents.append(cur)
        weights = np.cumsum([max(0.1, s.seconds) for s in scenes])
        weights = weights / weights[-1]
        k0 = 0
        for i, s in enumerate(scenes):
            k1 = max(k0 + 1, round(weights[i] * len(sents))) if i < len(scenes) - 1 else len(sents)
            chunk = [w for sent in sents[k0:k1] for w in sent]
            if chunk:
                text = " ".join(w["w"] for w in chunk)
                spans[s.id] = (chunk[0]["t0"], chunk[-1]["t1"], text)
                s.voiceover = text  # becomes the scene's caption text
            k0 = k1
    out = {}
    ordered = sorted(spans.items(), key=lambda kv: kv[1][0])
    for idx, (sid, (t0, t1, text)) in enumerate(ordered):
        a = max(0.0, t0 - 0.12)
        nxt = ordered[idx + 1][1][0] if idx + 1 < len(ordered) else total
        b = min(total, max(t1 + 0.25, min(nxt - 0.02, t1 + 0.6)))
        p = workdir / f"{sid}.wav"
        key = f"voice:{sid}"
        cut_in = {"file": ref(src), "a": round(a, 3), "b": round(b, 3)}
        if not state.fresh(key, cut_in):
            ffmpeg(["-i", str(src), "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-ac", "1", "-ar", "24000", str(p)])
            local = [{"w": w["w"], "t0": round(w["t0"] - a, 3), "t1": round(w["t1"] - a, 3)}
                     for w in words if a <= w["t0"] <= b]
            state.commit(key, cut_in, [p], transcript=text, words=local, speech_start=round(t0 - a, 3),
                         speech_end=round(t1 - a, 3), score=1.0, source="your voice-over")
        m = state.get(key)
        out[sid] = VoiceLine(file=str(p), speech_start=m["speech_start"], speech_end=m["speech_end"],
                             words=m.get("words", []))
    asr.unload()
    return out


def spoken(project: Project, text: str) -> str:
    """Apply the project's pronunciation dictionary (longest entries first)."""
    for written in sorted(project.pronounce, key=len, reverse=True):
        text = text.replace(written, project.pronounce[written])
    return text


def names(project: Project) -> list[str]:
    """Brand/product names written and spoken: ASR spells them freely, so the word check tolerates their spelling."""
    out = [project.brand.name] if project.brand.name else []
    out += list(project.pronounce) + list(project.pronounce.values())
    return [n for n in out if n]


def cut_tail(path: Path, last_word_end: float, gap: float = 0.25, floor_db: float = -40.0) -> bool:
    """TTS engines often add a breath, mumble or noise after the sentence (0.5-1.5 s that lengthen every scene).
    Cut at the first real silence after the last word, with a short fade. Returns True when something was cut."""
    wav, sr = sf.read(path, dtype="float32")
    mono = wav.mean(1) if wav.ndim > 1 else wav
    hop = int(sr * 0.02)
    db = np.array([20 * np.log10(np.sqrt(np.mean(mono[i:i + hop] ** 2)) + 1e-9) for i in range(0, len(mono), hop)])
    start = max(0, int((last_word_end - 0.1) / 0.02))
    need = int(gap / 0.02)
    run = 0
    for k in range(start, len(db)):
        run = run + 1 if db[k] < floor_db else 0
        if run >= need:
            cut = int(((k - need + 1) * 0.02 + 0.12) * sr)
            if len(mono) - cut < int(0.3 * sr):
                return False
            out = wav[:cut].copy()
            fade = min(int(0.06 * sr), len(out))
            ramp = np.linspace(1, 0, fade, dtype=np.float32)
            out[-fade:] *= ramp[:, None] if out.ndim > 1 else ramp
            sf.write(path, out, sr)
            log.info("Voice line %s: cut %.2fs of breath/noise after the last word", path.stem, (len(mono) - cut) / sr)
            return True
    return False


def trim_to_script(path: Path, tr: dict, written: str, spoken_text: str, language: str) -> dict:
    """Remove words the voice invented after (or before) the scripted line, then re-transcribe.
    Works for every engine and language: the script's words are aligned to the heard words (with timing)."""
    words = tr.get("words") or []
    if not words:
        return tr
    from difflib import SequenceMatcher

    script = asr.norm_words(spoken_text) or asr.norm_words(written)
    heard = [(asr.norm_words(w["w"]) or [""])[0] for w in words]
    blocks = [b for b in SequenceMatcher(None, script, heard, autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return tr
    first, last = blocks[0].b, blocks[-1].b + blocks[-1].size - 1
    # Script words before the first / after the last match were said but heard differently (a brand name spelled
    # "ديزا دامينيو"): keep that many heard words. Only words beyond the script are invented.
    head_script = blocks[0].a
    tail_script = len(script) - (blocks[-1].a + blocks[-1].size)
    extra_head = first - head_script
    extra_tail = len(words) - 1 - last - tail_script
    # end of the scripted speech: a stray last sound ("و...") after it is cut by cut_tail
    tr = {**tr, "script_end": words[min(len(words) - 1, last + tail_script)]["t1"]}
    if extra_tail < 2 and extra_head < 2:
        return tr
    wav, sr = sf.read(path, dtype="float32")
    a = max(0.0, words[extra_head]["t0"] - 0.15) if extra_head >= 2 else 0.0
    b = min(len(wav) / sr, words[len(words) - 1 - extra_tail]["t1"] + 0.25) if extra_tail >= 2 else len(wav) / sr
    sf.write(path, wav[int(a * sr): int(b * sr)], sr)
    log.info("Voice line %s: trimmed %d invented word(s)", path.stem, extra_tail + extra_head)
    return asr.transcribe(str(path), language)


def build(project: Project, state: State, workdir: Path, retries: int | None = None) -> dict[str, VoiceLine]:
    """Generate (or reuse) every scene's narration. Returns scene id -> VoiceLine.
    The TTS receives the spoken form; accuracy is checked against the written script."""
    if project.voice.file:
        return from_file(project, state, workdir)
    written = {s.id: s.voiceover.strip() for s in project.scenes if s.voiceover and s.voiceover.strip()}
    lines = {sid: spoken(project, t) for sid, t in written.items()}
    if not lines or not project.voice.enabled:
        return {}
    engine = pick_engine(project)
    if retries is None:
        retries = project.voice.retries or (3 if engine == "qwen" else 5)
    need = max(PASS, project.voice.min_accuracy)
    if engine == "qwen":
        ref_audio, ref_text = reference_voice(project, state, workdir)
    elif engine == "chatterbox":  # its own MIT voice, or a clone of voice.reference_audio
        ref_audio, ref_text = (Path(project.voice.reference_audio) if project.voice.reference_audio else None), ""
    else:  # habibi needs a reference: yours, or an Arabic reference made with Chatterbox (rights-clean)
        ref_audio, ref_text = _habibi_reference(project, state, workdir)
    from ugc_studio.state import file_hash

    worker_file = {"qwen": WORKER, "chatterbox": WORKERS / "chatterbox_worker.py",
                   "habibi": WORKERS / "habibi_worker.py"}[engine]
    ref_in = {"ref": ref(ref_audio), "ref_text": ref_text, "language": project.language.lower(), "engine": engine,
              "dialect": project.voice.dialect, "worker": file_hash(worker_file)[:12], "post": 2,
              **({"candidates": project.voice.candidates} if project.voice.candidates > 1 else {})}  # bump when post-processing changes
    todo = [sid for sid, text in lines.items() if not state.fresh(f"voice:{sid}", {**ref_in, "text": text})]
    seed_of = {sid: 7 for sid in todo}
    n_cand = project.voice.candidates
    best: dict[str, dict] = {}  # best take so far per line: every word right first, then the best listener rating

    def evaluate(sid: str, p: Path, seed: int) -> dict:
        tr = asr.transcribe(str(p), project.language)
        tr = trim_to_script(p, tr, written[sid], lines[sid], project.language)
        if tr.get("words") and cut_tail(p, tr.get("script_end", tr["words"][-1]["t1"])):
            tr = asr.transcribe(str(p), project.language)
        score = max(asr.similarity(written[sid], tr["text"], project.language, names(project)),
                    asr.similarity(lines[sid], tr["text"], project.language, names(project)))
        flagged = []
        if phonetics.supported(project.language):
            flagged = [f["word"] for f in phonetics.check(p, lines[sid], project.language)["flagged"]]
        good = score >= need and not flagged
        mos = quality.mos(p) if (good and n_cand > 1) else None
        return {"path": p, "score": score, "flagged": flagged, "tr": tr, "seed": seed, "good": good, "mos": mos,
                "rank": (good, mos or 0.0, score - 0.1 * len(flagged))}

    for attempt in range(retries):
        if not todo:
            break
        # vary the sampling between attempts (a stuck line often needs a different guidance, not just a seed)
        cfg = [0.5, 0.35, 0.65, 0.45, 0.55][attempt % 5]
        batch = [{"id": sid if k == 0 else f"{sid}.take{k}", "text": lines[sid], "seed": seed_of[sid] + 1009 * k,
                  "cfg": cfg} for sid in todo for k in range(n_cand)]
        if engine == "qwen":
            _run_worker({"clone_model": TTS_CLONE_MODEL, "language": project.language, "ref_audio": str(ref_audio),
                         "ref_text": ref_text, "out_dir": str(workdir), "lines": batch}, workdir, "qwen")
        elif engine == "chatterbox":
            _run_worker({"language_id": CHATTERBOX_LANGS[project.language.lower()],
                         "ref_audio": str(ref_audio) if ref_audio else None, "exaggeration": 0.5, "cfg": 0.5,
                         "out_dir": str(workdir), "lines": batch}, workdir, "chatterbox")
        else:
            _run_worker({"dialect": project.voice.dialect, "ref_audio": str(ref_audio), "ref_text": ref_text,
                         "out_dir": str(workdir), "lines": batch}, workdir, "habibi")
        failed = []
        for sid in todo:
            takes = [evaluate(sid, workdir / (f"{sid}.wav" if k == 0 else f"{sid}.take{k}.wav"), seed_of[sid] + 1009 * k)
                     for k in range(n_cand)]
            top = max(takes, key=lambda t: t["rank"])
            for t in takes:
                if t["flagged"]:
                    log.warning("Voice line %s mispronounced %s (attempt %d)", sid, t["flagged"], attempt + 1)
            if sid not in best or top["rank"] > best[sid]["rank"]:
                shutil.copy(top["path"], workdir / f"{sid}.best.wav")
                best[sid] = top
            for t in takes[1:]:
                t["path"].unlink(missing_ok=True)
            if top["good"] or attempt == retries - 1:
                b = best[sid]
                p = workdir / f"{sid}.wav"
                shutil.copy(workdir / f"{sid}.best.wav", p)
                (workdir / f"{sid}.best.wav").unlink(missing_ok=True)
                s0, s1 = _speech_bounds(p)
                state.commit(f"voice:{sid}", {**ref_in, "text": lines[sid]}, [p], score=round(b["score"], 3),
                             mispronounced=b["flagged"], transcript=b["tr"]["text"], words=b["tr"]["words"],
                             speech_start=round(s0, 3), speech_end=round(s1, 3), seed=b["seed"],
                             mos=None if b["mos"] is None else round(b["mos"], 2))
                if not b["good"]:
                    log.warning("Voice line %s kept at %.0f%% accuracy (best of %d tries): %r", sid, b["score"] * 100,
                                retries, b["tr"]["text"])
            else:
                failed.append(sid)
                seed_of[sid] += 101
        todo = failed
    asr.unload()
    out = {}
    for sid in lines:
        a = state.get(f"voice:{sid}")
        out[sid] = VoiceLine(file=str(state.path_of(f"voice:{sid}")), speech_start=a["speech_start"],
                             speech_end=a["speech_end"], words=a.get("words", []))
    return out
