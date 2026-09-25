"""Frames stage: identity references, start keyframes, seam frames (shared end/start) and end frames.

Continuity rules for a shot scene:
  cut       start = your start_image, else generated from start_prompt/prompt with identity references
  match     start = the seam frame generated for the previous shot's end (identical frame on both sides of the cut)
  continue  start = the previous shot's actual last frame (taken at render time)
The seam frame between shot A and a following `match` shot B is generated from B's start description, using A's
start frame as a reference so place, light and people carry over.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from ugc_studio.config import Resolution
from ugc_studio.schema import Project, Scene
from ugc_studio.state import State, ref
from ugc_studio.styles import keyframe_prompt, preset

log = logging.getLogger(__name__)
FLUX_STEPS = 4


@dataclass
class ShotFrames:
    start: str | None = None  # None + continuity=continue -> taken from the previous clip at render time
    end: str | None = None


def keyframe_size(res: Resolution, megapixels: float) -> tuple[int, int]:
    """Exactly the video's aspect at ~`megapixels`, sides multiple of 16 (video sides are multiples of 64)."""
    target = (megapixels * 1_000_000 / (res.width * res.height)) ** 0.5
    n = max(1, round(target * 4))
    return res.width * n // 4, res.height * n // 4


class _Gen:
    """Lazy FLUX loader + best-of-N selection. Nothing is loaded when every frame is cached."""

    def __init__(self, candidates: int = 1):
        self.g = None
        self.candidates = candidates
        self.report: dict[str, list] = {}

    def __call__(self, prompt, w, h, seed, refs, out, screens: int | None = None, tries: int = 5, judge_refs=None):
        """Generate `candidates` images (more if they fail the gates), keep the best one.
        Gates: exact number of green phone screens (screen-insert shots), identity to references, prompt match."""
        import numpy as np

        from ugc_studio import judge
        from ugc_studio.composite import count_screens

        if self.g is None:
            from ugc_studio.keyframes import KeyframeGenerator

            self.g = KeyframeGenerator(steps=FLUX_STEPS)
        out = Path(out)
        cands, scores = [], []
        n_wanted = self.candidates
        k = 0
        while k < tries + self.candidates and len(cands) < n_wanted:
            path = out.with_name(f"{out.stem}.cand{k}.png")
            im = self.g.generate(prompt, w, h, seed + 7001 * k, references=refs or None, out_path=path)
            k += 1
            if screens is not None:
                n = count_screens(np.asarray(im.convert("RGB")))
                if n != screens:
                    log.warning("%s: candidate shows %d phone screen(s), need %d", out.name, n, screens)
                    path.unlink(missing_ok=True)
                    continue
            if self.candidates == 1 and not (refs if judge_refs is None else judge_refs):
                cands.append(path)
                scores.append({})
                break
            p = judge.prompt_score(path, prompt)
            # identity is judged against people/products only: a transformation's end frame conditioned on its
            # start frame is *meant* to look different from it
            jr = refs if judge_refs is None else judge_refs
            ident = judge.identity_score(path, jr) if jr else None
            sc = {"prompt": round(p, 2), "identity": None if ident is None else round(ident, 3)}
            sc["pass"] = p >= judge.PROMPT_MIN and (ident is None or ident >= judge.IDENTITY_MIN)
            sc["total"] = round(p + (40 * ident if ident is not None else 0) + (100 if sc["pass"] else 0), 2)
            cands.append(path)
            scores.append(sc)
            if not sc["pass"]:
                log.warning("%s: candidate below quality floor %s", out.name, sc)
                n_wanted = min(n_wanted + 1, self.candidates + 2)  # one more try for each failed candidate
        if not cands:
            raise RuntimeError(f"{out.name}: no candidate passed the screen check after {k} tries")
        best = int(np.argmax([s.get("total", 0) for s in scores]))
        cands[best].replace(out)
        for c in cands:
            c.unlink(missing_ok=True)
        self.report[out.name] = {"chosen": best, "candidates": scores}
        if scores[best] and not scores[best].get("pass", True):
            log.warning("%s: kept best candidate %s but it is below the quality floor", out.name, scores[best])
        from PIL import Image

        return Image.open(out)

    def close(self):
        if self.g is not None:
            self.g.close()


class _DryGen:
    """Records what would be generated (for `ugc plan`) without loading any model."""

    def __init__(self):
        self.would: list[str] = []

    def __call__(self, prompt, w, h, seed, refs, out, screens=None, tries=5, judge_refs=None):
        self.would.append(Path(out).name)

    def close(self):
        pass


def _scene_refs(project: Project, scene: Scene, char_refs: dict[str, list[str]], prod_refs: dict[str, list[str]]):
    refs = [p for c in scene.characters for p in char_refs.get(c, [])[:2]]
    refs += [p for pr in scene.products for p in prod_refs.get(pr, [])[:1]]
    return refs[:4]  # FLUX.2 klein: a few references keep identity; more dilute it


