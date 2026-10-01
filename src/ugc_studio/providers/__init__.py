"""Pluggable generation providers: every capability can run locally (default) or on a cloud API.

Choice, highest priority first:
  1. project.yaml   providers: {image: openai, video: kling, music: elevenlabs, video_model: ...}
                    (video: local | veo | kling | seedance; image: local | openai | gemini | huggingface)
                    voice.engine: elevenlabs | openai | gemini | qwen | chatterbox | habibi | higgs
  2. environment    UGC_IMAGE_PROVIDER, UGC_VIDEO_PROVIDER, UGC_VOICE_PROVIDER, UGC_MUSIC_PROVIDER
                    (+ UGC_*_MODEL to pick the provider's model), usually in .env
  3. default        local open-source models (FLUX.2 klein, LTX-2.5, Qwen3-TTS/Chatterbox/Habibi, ACE-Step)

Modules are imported only when used: a cloud provider never loads torch, a local one never needs an API key.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass

from ugc_studio.providers.base import ProviderError

IMAGE = {
    "local": "ugc_studio.providers.local:LocalImage",
    "openai": "ugc_studio.providers.openai:OpenAIImage",
    "gemini": "ugc_studio.providers.gemini:GeminiImage",
    "huggingface": "ugc_studio.providers.huggingface:HFImage",
}
VIDEO = {
    "local": "ugc_studio.render:ShotRenderer",
    "veo": "ugc_studio.providers.gemini:VeoVideo",
    "kling": "ugc_studio.providers.kling:KlingVideo",
    "seedance": "ugc_studio.providers.seedance:SeedanceVideo",
}
# Local narration engines (qwen, chatterbox, habibi) run in their own environments via voice.py.
VOICE = {
    "openai": "ugc_studio.providers.openai:OpenAIVoice",
    "elevenlabs": "ugc_studio.providers.elevenlabs:ElevenLabsVoice",
    "gemini": "ugc_studio.providers.gemini:GeminiVoice",
}
MUSIC = {
    "local": "ugc_studio.providers.local:LocalMusic",
    "elevenlabs": "ugc_studio.providers.elevenlabs:ElevenLabsMusic",
}
REGISTRY = {"image": IMAGE, "video": VIDEO, "voice": VOICE, "music": MUSIC}
LOCAL_VOICES = ("qwen", "chatterbox", "habibi", "higgs")

# API key each cloud provider needs (shown by `ugc providers`)
KEYS = {
    "openai": ["OPENAI_API_KEY"],
    "gemini": ["GEMINI_API_KEY"], "veo": ["GEMINI_API_KEY"],
    "elevenlabs": ["ELEVENLABS_API_KEY"],
    "kling": ["KLING_API_KEY"],
    "seedance": ["ARK_API_KEY"],
    "huggingface": ["HF_TOKEN"],
}


# License terms of the local defaults (checked 2026-09-26, see docs/LICENSES.md). Not legal advice.
LICENSE_NOTES = {
    ("image", "local"): "FLUX.2 klein 4B: Apache-2.0 (the 9B variant is non-commercial)",
    ("video", "local"): "LTX-2.5: LTX Community License, free under $10M annual revenue; disclose AI-generated content",
    ("voice", "qwen"): "Qwen3-TTS: Apache-2.0",
    ("voice", "chatterbox"): "Chatterbox: MIT (outputs carry an inaudible Perth watermark)",
    ("voice", "habibi"): "Habibi-TTS: commercial use UNCERTAIN (fine-tuned from the CC-BY-NC F5-TTS base)",
    ("voice", "higgs"): "Higgs TTS 3: research and non-commercial (creator grant for social videos, with attribution)",
    ("music", "local"): "ACE-Step 1.5: MIT; Stable Audio 3 (if installed): Stability AI Community License, free under $1M revenue",
}


@dataclass(frozen=True)
class Choice:
    kind: str
    provider: str
    model: str | None
    source: str  # "project", "env" or "default"


def choice(project, kind: str) -> Choice:
    """Which provider (and model) this project uses for `kind` (image, video, voice, music)."""
    project = project if project is not None else _default_project()
    if kind == "voice":
        v = project.voice
        if v.engine != "auto":
            return Choice(kind, v.engine, v.model, "project")
        env = os.environ.get("UGC_VOICE_PROVIDER", "").strip().lower()
        if env and env != "auto":
            return Choice(kind, env, v.model or os.environ.get("UGC_VOICE_MODEL") or None, "env")
        return Choice(kind, "auto", v.model, "default")
    pr = project.providers
    name, model = getattr(pr, kind), getattr(pr, f"{kind}_model")
    if name:
        return Choice(kind, name, model or os.environ.get(f"UGC_{kind.upper()}_MODEL") or None, "project")
    env = os.environ.get(f"UGC_{kind.upper()}_PROVIDER", "").strip().lower()
    if env:
        return Choice(kind, env, model or os.environ.get(f"UGC_{kind.upper()}_MODEL") or None, "env")
    return Choice(kind, "local", model or os.environ.get(f"UGC_{kind.upper()}_MODEL") or None, "default")


def load(kind: str, name: str):
    table = REGISTRY[kind]
    if name not in table:
        raise ProviderError(f"Unknown {kind} provider {name!r}. Available: {', '.join(sorted(table))}")
    module, cls = table[name].split(":")
    return getattr(importlib.import_module(module), cls)


def create(project, kind: str, **kwargs):
    """Instantiate the backend chosen for `kind` (checks API keys early, with a clear message)."""
    c = choice(project, kind)
    for var in KEYS.get(c.provider, []):
        if not os.environ.get(var, "").strip():
            raise ProviderError(f"{kind} provider {c.provider!r} needs {var} in .env (see .env.example).")
    cls = load(kind, c.provider)
    if c.provider == "local" and kind == "video":
        return cls(**kwargs)
    return cls(model=c.model, **kwargs) if c.model else cls(**kwargs)


def _default_project():
    """Settings of a bare project: what .env / defaults give when no project.yaml is involved."""
    from ugc_studio.schema import Project

    return Project.model_validate({"title": "defaults", "scenes": [{"id": "s", "kind": "title"}]})


def describe(project=None) -> list[dict]:
    """Resolved configuration for display (`ugc providers`, API)."""
    p = project if project is not None else _default_project()
    rows = []
    for kind in ("image", "video", "voice", "music"):
        c = choice(p, kind)
        keys = KEYS.get(c.provider, [])
        rows.append({"kind": kind, "provider": c.provider, "model": c.model, "source": c.source,
                     "license": LICENSE_NOTES.get((kind, c.provider)) or ("provider terms of service"
                                                                         if c.provider not in ("local", "auto") else None),
                     "keys": {k: bool(os.environ.get(k, "").strip()) for k in keys},
                     "available": sorted(REGISTRY[kind]) + (list(LOCAL_VOICES) if kind == "voice" else [])})
    return rows
