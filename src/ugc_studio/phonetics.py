"""Pronunciation check at the phoneme level.

Whisper is a language model: it "hears" the word it expects ("bancaire") even when the speaker said "banchaire".
Here the audio is transcribed into raw phonemes by a CTC model with no language model
(facebook/wav2vec2-xlsr-53-espeak-cv-ft), and compared word by word with the expected pronunciation of the script
(espeak-ng). A word is flagged when its consonants don't match: /bɑ̃kɛʁ/ said as /bɑ̃ʃɛʁ/.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache

import numpy as np

from ugc_studio.config import PHONEME_MODEL

ESPEAK_LANG = {"french": "fr-fr", "english": "en-us", "spanish": "es", "german": "de", "italian": "it",
               "portuguese": "pt", "dutch": "nl", "turkish": "tr", "russian": "ru"}
VOWELS = set("aeiouyɑɐɒæɛɜəɘɵɪʊʏøœɔɤʌɯɨʉ")
# Recognizers confuse these even on correct speech: treat as one sound.
VOWEL_CLASS = {"ɑ": "a", "ɐ": "a", "æ": "a", "ɛ": "e", "ɜ": "e", "ə": "e", "œ": "e", "ø": "e", "ɘ": "e",
               "ɔ": "o", "ɒ": "o", "ɪ": "i", "ʊ": "u", "ʏ": "y", "ɑ̃": "ɑ̃", "ɔ̃": "ɑ̃", "ɛ̃": "ɛ̃", "œ̃": "ɛ̃"}
# Voiced/voiceless pairs assimilate naturally in connected speech ("carte bancaire" -> [kaʁd bɑ̃kɛʁ]): not an error.
VOICING = {"d": "t", "b": "p", "ɡ": "k", "g": "k", "z": "s", "v": "f", "ʒ": "ʃ"}
CONSONANT_MIN = 0.75  # a word whose consonants match less than this is mispronounced


def _espeak():
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())


@lru_cache(maxsize=1)
def _model():
    from transformers import AutoProcessor, Wav2Vec2ForCTC

    proc = AutoProcessor.from_pretrained(PHONEME_MODEL)
    model = Wav2Vec2ForCTC.from_pretrained(PHONEME_MODEL).eval()
    vocab = sorted((t for t in proc.tokenizer.get_vocab() if not t.startswith("<") and t.strip()), key=len, reverse=True)
    return proc, model, vocab


def supported(language: str) -> bool:
    return language.lower() in ESPEAK_LANG


def _tokens(ipa: str, vocab: list[str]) -> list[str]:
    """Greedy longest-match split of an IPA string into the recognizer's phoneme inventory."""
    out, i = [], 0
    ipa = ipa.replace("ˈ", "").replace("ˌ", "").replace("ː", "")
    while i < len(ipa):
        if ipa[i].isspace():
            i += 1
            continue
        for v in vocab:
            if ipa.startswith(v, i):
                out.append(v)
                i += len(v)
                break
        else:
            out.append(ipa[i])
            i += 1
    return out


def _norm(p: str) -> str:
    return VOWEL_CLASS.get(p, p)


def _is_consonant(p: str) -> bool:
    return not any(ch in VOWELS for ch in p) and p not in ("ɑ̃", "ɔ̃", "ɛ̃", "œ̃")


def expected_words(text: str, language: str) -> list[tuple[str, list[str]]]:
    from phonemizer import phonemize

    _espeak()
    words = [w for w in re.findall(r"[\w'’-]+", text) if re.search(r"\w", w)]
    ipas = phonemize(words, language=ESPEAK_LANG[language.lower()], backend="espeak", strip=True, with_stress=False,
                     language_switch="remove-flags")
    vocab = _model()[2]
    return [(w, _tokens(ipa, vocab)) for w, ipa in zip(words, ipas)]


def heard_phonemes(path_or_audio, rate: int = 16000) -> list[str]:
    import torch

    from ugc_studio.asr import load_audio

    audio = load_audio(str(path_or_audio), rate) if not isinstance(path_or_audio, np.ndarray) else path_or_audio
    proc, model, _ = _model()
    with torch.inference_mode():
        logits = model(proc(audio, sampling_rate=rate, return_tensors="pt").input_values).logits
    return proc.batch_decode(torch.argmax(logits, -1))[0].split()


def check(path, script: str, language: str) -> dict:
    """{"score": 0-1, "flagged": [{"word", "expected", "heard"}]} comparing speech with the script's pronunciation."""
    exp = expected_words(script, language)
    heard = heard_phonemes(path)
    flat, owner = [], []
    for k, (_, ph) in enumerate(exp):
        flat += ph
        owner += [k] * len(ph)
    sm = SequenceMatcher(None, [_norm(p) for p in flat], [_norm(p) for p in heard], autojunk=False)
    got: list[str | None] = [None] * len(flat)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                got[i1 + k] = heard[j1 + k]
        elif tag == "replace":
            for k in range(min(i2 - i1, j2 - j1)):
                got[i1 + k] = heard[j1 + k]
    flagged, scores = [], []
    for k, (word, ph) in enumerate(exp):
        idx = [i for i, o in enumerate(owner) if o == k]
        cons = [i for i in idx if _is_consonant(flat[i])]
        match = [i for i in idx if got[i] is not None and _norm(got[i]) == _norm(flat[i])]
        c_match = [i for i in cons if got[i] is not None and VOICING.get(got[i], got[i]) == VOICING.get(flat[i], flat[i])]
        # A dropped word-final consonant is normal connected speech ("trente jours" -> [tʁɑ̃ʒuʁ]); only a
        # substituted consonant ("bancaire" -> [bɑ̃ʃɛʁ]) or a lost inner consonant is a mispronunciation.
        if cons and cons[-1] == idx[-1] and got[cons[-1]] is None:
            cons = cons[:-1]
        scores.append(len(match) / max(1, len(idx)))
        # Only judge words with enough consonants: 1-2 phoneme words are too noisy to call.
        if len(cons) >= 2 and len(c_match) / len(cons) < CONSONANT_MIN:
            flagged.append({"word": word, "expected": "".join(flat[i] for i in idx),
                            "heard": "".join(got[i] or "·" for i in idx)})
    return {"score": round(float(np.mean(scores)) if scores else 1.0, 3), "flagged": flagged,
            "heard": " ".join(heard)}
