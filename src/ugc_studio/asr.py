"""Whisper (large-v3-turbo) transcription with word timestamps: voice QA, synced animation, captions."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache

import numpy as np

from ugc_studio.config import ARABIC_ASR, ASR_MODEL

LANG_CODES = {"english": "english", "french": "french", "spanish": "spanish", "german": "german", "italian": "italian",
              "portuguese": "portuguese", "arabic": "arabic", "russian": "russian", "japanese": "japanese",
              "korean": "korean", "chinese": "chinese", "turkish": "turkish", "dutch": "dutch"}


@lru_cache(maxsize=2)
def _pipe(device: str | None = None):
    import torch
    from transformers import pipeline

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    return pipeline("automatic-speech-recognition", model=ASR_MODEL,
                    dtype=torch.float16 if device == "cuda" else torch.float32, device=device)


@lru_cache(maxsize=1)
def _qwen_asr(device: str):
    import torch
    from transformers import AutoModelForMultimodalLM, AutoProcessor

    proc = AutoProcessor.from_pretrained(ARABIC_ASR)
    model = AutoModelForMultimodalLM.from_pretrained(
        ARABIC_ASR, dtype=torch.float16 if device == "cuda" else torch.float32).to(device).eval()
    return proc, model


def second_opinion(path_or_audio, language: str | None, device: str | None = None) -> str | None:
    """A second, more literal transcript for languages where Whisper is weak (Arabic: Qwen3-ASR). Whisper tends to
    "hear" the expected word; the speech gates require both transcripts to agree. None when not applicable."""
    if (language or "").lower() != "arabic" or ARABIC_ASR.lower() == "whisper":
        return None
    import torch

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    audio = load_audio(path_or_audio, 16000) if isinstance(path_or_audio, str) else path_or_audio
    if audio.size < 4000:
        return ""
    proc, model = _qwen_asr(device)
    inp = proc.apply_transcription_request(audio=audio, language="ar")
    inp = {k: (v.to(device, dtype=model.dtype) if v.is_floating_point() else v.to(device)) for k, v in inp.items()}
    with torch.inference_mode():
        out = model.generate(**inp, max_new_tokens=256, do_sample=False)
    return proc.decode(out[0][inp["input_ids"].shape[1]:], return_format="transcription_only").strip()


def unload() -> None:
    import torch

    _pipe.cache_clear()
    _qwen_asr.cache_clear()
    torch.cuda.empty_cache()


def load_audio(path: str, rate: int = 16000) -> np.ndarray:
    import av

    with av.open(str(path)) as c:
        if not c.streams.audio:
            return np.zeros(0, np.float32)
        rs = av.AudioResampler(format="fltp", layout="mono", rate=rate)
        chunks = [f.to_ndarray().ravel() for fr in c.decode(audio=0) for f in rs.resample(fr)]
        chunks += [f.to_ndarray().ravel() for f in rs.resample(None)]
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)


def transcribe(path_or_audio, language: str | None = None, rate: int = 16000, device: str | None = None) -> dict:
    """Returns {"text": str, "words": [{"w", "t0", "t1"}]}."""
    audio = load_audio(path_or_audio, rate) if isinstance(path_or_audio, str) else path_or_audio
    if audio.size < rate // 4:
        return {"text": "", "words": []}
    kw = {"task": "transcribe"}
    if language and language.lower() in LANG_CODES:
        kw["language"] = LANG_CODES[language.lower()]
    out = _pipe(device)({"raw": audio, "sampling_rate": rate}, return_timestamps="word", generate_kwargs=kw)
    words = [{"w": c["text"].strip(), "t0": round(c["timestamp"][0], 3),
              "t1": round(c["timestamp"][1] if c["timestamp"][1] is not None else c["timestamp"][0] + 0.2, 3)}
             for c in out.get("chunks", []) if c["text"].strip()]
    return {"text": out["text"].strip(), "words": words}


_EQUIV = [("’", "'"), ("-", " "), ("dé zèd", "dz"), ("vingt quatre", "24"), ("trente", "30"), ("deux", "2"),
          ("point com", "com")]


_AR_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")


def _norm_arabic(t: str) -> str:
    """Spelling variants Whisper and writers mix freely: harakat, tatweel, alef/hamza forms, ta marbuta, alef maqsura."""
    t = _AR_DIACRITICS.sub("", t)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي"),
                 ("،", ","), ("؟", "?"), ("؛", ";")):
        t = t.replace(a, b)
    return t


def norm_words(text: str) -> list[str]:
    t = _norm_arabic(text).lower()
    for a, b in _EQUIV:
        t = t.replace(a, b)
    t = re.sub(r"[^\w' ]+", " ", t)
    # Silent plural endings (FR/EN): "réservations" and "réservation" sound identical.
    return [w[:-1] if len(w) > 3 and w[-1] in "sx" and w.isascii() else w for w in t.split()]


NUM_LANG = {"english": "en", "french": "fr", "spanish": "es", "german": "de", "italian": "it", "portuguese": "pt",
            "russian": "ru", "japanese": "ja", "korean": "ko", "arabic": "ar", "dutch": "nl", "polish": "pl",
            "turkish": "tr", "hindi": "hi", "hebrew": "he", "danish": "da", "finnish": "fi", "swedish": "sv",
            "norwegian": "no", "greek": "el"}


def _spell_numbers(words: list[str], language: str | None) -> list[str]:
    """ASR writes "30" where the script says "ثلاثون" / "trente": spell digits out in the script's language."""
    code = NUM_LANG.get((language or "").lower())
    if not code or not any(w.isdigit() for w in words):
        return words
    try:
        from num2words import num2words
    except ImportError:
        return words
    out = []
    for w in words:
        out += norm_words(num2words(int(w), lang=code)) if w.isdigit() and len(w) < 10 else [w]
    return out


