"""Director: brief (+ website, persona, images) -> complete project.yaml, for every mode.

The LLM writes only the creative beats (hook, lines, shot ideas, features); Python assembles them into a valid
Project with mode-specific pacing, transitions, layouts and durations. This keeps planning robust even with a
small local model, and every plan is schema-validated with retries.
"""

from __future__ import annotations

import gc
import json
import logging
import math
import re
from typing import Any

from ugc_studio.config import DIRECTOR_4BIT, DIRECTOR_LLM
from ugc_studio.schema import Brand, Project
from ugc_studio.styles import STYLES

log = logging.getLogger(__name__)
WPS = 2.5  # spoken words per second
ICONS = ["zap", "sparkles", "clock", "timer", "calendar-check", "chart-no-axes-column", "badge-percent", "qr-code",
         "store", "languages", "message-circle", "smartphone", "shield-check", "heart", "star", "truck", "wallet",
         "credit-card", "users", "globe", "map-pin", "camera", "image", "bell", "lock", "rocket", "leaf", "gift",
         "thumbs-up", "trending-up", "circle-check", "headphones", "utensils-crossed", "coffee", "shopping-bag"]

COMMON = """You are a world-class creative director writing short-form video scripts that perform on TikTok, Instagram
Reels, YouTube Shorts and TV. Every visual description is rendered by an AI video model, so it must be concrete and
filmable: subject, setting, action, camera move, light. Never put text, logos or brand names inside visual
descriptions. Write spoken lines in {language}. Return ONLY one JSON object, no markdown."""

SCHEMAS = {
    "ugc": """Mode: UGC testimonial. One relatable creator talks to camera (selfie style) about the product.
JSON: {{"title": str, "character": str (age, look, hair, outfit - one sentence), "voice_style": str (how they sound),
"shots": [{{"setting": str, "action": str, "camera": str, "dialogue": str ({min_w}-{max_w} words),
"same_setup_as_previous": bool}}]  (exactly {n} shots; shot 1 is a scroll-stopping hook; last shot is a clear call
to action)}}""",
    "influencer": """Mode: influencer video. A charismatic creator with strong personality talks to camera across
varied aesthetic setups (home, street, café, car, gym...), like a top Instagram/TikTok creator.
JSON: {{"title": str, "voice_style": str, "shots": [{{"setting": str, "action": str, "camera": str,
"dialogue": str ({min_w}-{max_w} words), "same_setup_as_previous": bool}}]  (exactly {n} shots; punchy hook first;
end with a call to follow, comment or buy)}}""",
    "faceless": """Mode: faceless viral video. Narrated, no presenter on camera. Scroll-stopping first line, curiosity,
payoff, loop-friendly ending. Fast cuts.
JSON: {{"title": str, "shots": [{{"visual": str (cinematic b-roll, no faces needed), "narration": str
({min_w}-{max_w} words)}}]  (exactly {n} shots)}}""",
    "promo": """Mode: product commercial (TV / social ad). Structure: problem hook -> product reveal -> how it works
(real screens) -> key features -> emotional payoff -> offer and call to action.
JSON: {{"title": str, "tagline": str (max 8 words), "offer": str (max 6 words, from the facts, or ""),
"hook": [{{"visual": str, "narration": str (6-12 words), "caption": str (max 4 words)}}]  (2 items),
"reveal": {{"headline": str (max 5 words), "narration": str (8-14 words)}},
"screens": [{{"page": str (one of the page URLs given, or ""), "eyebrow": str (max 4 words),
"headline": str (max 5 words), "bullets": [str, str, str] (max 5 words each), "narration": str (8-14 words)}}]
(1 or 2 items),
"features": {{"headline": str (max 6 words), "items": [{{"title": str (max 3 words), "subtitle": str (max 6 words),
"icon": one of {icons}}}] (4 to 6 items), "narration": str (8-14 words)}},
"lifestyle": {{"visual": str (happy customers using the product in real life), "caption": str (max 6 words)}},
"end": {{"narration": str (10-16 words, brand name + offer + where to go)}}}}""",
}


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("no JSON object in LLM output")
    return json.loads(text[a:b + 1])


