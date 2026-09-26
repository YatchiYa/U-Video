"""Persona library: reusable identities (face, outfit, voice) for influencer / UGC videos.

personas/<name>/persona.yaml + reference images. A project character with `persona: <name>` inherits them,
so the same person looks and sounds the same in every video.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from ugc_studio.config import ROOT
from ugc_studio.schema import Project

PERSONAS_DIR = ROOT / "personas"

# Neutral identity shots: the keyframe generator borrows identity from these without copying pose or scene.
SHEET_VIEWS = [
    "head-and-shoulders portrait facing the camera, neutral relaxed expression",
    "three-quarter view portrait turned slightly left, soft smile",
    "waist-up portrait, natural confident posture, hands visible",
]


class Persona(BaseModel):
    name: str
    description: str  # age, ethnicity, face, hair, build, signature outfit
    voice_style: str = ""  # how they sound on camera, e.g. "a bright, friendly female voice, Parisian accent"
    language: str = "English"
    images: list[str] = Field(default_factory=list)  # file names inside the persona folder

    @property
    def folder(self) -> Path:
        return PERSONAS_DIR / _slug(self.name)

    def image_paths(self) -> list[str]:
        return [str(self.folder / i) for i in self.images]


def _slug(name: str) -> str:
    s = "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")
    if not s:
        raise ValueError(f"invalid persona name {name!r}")
    return s


def list_personas() -> list[Persona]:
    if not PERSONAS_DIR.is_dir():
        return []
    return [load(p.parent.name) for p in sorted(PERSONAS_DIR.glob("*/persona.yaml"))]


def load(name: str) -> Persona:
    path = PERSONAS_DIR / _slug(name) / "persona.yaml"
    if not path.is_file():
        known = [p.name for p in list_personas()] if PERSONAS_DIR.is_dir() else []
        raise FileNotFoundError(f"persona {name!r} not found. Known: {known}. Create one with `ugc persona create`.")
    return Persona.model_validate(yaml.safe_load(path.read_text()))


def save(p: Persona) -> Path:
    p.folder.mkdir(parents=True, exist_ok=True)
    out = p.folder / "persona.yaml"
    out.write_text(yaml.safe_dump(p.model_dump(), sort_keys=False, allow_unicode=True))
    return out


def create(name: str, description: str, images: list[str] | None = None, voice_style: str = "",
           language: str = "English", generate: int = 3, seed: int = 7) -> Persona:
    """Create a persona from your photos, or generate a consistent identity sheet from the description."""
    p = Persona(name=name, description=description, voice_style=voice_style, language=language)
    p.folder.mkdir(parents=True, exist_ok=True)
    for i, src in enumerate(images or []):
        src_p = Path(src).expanduser()
        if not src_p.is_file():
            raise FileNotFoundError(src)
        dst = f"ref_{i:02d}{src_p.suffix.lower()}"
        shutil.copy(src_p, p.folder / dst)
        p.images.append(dst)
    if not p.images and generate:
        from ugc_studio import providers

        gen = providers.create(None, "image")  # UGC_IMAGE_PROVIDER (default: local FLUX.2 klein)
        try:
            first = p.folder / "ref_00.png"
            gen.generate(f"Photorealistic {SHEET_VIEWS[0]} of {description}. Plain light gray seamless background, "
                         "soft even studio light, sharp focus, realistic skin texture, no text", 1024, 1280, seed,
                         out_path=first)
            p.images.append(first.name)
            for k, view in enumerate(SHEET_VIEWS[1:generate], start=1):
                out = p.folder / f"ref_{k:02d}.png"
                gen.generate(f"A new photo of the same person as in the reference image (same face, hair and outfit): "
                             f"{view}, plain light gray background, soft studio light, realistic skin texture, no text",
                             1024, 1280, seed + k, references=[first], out_path=out)
                p.images.append(out.name)
        finally:
            gen.close()
    save(p)
    return p


def apply(project: Project) -> Project:
    """Merge persona data into project characters (images, description) and the on-camera voice style."""
    for c in project.characters:
        if not c.persona:
            continue
        p = load(c.persona)
        if not c.images:
            c.images = p.image_paths()
        if not c.description:
            c.description = p.description
        if p.voice_style and not project.voice_style:
            project.voice_style = p.voice_style
    return project
