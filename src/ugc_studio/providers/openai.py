"""OpenAI: images (GPT Image, with reference images) and narration (gpt-4o-mini-tts).

Auth: OPENAI_API_KEY. Spec: github.com/openai/openai-openapi (checked 2026-09-25). The Sora video API was shut
down on 2026-09-24, so OpenAI is not offered as a video provider.
"""

from __future__ import annotations

import base64
from pathlib import Path

from ugc_studio.providers.base import ImageBackend, VoiceBackend, check, client, need_key, save_image_bytes

API = "https://api.openai.com/v1"


def _auth() -> dict:
    return {"Authorization": f"Bearer {need_key('OPENAI_API_KEY', 'OpenAI')}"}


def _size(width: int, height: int) -> str:
    """GPT Image 2+ accepts any WxH with sides divisible by 16 and ratio within 1:3..3:1 (keyframes already are)."""
    w, h = max(16, width // 16 * 16), max(16, height // 16 * 16)
    return f"{w}x{h}"


class OpenAIImage(ImageBackend):
    name = "openai"
    supports_references = True

    def __init__(self, model: str | None = None, quality: str = "high"):
        self.model = model or "gpt-image-2.5-flare"
        self.quality = quality

    def generate(self, prompt, width, height, seed, references=None, out_path=None):
        with client(timeout=300) as c:
            if references:
                # edits: up to 16 reference images as repeated `image[]` fields; high input fidelity keeps faces
                files = [("image[]", (Path(r).name, Path(r).read_bytes(), "image/png")) for r in references[:16]]
                data = {"model": self.model, "prompt": prompt, "size": _size(width, height), "quality": self.quality,
                        "input_fidelity": "high", "output_format": "png", "n": "1"}
                r = c.post(f"{API}/images/edits", headers=_auth(), data=data, files=files)
            else:
                r = c.post(f"{API}/images/generations", headers=_auth(),
                           json={"model": self.model, "prompt": prompt, "size": _size(width, height),
                                 "quality": self.quality, "output_format": "png", "n": 1})
            check(r, "OpenAI images")
        return save_image_bytes(base64.b64decode(r.json()["data"][0]["b64_json"]), width, height, out_path)


class OpenAIVoice(VoiceBackend):
    name = "openai"

    def __init__(self, model: str | None = None):
        self.model = model or "gpt-4o-mini-tts"

    def synthesize(self, lines, out_dir, language, voice):
        out_dir.mkdir(parents=True, exist_ok=True)
        body = {"model": self.model, "voice": voice.voice_id or "cedar", "response_format": "wav"}
        if not self.model.startswith("tts-1"):  # tts-1 / tts-1-hd take no instructions
            body["instructions"] = f"{voice.description} Speak in {language}."
        with client(timeout=300) as c:
            for line in lines:
                r = check(c.post(f"{API}/audio/speech", headers=_auth(), json={**body, "input": line["text"]}),
                          "OpenAI speech")
                (out_dir / f"{line['id']}.wav").write_bytes(r.content)
