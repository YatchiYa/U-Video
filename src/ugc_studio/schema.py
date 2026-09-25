"""Project schema (v2): one YAML file fully describes a video. Everything else is derived and cached.

A project is a list of scenes. Scene kinds:
  shot      AI live action (LTX-2.5): prompt + optional dialogue (UGC lip-sync) or voice-over, captions
  image     a still you provide (product photo, screenshot) animated with a camera move
  title     kinetic headline on a brand background
  screen    device mockup (phone / laptop) playing a real scroll recording of a URL, or an image
  features  animated feature cards
  endcard   logo, headline, offer, URL, phone, scannable QR code
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ugc: creator testimonial on camera | influencer: persistent AI persona on camera (reusable)
# faceless: viral narrated video (TTS + b-roll + big captions) | promo: product/brand commercial from a URL
Mode = Literal["ugc", "influencer", "faceless", "promo"]
Style = Literal["ugc", "promo", "anime", "cinematic", "realistic"]
Continuity = Literal["cut", "match", "continue"]
TransitionType = Literal[
    "cut", "dissolve", "fade", "fadewhite", "wipe", "slide", "zoom", "whip", "circle", "brand"
]
SceneKind = Literal["shot", "clip", "image", "title", "screen", "devices", "features", "endcard"]
FixKind = Literal["interpolate", "retake", "freeze"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Transition(Strict):
    type: TransitionType = "cut"
    seconds: float = Field(0.4, ge=0.0, le=2.0)


class Fix(Strict):
    """A non-destructive repair recorded in the project and re-applied on every build."""

    kind: FixKind
    start: float = Field(ge=0.0)  # seconds, local to the scene's raw clip
    end: float = Field(gt=0.0)
    prompt: str | None = None  # retake: what the region should show (defaults to the scene prompt)
    seed: int | None = None
    video: bool = True
    audio: bool = False

    @model_validator(mode="after")
    def _order(self) -> Fix:
        if self.end <= self.start:
            raise ValueError(f"fix end ({self.end}) must be after start ({self.start})")
        return self


class Device(Strict):
    url: str | None = None  # recorded live, scrolling
    image: str | None = None  # or a screenshot
    label: str = ""

    @model_validator(mode="after")
    def _src(self) -> Device:
        if not (self.url or self.image):
            raise ValueError("a device needs `url` or `image`")
        return self


class ScreenInsert(Strict):
    """Show the REAL app/website on a phone filmed by the AI (green-screen replacement)."""

    url: str | None = None  # recorded live, scrolling
    image: str | None = None  # or a static screenshot
    scroll: bool = True

    @model_validator(mode="after")
    def _src(self) -> ScreenInsert:
        if not (self.url or self.image):
            raise ValueError("screen_insert needs `url` or `image`")
        return self


class Feature(Strict):
    title: str
    subtitle: str = ""
    icon: str = "sparkles"  # any Lucide icon name


class Scene(Strict):
    id: str
    kind: SceneKind = "shot"
    seconds: float = Field(5.0, gt=0.4, le=30.0)

    # ---- shot ----
    prompt: str = ""  # what happens on screen (camera, action, light, sound)
    dialogue: str | None = None  # UGC: spoken on camera, lip-synced by the video model
    continuity: Continuity = "cut"  # cut: own keyframe | match: pinned seam | continue: from previous last frame
    start_image: str | None = None  # your first frame (otherwise generated from start_prompt)
    start_prompt: str | None = None
    end_image: str | None = None  # optional last frame to land on
    end_prompt: str | None = None
    characters: list[str] = Field(default_factory=list)  # ids from Project.characters kept consistent
    products: list[str] = Field(default_factory=list)  # ids from Project.products
    clip_in: float = Field(0.0, ge=0.0)  # skip the first seconds of the generated clip
    screen_insert: ScreenInsert | None = None  # phone in this shot displays your real app (green-screen replace)
    seed: int | None = None  # changes this shot's keyframe AND video
    take: int = Field(0, ge=0)  # new video take with the same keyframes (`ugc fix --mode reshoot`)
    fixes: list[Fix] = Field(default_factory=list)

    # ---- any kind ----
    voiceover: str | None = None  # promo narration for this scene (TTS)
    caption: list[str] = Field(default_factory=list)  # on-screen kinetic lines
    transition: Transition = Field(default_factory=Transition)  # transition INTO this scene
    ambience: float = Field(0.35, ge=0.0, le=1.0)  # level of the clip's own sound

    # ---- clip: your own footage ----
    video: str | None = None  # a video file used as this shot (trimmed with clip_in / seconds)

    # ---- image / screen ----
    image: str | None = None
    url: str | None = None
    device: Literal["phone", "laptop", "none"] = "phone"
    reveal: Literal["rise", "spin", "flip"] = "rise"  # screen: how the device enters (spin = 3D spin + light burst)
    theme: Literal["auto", "light", "dark"] = "auto"  # background of graphics scenes
    devices: list[Device] = Field(default_factory=list)  # devices: several screens fanned out in 3D
    headline: str | None = None
    eyebrow: str | None = None
    bullets: list[str] = Field(default_factory=list)

    # ---- features ----
    features: list[Feature] = Field(default_factory=list)

    # ---- endcard ----
    offer: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not v or not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"scene id {v!r} must be alphanumeric (with - or _)")
        return v

    @model_validator(mode="after")
    def _kind_requirements(self) -> Scene:
        if self.kind == "shot" and not self.prompt.strip():
            raise ValueError(f"scene {self.id}: a shot needs a prompt")
        if self.kind == "clip" and not self.video:
            raise ValueError(f"scene {self.id}: a clip scene needs `video` (your footage)")
        if self.kind == "image" and not (self.image or self.start_prompt):
            raise ValueError(f"scene {self.id}: an image scene needs `image` (your file) or `start_prompt` (generated)")
        if self.kind == "screen" and not (self.url or self.image):
            raise ValueError(f"scene {self.id}: a screen scene needs `url` or `image`")
        if self.kind == "devices" and not 2 <= len(self.devices) <= 4:
            raise ValueError(f"scene {self.id}: a devices scene needs 2 to 4 `devices`")
        if self.kind == "features" and not self.features:
            raise ValueError(f"scene {self.id}: a features scene needs `features`")
        if self.dialogue and self.voiceover:
            raise ValueError(f"scene {self.id}: use either dialogue (on camera) or voiceover, not both")
        return self


class Character(Strict):
    id: str
    description: str = ""  # identity text reused in every prompt: age, face, hair, outfit
    images: list[str] = Field(default_factory=list)  # your photos; if empty a reference portrait is generated
    persona: str | None = None  # name of a saved persona (`ugc persona`): brings its images, description, voice


class Product(Strict):
    id: str
    description: str
    images: list[str] = Field(default_factory=list)  # real product photos keep labels/logos correct


class Brand(Strict):
    name: str = ""
    tagline: str = ""
    url: str = ""
    phone: str = ""
    offer: str = ""
    logo: str | None = None  # svg/png
    primary: str = "#6c2bd9"
    secondary: str = "#a163ff"
    dark: str = "#161320"
    light: str = "#fbf9f6"
    accent: str = "#23a55a"
    font_heading: str = "Bricolage Grotesque Variable"
    font_body: str = "Inter Variable"


class Voice(Strict):
    """Promo narration (TTS). UGC dialogue uses the video model's native voice instead."""

    enabled: bool = True
    description: str = (
        "A warm, confident, professional male voice-over artist for a premium TV commercial, rich medium-low "
        "pitch, clear diction, friendly energy, natural pacing."
    )
    reference_audio: str | None = None  # clone this voice instead of designing one
    reference_text: str | None = None
    tempo: float = Field(1.0, ge=0.8, le=1.2)
    # auto: Qwen3-TTS for its 10 languages, Chatterbox (MIT, 23 languages incl. Arabic) otherwise,
    # Habibi (Apache-2.0 checkpoints) when an Arabic `dialect` is set.
    engine: Literal["auto", "qwen", "chatterbox", "habibi"] = "auto"
    dialect: Literal["MSA", "ALG", "EGY", "IRQ", "MAR"] | None = None  # Arabic dialect (Habibi)
    min_accuracy: float = Field(0.9, ge=0.5, le=1.0)  # word accuracy a narration line must reach (1.0 = every word)
    retries: int | None = Field(None, ge=1, le=20)  # attempts per line (default: 3 Qwen, 5 others)
    candidates: int = Field(1, ge=1, le=8)  # takes per attempt; the best-sounding one with every word right is kept
    # Your own finished voice-over (mp3/wav/m4a...): used as the narration, cut per scene automatically.
    file: str | None = None


