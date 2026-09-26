"""Google Gemini API (API key, not Vertex): Veo 3.1 video, Gemini image ("Nano Banana") and Gemini TTS.

Auth: GEMINI_API_KEY (header x-goog-api-key). Docs: ai.google.dev/gemini-api/docs/{veo,image-generation,
speech-generation} (checked 2026-09-25). Images and speech use the Interactions API (the documented path for the
3.x models); Veo uses predictLongRunning.
"""

from __future__ import annotations

import base64
from pathlib import Path

from ugc_studio.providers.base import (ImageBackend, VideoBackend, VoiceBackend, aspect_of, check, client,
                                       conform_clip, download, image_b64, need_key, pick_duration, poll,
                                       save_image_bytes)

API = "https://generativelanguage.googleapis.com/v1beta"


def _auth() -> dict:
    return {"x-goog-api-key": need_key("GEMINI_API_KEY", "Gemini")}


def _outputs(data: dict, kind: str) -> list[dict]:
    """Content blocks of `kind` (image/audio/video) in an Interactions response."""
    blocks = []
    for step in data.get("steps", []):
        if step.get("type") == "model_output":
            blocks += [c for c in step.get("content", []) if c.get("type") == kind]
    return blocks


class GeminiImage(ImageBackend):
    name = "gemini"
    supports_references = True
    ASPECTS = ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"]

    def __init__(self, model: str | None = None):
        self.model = model or "gemini-3.1-flash-image"

    def generate(self, prompt, width, height, seed, references=None, out_path=None):
        inputs = [{"type": "text", "text": prompt}]
        inputs += [{"type": "image", "mime_type": "image/png", "data": image_b64(r)} for r in (references or [])[:14]]
        body = {"model": self.model, "input": inputs,
                "response_format": {"type": "image", "mime_type": "image/png",
                                    "aspect_ratio": aspect_of(width, height, self.ASPECTS),
                                    "image_size": "2K" if max(width, height) > 1024 else "1K"}}
        with client(timeout=300) as c:
            data = check(c.post(f"{API}/interactions", headers=_auth(), json=body), "Gemini image").json()
        images = _outputs(data, "image")
        if not images:
            raise RuntimeError(f"Gemini returned no image: {str(data)[:300]}")
        return save_image_bytes(base64.b64decode(images[0]["data"]), width, height, out_path)


class VeoVideo(VideoBackend):
    """Veo 3.1: first + last frame, native audio (ambience and speech), 4/6/8 s clips at 24 fps."""

    name = "veo"
    makes_audio = True
    supports_end_frame = True

    def __init__(self, model: str | None = None):
        self.model = model or "veo-3.1-generate-preview"

    def render(self, prompt, out_path, width, height, num_frames, seed, images=None, fps=24):
        out_path = Path(out_path)
        seconds = num_frames / fps
        hd = max(width, height) >= 1920  # tv quality
        duration = 8 if hd else pick_duration(seconds, [4, 6, 8])  # 1080p requires 8 s
        instance = {"prompt": prompt}
        start = [c for c in images or [] if c.frame_idx == 0]
        end = [c for c in images or [] if c.frame_idx > 0]
        if start:
            instance["image"] = {"inlineData": {"mimeType": "image/png", "data": image_b64(start[0].path)}}
            if end:  # lastFrame only together with a first frame
                instance["lastFrame"] = {"inlineData": {"mimeType": "image/png", "data": image_b64(end[0].path)}}
        params = {"aspectRatio": aspect_of(width, height, ["16:9", "9:16"]), "durationSeconds": str(duration),
                  "resolution": "1080p" if hd else "720p", "seed": seed}
        # image-to-video only allows adult people; text-to-video only `allow_all`
        params["personGeneration"] = "allow_adult" if start else "allow_all"
        with client(timeout=120) as c:
            op = check(c.post(f"{API}/models/{self.model}:predictLongRunning", headers=_auth(),
                              json={"instances": [instance], "parameters": params}), "Veo").json()
            name = op["name"]
            done = poll(lambda: check(c.get(f"{API}/{name}", headers=_auth()), "Veo").json(),
                        lambda d: d.get("done", False),
                        lambda d: (d.get("error") or {}).get("message"), "Veo", timeout=900, every=10)
        samples = done["response"]["generateVideoResponse"]["generatedSamples"]
        raw = download(samples[0]["video"]["uri"], out_path.with_suffix(".veo.mp4"), headers=_auth(), provider="Veo")
        conform_clip(raw, out_path, width, height, num_frames, fps)
        raw.unlink(missing_ok=True)
        return out_path


class GeminiVoice(VoiceBackend):
    """Gemini TTS: 30 prebuilt voices, style from voice.description; WAV 24 kHz mono."""

    name = "gemini"

    def __init__(self, model: str | None = None):
        self.model = model or "gemini-3.8-flash-tts"

    def synthesize(self, lines, out_dir, language, voice):
        out_dir.mkdir(parents=True, exist_ok=True)
        with client(timeout=300) as c:
            for line in lines:
                body = {"model": self.model,
                        "input": [{"type": "user_input", "content": [{
                            "type": "text", "text": line["text"],
                            "annotations": [{"type": "speech_metadata", "style": voice.description}]}]}],
                        "response_format": {"type": "audio", "mime_type": "audio/wav", "sample_rate": 24000},
                        "generation_config": {"speech_config": [{"voice": voice.voice_id or "Charon"}]}}
                data = check(c.post(f"{API}/interactions", headers=_auth(), json=body), "Gemini TTS").json()
                audio = _outputs(data, "audio")
                if not audio:
                    raise RuntimeError(f"Gemini TTS returned no audio: {str(data)[:300]}")
                (out_dir / f"{line['id']}.wav").write_bytes(base64.b64decode(audio[0]["data"]))