def _collapse_names(words: list[str], names: list[list[str]]) -> list[str]:
    """Brand names have no fixed spelling in ASR output ("دي زاد مينيو" is heard as "ديزا دامينيو"): a run of
    words whose letters (spaces ignored) closely match a name becomes one token, so only real errors count."""
    for k, name in enumerate(names):
        target = "".join(name)
        if len(target) < 4:
            continue

        def match(i):
            best = None
            for n in range(max(1, len(name) - 1), len(name) + 2):
                if i + n <= len(words):
                    r = SequenceMatcher(None, target, "".join(words[i:i + n]), autojunk=False).ratio()
                    if r >= 0.8 and (best is None or r > best[0]):
                        best = (r, n)
            return best

        out, i = [], 0
        while i < len(words):
            best, nxt = match(i), match(i + 1)
            if best and nxt and nxt[0] > best[0]:  # "مع دي زاد مينيو": the name starts at the next word
                best = None
            if best:
                out.append(f"§{k}")
                i += best[1]
            else:
                out.append(words[i])
                i += 1
        words = out
    return words


def similarity(expected: str, heard: str, language: str | None = None, names: list[str] = (),
               spelling: float = 1.0) -> float:
    """Word accuracy of `heard` against `expected`; numbers and brand-name spellings are not counted as errors.
    `spelling` < 1: a word also counts when that share of its letters match (dialects have no fixed spelling:
    Algerian "بزاف" is also written "بالزاف")."""
    groups = [norm_words(n) for n in names if norm_words(n)]
    e = _collapse_names(_spell_numbers(norm_words(expected), language), groups)
    h = _collapse_names(_spell_numbers(norm_words(heard), language), groups)
    sm = SequenceMatcher(None, e, h, autojunk=False)
    matched = 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        # a word split or joined differently ("ويخرجلك" / "ويخرج لك", "aujourd'hui") is the same speech
        if op == "equal" or (op == "replace" and "".join(e[i1:i2]) == "".join(h[j1:j2])):
            matched += (i2 - i1) + (j2 - j1)
        elif op == "replace" and spelling < 1.0 and (i2 - i1) == (j2 - j1):
            matched += 2 * sum(SequenceMatcher(None, a, b, autojunk=False).ratio() >= spelling
                               for a, b in zip(e[i1:i2], h[j1:j2]))
    return matched / max(1, len(e) + len(h))


def align_to_script(script: str, heard: list[dict], t0: float, t1: float) -> list[dict]:
    """Captions that show the SCRIPT's exact words with Whisper's timing.

    Heard words inside [t0, t1] are aligned to the script (difflib on normalized words). Matched words take
    the heard timing; script words Whisper misheard or missed are spread over the time of the heard words they
    replace (or interpolated between neighbours). Words heard outside the window are dropped, which removes
    hallucinations over music ("Sous-titrage...")."""
    words = [w for w in heard if w["t0"] >= t0 - 0.2 and w["t1"] <= t1 + 0.3]
    target: list[str] = []
    for tok in script.split():  # French spacing: "mieux ?" -> "mieux?" (punctuation is not a caption word)
        if target and not re.search(r"\w", tok):
            target[-1] += tok
        else:
            target.append(tok)
    if not target:
        return []
    if not words:  # nothing heard: spread the line evenly over the window
        step = (t1 - t0) / len(target)
        return [{"w": w, "t0": round(t0 + k * step, 3), "t1": round(t0 + (k + 1) * step, 3)} for k, w in enumerate(target)]
    key = lambda s: (norm_words(s) or [""])[0]  # noqa: E731
    sm = SequenceMatcher(None, [key(w) for w in target], [key(w["w"]) for w in words], autojunk=False)
    out: list[dict | None] = [None] * len(target)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = {"w": target[i1 + k], "t0": words[j1 + k]["t0"], "t1": words[j1 + k]["t1"]}
        elif tag == "replace":
            a, b = words[j1]["t0"], words[j2 - 1]["t1"]
            step = (b - a) / (i2 - i1)
            for k in range(i2 - i1):
                out[i1 + k] = {"w": target[i1 + k], "t0": round(a + k * step, 3), "t1": round(a + (k + 1) * step, 3)}
    # script words with no heard counterpart: interpolate between known neighbours
    for i, o in enumerate(out):
        if o is None:
            prev = next((out[k]["t1"] for k in range(i - 1, -1, -1) if out[k]), t0)
            nxt = next((out[k]["t0"] for k in range(i + 1, len(out)) if out[k]), max(prev + 0.25, t1))
            out[i] = {"w": target[i], "t0": round(prev, 3), "t1": round(max(prev + 0.08, min(nxt, prev + 0.4)), 3)}
    return out