class Music(Strict):
    mode: Literal["generate", "file", "none"] = "generate"
    prompt: str = "Uplifting modern commercial instrumental, warm, optimistic, clean punchy mix, no vocals"
    file: str | None = None
    volume: float = Field(0.55, ge=0.0, le=1.5)
    bpm: int | None = None


class Captions(Strict):
    """Word-by-word captions from the real audio (Whisper timing)."""

    enabled: bool = False
    style: Literal["tiktok", "clean", "none"] = "tiktok"
    position: Literal["bottom", "middle", "top"] = "bottom"


class Project(Strict):
    title: str
    mode: Mode = "ugc"
    style: Style = "ugc"
    aspect: Literal["9:16", "16:9", "1:1", "4:5"] = "9:16"
    quality: Literal["draft", "standard", "high", "tv"] = "standard"
    fps: int = Field(24, ge=12, le=60)
    language: str = "English"
    seed: int = 42
    target_seconds: float | None = None  # fit the edit exactly to this length (e.g. 15 / 30 / 60)
    source_url: str | None = None  # promo: the product website (read for text, brand and screen recordings)
    look: str = ""  # global visual direction appended to every shot
    # How to SAY words (narration): written -> spoken, e.g. {"DZ-MeNU": "Dé-Zèd Menu", "dz-menu.com": "dé-zèd tiret
    # menu point com"}. Scripts and captions keep the written form; only the voice uses the spoken form.
    pronounce: dict[str, str] = Field(default_factory=dict)
    voice_style: str = ""  # UGC: how the on-camera person sounds (kept identical across shots)
    brand: Brand = Field(default_factory=Brand)
    characters: list[Character] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    voice: Voice = Field(default_factory=Voice)
    music: Music = Field(default_factory=Music)
    captions: Captions = Field(default_factory=Captions)
    color_match: bool = True  # grade every shot to the first shot's look
    image_candidates: int = Field(2, ge=1, le=6)  # keyframes: generate N, keep the best (prompt + identity scores)
    visual_check: bool = True  # every shot: black/frozen/identity-drift check with automatic re-take
    speech_check: bool = True  # transcribe every on-camera line right after rendering; re-shoot if it's wrong
    speech_min: float = Field(0.95, ge=0.5, le=1.0)  # minimum word accuracy for a take to be accepted
    speech_retries: int = Field(2, ge=0, le=5)  # extra takes (new seeds) before keeping the best one
    logo_bug: bool = False  # small brand badge on live-action scenes
    scenes: list[Scene]

    @model_validator(mode="after")
    def _refs(self) -> Project:
        ids = [s.id for s in self.scenes]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate scene ids: {sorted(dupes)}")
        chars = {c.id for c in self.characters}
        prods = {p.id for p in self.products}
        for s in self.scenes:
            for c in s.characters:
                if c not in chars:
                    raise ValueError(f"scene {s.id}: unknown character {c!r} (known: {sorted(chars)})")
            for p in s.products:
                if p not in prods:
                    raise ValueError(f"scene {s.id}: unknown product {p!r} (known: {sorted(prods)})")
        if self.scenes and self.scenes[0].continuity != "cut":
            self.scenes[0].continuity = "cut"
        if self.scenes:
            self.scenes[0].transition = Transition(type="cut", seconds=0.0)
        return self

    # ---------------------------------------------------------------- io
    @classmethod
    def load(cls, path: str | Path) -> Project:
        path = Path(path)
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a project file")
        data = _migrate_v1(data)
        proj = cls.model_validate(data)
        proj._resolve_paths(path.parent)
        return proj

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            yaml.safe_dump(
                self.model_dump(mode="json", exclude_defaults=True), sort_keys=False, allow_unicode=True, width=110
            )
        )

    def _resolve_paths(self, base: Path) -> None:
        def res(p: str | None) -> str | None:
            if not p:
                return p
            q = Path(p).expanduser()
            return str(q if q.is_absolute() else (base / q).resolve())

        self.brand.logo = res(self.brand.logo)
        self.voice.reference_audio = res(self.voice.reference_audio)
        self.voice.file = res(self.voice.file)
        self.music.file = res(self.music.file)
        for c in self.characters:
            c.images = [res(i) for i in c.images]
        for p in self.products:
            p.images = [res(i) for i in p.images]
        for s in self.scenes:
            s.start_image, s.end_image, s.image = res(s.start_image), res(s.end_image), res(s.image)
            s.video = res(s.video)
            for dv in s.devices:
                dv.image = res(dv.image)
            if s.screen_insert:
                s.screen_insert.image = res(s.screen_insert.image)

    def missing_files(self) -> list[str]:
        paths = [self.brand.logo, self.voice.reference_audio, self.music.file if self.music.mode == "file" else None]
        paths += [i for c in self.characters for i in c.images] + [i for p in self.products for i in p.images]
        paths += [p for s in self.scenes for p in (s.start_image, s.end_image, s.image)]
        paths += [dv.image for s in self.scenes for dv in s.devices]
        return [p for p in paths if p and not Path(p).is_file()]

    def scene(self, sid: str) -> Scene:
        for s in self.scenes:
            if s.id == sid:
                return s
        raise KeyError(f"no scene {sid!r}; scenes: {[s.id for s in self.scenes]}")