def build(project: Project, state: State, workdir: Path, res: Resolution, dry_run: bool = False):
    """Returns {scene id: ShotFrames}; with dry_run=True returns (frames, [images that would be generated])."""
    workdir.mkdir(parents=True, exist_ok=True)
    mp = 2.0 if project.quality == "tv" else 1.0
    w, h = keyframe_size(res, mp)
    gen = _DryGen() if dry_run else _Gen(project.image_candidates)
    commit = state.commit
    if dry_run:
        state.commit = lambda *a, **k: None  # never record anything during a dry run
    try:
        # ---- identity references
        char_refs: dict[str, list[str]] = {}
        for c in project.characters:
            if c.images:
                char_refs[c.id] = c.images
                continue
            out = workdir / f"ref_{c.id}.png"
            prompt = (f"Photorealistic head-and-shoulders identity portrait of {c.description}. Neutral relaxed "
                      "expression facing the camera, plain light gray seamless background, soft even studio light, "
                      "no props, no text")
            if project.style == "anime":
                prompt = f"Anime character reference portrait of {c.description}, plain background, {preset(project).image}"
            inputs = {"prompt": prompt, "seed": project.seed, "size": [w, h]}
            if not state.fresh(f"ref:{c.id}", inputs):
                gen(prompt, w, h, project.seed, None, out)
                state.commit(f"ref:{c.id}", inputs, [out])
            char_refs[c.id] = [str(out)]
        prod_refs: dict[str, list[str]] = {}
        for p in project.products:
            if p.images:
                prod_refs[p.id] = p.images
                continue
            out = workdir / f"ref_{p.id}.png"
            prompt = (f"Professional product packshot of {p.description}, centered on a plain white background, soft "
                      "studio light, sharp focus, no text")
            inputs = {"prompt": prompt, "seed": project.seed + 1, "size": [w, h]}
            if not state.fresh(f"ref:{p.id}", inputs):
                gen(prompt, w, h, project.seed + 1, None, out)
                state.commit(f"ref:{p.id}", inputs, [out])
            prod_refs[p.id] = [str(out)]

        # ---- per-shot frames
        shots = [s for s in project.scenes if s.kind == "shot"]
        frames: dict[str, ShotFrames] = {s.id: ShotFrames() for s in shots}
        seam_for: dict[str, str] = {}  # scene id -> seam path used as its start
        for i, s in enumerate(project.scenes):
            if s.kind != "shot":
                continue
            fr = frames[s.id]
            refs = _scene_refs(project, s, char_refs, prod_refs)
            seed = s.seed if s.seed is not None else project.seed + 17 * i
            # start
            if s.start_image:
                fr.start = s.start_image
            elif s.continuity == "match" and s.id in seam_for:
                fr.start = seam_for[s.id]
            elif s.continuity == "continue" and i > 0 and project.scenes[i - 1].kind == "shot":
                fr.start = None
            else:
                out = workdir / f"{s.id}_start.png"
                prompt = keyframe_prompt(project, s, s.start_prompt, with_reference=bool(refs))
                inputs = {"prompt": prompt, "refs": [ref(r) for r in refs], "seed": seed, "size": [w, h]}
                if not state.fresh(f"kf:{s.id}:start", inputs):
                    gen(prompt, w, h, seed, refs, out, screens=_screens_needed(prompt))
                    state.commit(f"kf:{s.id}:start", inputs, [out])
                fr.start = str(out)
            # end: explicit image / prompt, or the seam shared with a following `match` shot
            nxt = project.scenes[i + 1] if i + 1 < len(project.scenes) else None
            if s.end_image:
                fr.end = s.end_image
            elif nxt is not None and nxt.kind == "shot" and nxt.continuity == "match" and not nxt.start_image:
                nrefs = _scene_refs(project, nxt, char_refs, prod_refs)
                anchor = [fr.start] if fr.start else []
                all_refs = (anchor + [r for r in refs + nrefs if r not in anchor])[:4]
                out = workdir / f"seam_{s.id}_{nxt.id}.png"
                prompt = keyframe_prompt(project, nxt, nxt.start_prompt or nxt.prompt, with_reference=True)
                inputs = {"prompt": prompt, "refs": [ref(r) for r in all_refs], "seed": seed + 1, "size": [w, h]}
                if not state.fresh(f"kf:{s.id}:end", inputs):
                    gen(prompt, w, h, seed + 1, all_refs, out, screens=_screens_needed(prompt))
                    state.commit(f"kf:{s.id}:end", inputs, [out])
                fr.end = str(out)
                seam_for[nxt.id] = str(out)
            elif s.end_prompt:
                anchor = [fr.start] if fr.start else []
                all_refs = (anchor + refs)[:4]
                out = workdir / f"{s.id}_end.png"
                prompt = keyframe_prompt(project, s, s.end_prompt, with_reference=bool(all_refs))
                inputs = {"prompt": prompt, "refs": [ref(r) for r in all_refs], "seed": seed + 2, "size": [w, h]}
                if not state.fresh(f"kf:{s.id}:end", inputs):
                    gen(prompt, w, h, seed + 2, all_refs, out, screens=_screens_needed(prompt), judge_refs=refs)
                    state.commit(f"kf:{s.id}:end", inputs, [out])
                fr.end = str(out)
        # ---- generated stills for image scenes without a file
        for s in project.scenes:
            if s.kind == "image" and not s.image and s.start_prompt:
                out = workdir / f"{s.id}_image.png"
                refs = _scene_refs(project, s, char_refs, prod_refs)
                prompt = keyframe_prompt(project, s, s.start_prompt, with_reference=bool(refs))
                inputs = {"prompt": prompt, "refs": [ref(r) for r in refs], "seed": project.seed, "size": [w, h]}
                if not state.fresh(f"img:{s.id}", inputs):
                    gen(prompt, w, h, project.seed, refs, out)
                    state.commit(f"img:{s.id}", inputs, [out])
                s.image = str(out)
    finally:
        gen.close()
        state.commit = commit
    return (frames, gen.would) if dry_run else frames


def _screens_needed(prompt: str) -> int | None:
    from ugc_studio.composite import GREEN_PROMPT

    return 1 if GREEN_PROMPT.rstrip(".")[:40] in prompt else None


def copy_frame(src: str, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    return dst