def site_facts(site: dict) -> str:
    keep = {k: site.get(k) for k in ("title", "description", "h1", "h2", "h3", "ctas", "prices", "phones")}
    keep["paragraphs"] = (site.get("paragraphs") or [])[:14]
    keep["pages"] = [u for u in (site.get("links") or []) if not re.search(r"login|legal|privacy|cgu|cgv|terms", u)][:12]
    return json.dumps(keep, ensure_ascii=False)[:6000]


class Director:
    """Local LLM script writer (default Qwen3.5-9B, loaded in 4-bit NF4 so it fits a 12 GB GPU; text-only weights:
    the vision tower of the checkpoint is skipped by the causal-LM class)."""

    def __init__(self, model_id: str = DIRECTOR_LLM, four_bit: bool = DIRECTOR_4BIT):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model_id)
        kw = {}
        from pathlib import Path

        cfg = Path(model_id) / "config.json"
        prequantized = cfg.is_file() and "quantization_config" in cfg.read_text()
        if four_bit and not prequantized:
            from transformers import BitsAndBytesConfig

            kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                           bnb_4bit_compute_dtype=torch.bfloat16,
                                                           bnb_4bit_use_double_quant=True)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda:0", **kw)

    def _chat(self, system: str, user: str, temperature: float) -> str:
        with self.torch.inference_mode():
            msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            try:  # hybrid-reasoning models (Qwen3.5, Gemma 4): answer directly, no hidden thinking
                ids = self.tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt",
                                                   return_dict=True, enable_thinking=False)
            except TypeError:
                ids = self.tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt",
                                                   return_dict=True)
            ids = {k: v.to(self.model.device) for k, v in ids.items()}
            # Qwen3.5 card, non-thinking: temperature 0.7, top_p 0.8, top_k 20 (no generation_config.json: explicit)
            out = self.model.generate(**ids, max_new_tokens=3000, do_sample=True, temperature=temperature, top_p=0.8,
                                      top_k=20, repetition_penalty=1.05)
        text = self.tok.decode(out[0, ids["input_ids"].shape[1]:], skip_special_tokens=True)
        return re.sub(r"^\s*<think>.*?</think>\s*", "", text, flags=re.S)  # an empty think block, if echoed

    def beats(self, mode: str, brief: str, n: int, shot_s: float, language: str, facts: str = "",
              retries: int = 3) -> dict:
        max_w = max(4, int(shot_s * WPS))
        system = COMMON.format(language=language) + "\n\n" + SCHEMAS[mode].format(
            n=n, min_w=max(3, max_w - 4), max_w=max_w, icons=json.dumps(ICONS))
        user = f"Brief: {brief}\nStyle guidance: {STYLES.get(mode, STYLES['promo']).director}\n"
        if facts:
            user += f"Facts from the product website (use real claims only, never invent numbers):\n{facts}\n"
        err = None
        for k in range(retries):
            try:
                data = _extract_json(self._chat(system, user, 0.7 if k == 0 else 0.5))
                _check_beats(mode, data, n)
                return data
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                err = e
                log.warning("director attempt %d: %s", k + 1, e)
        raise RuntimeError(f"Director failed after {retries} attempts: {err}")

    def close(self) -> None:
        del self.model
        gc.collect()
        self.torch.cuda.empty_cache()


