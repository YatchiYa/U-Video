"""Prompt language per visual style and mode, for LTX-2.5 (video) and FLUX.2 (keyframes)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ugc_studio.schema import Project, Scene


@dataclass(frozen=True)
class StylePreset:
    video: str  # appended to every LTX prompt
    image: str  # appended to every keyframe prompt
    director: str  # guidance for the LLM director


STYLES: dict[str, StylePreset] = {
    "ugc": StylePreset(
        video=("Authentic user-generated smartphone footage, handheld selfie-style camera with subtle natural shake, "
               "natural window daylight, realistic skin texture, casual real-life setting, candid and genuine."),
        image=("candid smartphone photo, front camera, natural daylight, realistic skin texture with pores, "
               "casual authentic setting, no text, no watermark"),
        director=("UGC ad: one relatable creator speaking directly to camera like a TikTok/Reels testimonial. Hook in "
                  "the first shot, show the product in use, honest benefit, clear call to action at the end."),
    ),
    "influencer": StylePreset(
        video=("Polished Instagram influencer content shot on a modern smartphone, flattering soft key light, "
               "aesthetic well-styled location, confident charismatic on-camera presence, crisp detail, natural motion."),
        image=("aesthetic Instagram influencer photo, flattering soft light, stylish location, sharp focus, realistic "
               "skin texture, no text, no watermark"),
        director=("Influencer video: a charismatic creator with a strong personality talks to camera, varied aesthetic "
                  "setups (home, street, café, car), punchy hook, value or story, call to follow or comment."),
    ),
    "promo": StylePreset(
        video=("High-end commercial cinematography, smooth gimbal and dolly camera moves, studio-grade lighting, "
               "crisp detail, shallow depth of field, premium color grade, no text, no logos."),
        image=("premium commercial photography, cinematic lighting, crisp detail, shallow depth of field, elegant "
               "composition, no text, no watermark"),
        director=("Promotional spot: problem, product reveal, product in use, key benefits, social proof, offer and "
                  "call to action. Confident narration, premium visuals."),
    ),
    "faceless": StylePreset(
        video=("Cinematic viral b-roll, dynamic camera movement, bold contrast, vivid colors, shallow depth of field, "
               "striking composition, crisp detail, no text, no logos."),
        image=("cinematic striking photo, bold contrast, vivid colors, dramatic light, shallow depth of field, "
               "no text, no watermark"),
        director=("Faceless viral video: a scroll-stopping hook in the first sentence, fast visual cuts every 2-3 "
                  "seconds, curiosity and payoff, short punchy narration, loop-friendly ending."),
    ),
    "anime": StylePreset(
        video=("2D Japanese anime style, clean cel shading, expressive characters, vibrant colors, hand-drawn "
               "background art, dynamic anime camera work, consistent character design."),
        image=("2D anime key visual, clean line art, cel shading, vibrant colors, detailed painted background, "
               "studio-quality anime illustration, no text, no watermark"),
        director="Anime short: expressive characters, clear emotional beats, dynamic framing, short dialogue lines.",
    ),
    "cinematic": StylePreset(
        video=("Cinematic film look, anamorphic lens, motivated lighting, rich color grade, natural film grain, "
               "deliberate camera movement."),
        image=("cinematic film still, anamorphic lens, motivated dramatic lighting, rich color grade, 35mm film grain, "
               "no text, no watermark"),
        director="Cinematic short film: strong visual storytelling, varied shot sizes, mood and atmosphere.",
    ),
    "realistic": StylePreset(
        video="Photorealistic footage, natural lighting, realistic motion and physics, true-to-life colors.",
        image="photorealistic photo, natural lighting, true-to-life colors, high detail, no text, no watermark",
        director="Realistic documentary-style footage with natural, believable moments.",
    ),
}


def preset(project: Project) -> StylePreset:
    """Visual preset: modes with their own look (influencer, faceless) override the generic style."""
    if project.mode in ("influencer", "faceless") and project.style in ("ugc", "promo"):
        return STYLES[project.mode]
    return STYLES[project.style]


def _identity(project: Project, scene: Scene) -> str:
    parts = [c.description for c in project.characters if c.id in scene.characters and c.description]
    parts += [p.description for p in project.products if p.id in scene.products and p.description]
    return " ".join(p.strip().rstrip(".") + "." for p in parts)


def video_prompt(project: Project, scene: Scene) -> str:
    """Final LTX prompt: action + identity + spoken line + style. On-camera speech starts immediately and ends
    explicitly (otherwise the model pads short lines by repeating words)."""
    parts = [scene.prompt.strip()]
    ident = _identity(project, scene)
    if ident:
        parts.append(ident)
    if scene.dialogue:
        voice = f" in {project.voice_style.strip()}" if project.voice_style.strip() else ""
        line = scene.dialogue.strip()
        for written in sorted(project.pronounce, key=len, reverse=True):
            line = line.replace(written, project.pronounce[written])
        parts.append(f'Right from the first second, speaking directly to the camera{voice}, they say: '
                     f'"{line}" Then they stop talking and simply smile, with no further words.')
    elif scene.voiceover or project.mode in ("faceless", "promo"):
        parts.append("No one speaks on camera; only natural ambient sound.")
    if scene.screen_insert:
        from ugc_studio.composite import GREEN_PROMPT

        parts.append(GREEN_PROMPT)
    if project.look:
        parts.append(project.look.strip())
    parts.append(preset(project).video)
    return " ".join(parts)


def keyframe_prompt(project: Project, scene: Scene, text: str | None = None, with_reference: bool = False) -> str:
    base = (text or scene.start_prompt or scene.prompt).strip().rstrip(".")
    if with_reference:
        base = ("A new photo of the same subject as in the reference images (same face, fur or hair, markings, "
                f"outfit, product design and label). {base}")
    ident = _identity(project, scene)
    look = f" {project.look.strip()}" if project.look else ""
    # Only frames that actually show a phone get the green screen (a morph's first frame may be a paper menu).
    if scene.screen_insert and re.search(r"phone|smartphone|screen|device|tablet|écran|téléphone", base, re.I):
        from ugc_studio.composite import GREEN_PROMPT

        base += ". " + GREEN_PROMPT.rstrip(".")
    # Third-party logos (a bitten apple on a laptop...) can't go on air: devices are drawn unbranded.
    if (re.search(r"laptop|computer|macbook|tablet|ipad|monitor|television|\btv\b|car\b|ordinateur", base, re.I)
            and not re.search(r"no logo|unbranded|sans logo", base, re.I)):
        base += ". Every device and object is unbranded, with no visible logos or brand names"
    return f"{base}. {ident}{look} {preset(project).image}".replace("  ", " ")
