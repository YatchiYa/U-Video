"""ElevenLabs: narration (text-to-speech, Arabic included) and instrumental music.

Auth: ELEVENLABS_API_KEY (header xi-api-key). Spec: api.elevenlabs.io/openapi.json (checked 2026-09-25).
Audio comes back as MP3 (available on every plan) and is converted to WAV for the pipeline.
"""

from __future__ import annotations

import os

from ugc_studio.providers.base import MusicBackend, ProviderError, VoiceBackend, check, client, need_key

API = "https://api.elevenlabs.io/v1"


def _auth() -> dict:
    return {"xi-api-key": need_key("ELEVENLABS_API_KEY", "ElevenLabs")}


def _mp3_to_wav(data: bytes, out, mono: bool = True) -> None:
    from ugc_studio.media import ffmpeg

    tmp = out.with_suffix(".mp3")
    tmp.write_bytes(data)
    ffmpeg(["-i", str(tmp), *(["-ac", "1"] if mono else []), str(out)])
    tmp.unlink(missing_ok=True)


class ElevenLabsVoice(VoiceBackend):
    """Any ElevenLabs voice (library or your cloned voice): set voice.voice_id or ELEVENLABS_VOICE_ID."""

    name = "elevenlabs"

    def __init__(self, model: str | None = None):
        self.model = model or "eleven_multilingual_v2"  # Arabic supported (also eleven_v3, eleven_flash_v2_5)

    def synthesize(self, lines, out_dir, language, voice):
        voice_id = voice.voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
        if not voice_id:
            raise ProviderError("ElevenLabs needs a voice: set voice.voice_id in project.yaml or ELEVENLABS_VOICE_ID "
                                "in .env (copy the id from your ElevenLabs voice library).")
        out_dir.mkdir(parents=True, exist_ok=True)
        with client(timeout=300) as c:
            for line in lines:
                body = {"text": line["text"], "model_id": self.model, "seed": int(line.get("seed", 7)) % 4294967295,
                        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0,
                                           "use_speaker_boost": True}}
                r = check(c.post(f"{API}/text-to-speech/{voice_id}", params={"output_format": "mp3_44100_128"},
                                 headers=_auth(), json=body), "ElevenLabs TTS")
                _mp3_to_wav(r.content, out_dir / f"{line['id']}.wav")


class ElevenLabsMusic(MusicBackend):
    name = "elevenlabs"

    def __init__(self, model: str | None = None):
        self.model = model or "music_v2"

    def generate(self, caption, seconds, bpm, seed, candidates, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt = f"{caption} Tempo {bpm} BPM." if bpm else caption
        length_ms = int(min(600_000, max(3_000, round(seconds * 1000))))
        with client(timeout=600) as c:
            for k in range(candidates):  # `seed` cannot be combined with a prompt: each call is a new take
                r = check(c.post(f"{API}/music", headers=_auth(),
                                 json={"prompt": prompt[:4100], "music_length_ms": length_ms, "model_id": self.model,
                                       "force_instrumental": True}), "ElevenLabs music")
                _mp3_to_wav(r.content, out_dir / f"cand{k}.wav", mono=False)