def _check_beats(mode: str, d: dict, n: int) -> None:
    if mode in ("ugc", "influencer", "faceless"):
        shots = d["shots"]
        if len(shots) < max(2, n - 1):
            raise ValueError(f"expected {n} shots, got {len(shots)}")
        key = "narration" if mode == "faceless" else "dialogue"
        for s in shots:
            if not str(s.get(key, "")).strip() or not str(s.get("visual") or s.get("action") or "").strip():
                raise ValueError(f"shot missing {key} or visual")
    else:
        for k in ("tagline", "hook", "reveal", "screens", "features", "end"):
            if k not in d:
                raise ValueError(f"missing {k}")
        if len(d["features"]["items"]) < 3:
            raise ValueError("need at least 3 features")


# ---------------------------------------------------------------- assembly (deterministic)
PACING = {"ugc": 5.0, "influencer": 5.0, "faceless": 3.0}
PRODUCT_WORDS = r"product|bottle|box|app|phone|pack|jar|tube|serum|cream|bag|shoe|device|package"


def assemble(mode: str, beats: dict, *, seconds: float, aspect: str, quality: str, language: str, seed: int,
             brand: Brand | None = None, persona: str | None = None, char_images: list[str] | None = None,
             product_desc: str = "", product_images: list[str] | None = None, site: dict | None = None,
             style: str | None = None) -> Project:
    fps = 25 if mode == "promo" else 24
    data: dict[str, Any] = {"title": beats.get("title") or "Untitled", "mode": mode, "aspect": aspect,
                            "quality": quality, "fps": fps, "language": language, "seed": seed,
                            "style": style or ("promo" if mode == "promo" else "ugc")}
    if product_desc or product_images:
        data["products"] = [{"id": "product", "description": product_desc, "images": product_images or []}]
    pid = ["product"] if data.get("products") else []

    if mode in ("ugc", "influencer"):
        char = {"id": "hero", "description": beats.get("character", ""), "images": char_images or []}
        if persona:
            char["persona"] = persona
        data["characters"] = [char]
        data["voice_style"] = beats.get("voice_style", "")
        data["captions"] = {"enabled": mode == "influencer", "style": "tiktok"}
        data["music"] = {"mode": "generate", "volume": 0.18 if mode == "ugc" else 0.25}
        scenes = []
        for i, s in enumerate(beats["shots"]):
            same = bool(s.get("same_setup_as_previous")) and i > 0
            visual = ". ".join(x for x in (s.get("setting"), s.get("action"), s.get("camera")) if x)
            trans = ({"type": "cut", "seconds": 0.0} if same or mode == "ugc" or i == 0
                     else {"type": ["whip", "zoom", "fadewhite"][i % 3], "seconds": 0.3})
            scenes.append({"id": f"s{i + 1:02d}", "kind": "shot", "seconds": PACING[mode], "prompt": visual,
                           "dialogue": s["dialogue"].strip(), "characters": ["hero"],
                           "products": pid if re.search(PRODUCT_WORDS, visual, re.I) else [],
                           # same setup = the action flows on from the real last frame (nothing can pop in)
                           "continuity": "continue" if same else "cut", "transition": trans})
        data["scenes"] = scenes
    elif mode == "faceless":
        data["voice"] = {"enabled": True}
        data["captions"] = {"enabled": True, "style": "tiktok", "position": "middle"}
        data["music"] = {"mode": "generate", "volume": 0.35}
        data["scenes"] = [{"id": f"s{i + 1:02d}", "kind": "shot", "seconds": PACING[mode], "prompt": s["visual"],
                           "voiceover": s["narration"].strip(),
                           "products": pid if re.search(PRODUCT_WORDS, s["visual"], re.I) else [], "ambience": 0.15,
                           "transition": {"type": ["cut", "whip", "cut", "zoom"][i % 4] if i else "cut",
                                          "seconds": 0.25}}
                          for i, s in enumerate(beats["shots"])]
    else:  # promo
        b = brand or Brand()
        data["brand"] = b.model_dump() | {"tagline": beats.get("tagline") or b.tagline,
                                          "offer": beats.get("offer") or b.offer}
        data["target_seconds"] = seconds
        data["logo_bug"] = True
        data["voice"] = {"enabled": True}
        data["music"] = {"mode": "generate", "volume": 0.55}
        pages = (site or {}).get("links") or []
        root_url = (site or {}).get("url") or b.url or None
        sc: list[dict] = []
        for i, h in enumerate(beats["hook"][:2]):
            sc.append({"id": f"hook{i + 1}", "kind": "shot", "seconds": 5.0, "prompt": h["visual"],
                       "voiceover": h["narration"], "caption": [h["caption"]] if h.get("caption") else [],
                       "transition": {"type": "cut", "seconds": 0.0}})
        sc.append({"id": "reveal", "kind": "title", "seconds": 3.5, "headline": beats["reveal"]["headline"],
                   "voiceover": beats["reveal"]["narration"], "transition": {"type": "brand", "seconds": 0.8}})
        for i, s in enumerate(beats["screens"][:2]):
            url = s.get("page") if s.get("page") in pages else root_url
            img = None if url else (product_images or [None])[0]
            if not url and not img:
                continue
            sc.append({"id": f"screen{i + 1}", "kind": "screen", "seconds": 4.5, "url": url, "image": img,
                       "device": "phone" if i == 0 or aspect == "9:16" else "laptop",
                       "eyebrow": s.get("eyebrow"), "headline": s.get("headline"), "bullets": s.get("bullets", [])[:3],
                       "voiceover": s.get("narration"),
                       "transition": {"type": "brand" if i == 0 else "circle", "seconds": 0.8 if i == 0 else 0.6}})
        f = beats["features"]
        sc.append({"id": "features", "kind": "features", "seconds": 4.5, "headline": f["headline"],
                   "features": [{"title": it["title"], "subtitle": it.get("subtitle", ""),
                                 "icon": it.get("icon") if it.get("icon") in ICONS else "sparkles"}
                                for it in f["items"][:6]],
                   "voiceover": f.get("narration"), "transition": {"type": "slide", "seconds": 0.6}})
        ls = beats.get("lifestyle") or {}
        if ls.get("visual"):
            sc.append({"id": "life", "kind": "shot", "seconds": 4.0, "prompt": ls["visual"],
                       "products": pid if re.search(PRODUCT_WORDS, ls["visual"], re.I) else [],
                       "caption": [ls["caption"]] if ls.get("caption") else [],
                       "transition": {"type": "brand", "seconds": 0.8}})
        sc.append({"id": "end", "kind": "endcard", "seconds": 3.0, "voiceover": beats["end"]["narration"],
                   "transition": {"type": "brand", "seconds": 0.8}})
        data["scenes"] = sc
    return Project.model_validate(data)