def _migrate_v1(data: dict) -> dict:
    """Accept v1 storyboards (shots/references/voice string) so older examples keep working."""
    if "scenes" in data or "shots" not in data:
        return data
    out = {k: v for k, v in data.items() if k in ("title", "style", "aspect", "quality", "seed", "look")}
    out["mode"] = "ugc"
    if isinstance(data.get("voice"), str):
        out["voice_style"] = data["voice"]
    refs = data.get("references") or []
    if refs or data.get("reference_prompt") or data.get("look"):
        out["characters"] = [{"id": "hero", "description": data.get("look") or data.get("reference_prompt", ""),
                              "images": refs}]
    scenes = []
    for s in data["shots"]:
        sc = {"id": s["id"], "kind": "shot", "seconds": s.get("seconds", 5.0), "prompt": s["prompt"],
              "continuity": s.get("continuity", "cut")}
        for k_old, k_new in (("dialogue", "dialogue"), ("image", "start_image"), ("keyframe_prompt", "start_prompt"),
                             ("seed", "seed")):
            if s.get(k_old) is not None:
                sc[k_new] = s[k_old]
        if out.get("characters") and s.get("use_character_ref", True):
            sc["characters"] = ["hero"]
        scenes.append(sc)
    out["scenes"] = scenes
    return out