def shots_for(mode: str, seconds: float) -> tuple[int, float]:
    pace = PACING.get(mode, 5.0)
    n = max(2, math.ceil(seconds / pace - 1e-6))
    return n, seconds / n


def brand_from_site(site: dict) -> Brand:
    pal = site.get("palette", {})
    name = re.split(r"\s[—|\-–:]\s", site.get("title") or "")[0].strip() or "Brand"
    logo = next((f for f in site.get("icon_files", []) if f.endswith(".svg")), None) or \
        next(iter(site.get("icon_files", [])), None)

    def font(css: str, default: str) -> str:
        first = (css or "").split(",")[0].strip().strip('"')
        known = {"Inter": "Inter Variable", "Bricolage Grotesque": "Bricolage Grotesque Variable"}
        return known.get(first, default)

    return Brand(name=name, tagline=(site.get("h1") or [""])[0][:80], url=site.get("url", ""),
                 phone=(site.get("phones") or [""])[0], logo=logo,
                 primary=pal.get("primary", "#6c2bd9"), secondary=pal.get("secondary", "#a163ff"),
                 dark=pal.get("dark", "#161320"), light="#fbf9f6",
                 font_heading=font(site.get("font_heading"), "Bricolage Grotesque Variable"),
                 font_body=font(site.get("font_body"), "Inter Variable"))
