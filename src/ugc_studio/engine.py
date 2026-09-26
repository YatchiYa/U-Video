"""Studio: incremental build of a project folder.

Stages (each asset cached by the hash of its inputs, so only what changed is rebuilt):
  frames -> voice -> music -> shots (+fixes) -> screens -> conform (+color match) -> base -> captions -> overlay
  -> master -> deliveries (web / tv / vertical)
GPU models are loaded lazily and one at a time (FLUX, TTS, ACE-Step, LTX, Whisper) to fit a 12 GB card.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ugc_studio import edit, images, motion, personas, timeline
from ugc_studio.config import CANVAS, RENDER_SECONDS_ESTIMATE, resolution, segment_frames
from ugc_studio.media import color_match_lut, conform, extract_frame, probe, sample_frames
from ugc_studio.schema import Project
from ugc_studio.state import State, ref
from ugc_studio.styles import video_prompt

log = logging.getLogger(__name__)
PROJECT_FILE = "project.yaml"


@dataclass
class PlanItem:
    stage: str
    key: str
    what: str
    seconds: float


@dataclass
class BuildResult:
    master: Path
    deliveries: dict[str, Path]
    timeline: timeline.Timeline
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0


class Studio:
    def __init__(self, project_dir: str | Path, progress: Callable[[str, str], None] | None = None):
        self.dir = Path(project_dir).resolve()
        self.file = self.dir / PROJECT_FILE
        if not self.file.is_file():
            raise FileNotFoundError(f"{self.file} not found. Create a project with `ugc new`.")
        self.project = personas.apply(Project.load(self.file))
        from ugc_studio import assets

        # Every user file is validated + normalized (any image/video/audio format) before anything runs.
        self.ingest = assets.ingest(self.project, self.dir)
        self.state = State(self.dir)
        self.res = resolution(self.project.aspect, "tv" if self.project.quality == "tv" else self.project.quality)
        self.canvas = CANVAS[self.project.aspect]
        self.progress = progress or (lambda stage, msg: log.info("[%s] %s", stage, msg))
        for sub in ("frames", "voice", "music", "clips", "fixed", "conform", "screens", "motion", "render", "out"):
            (self.dir / sub).mkdir(exist_ok=True)

    # ---------------------------------------------------------------- helpers
    def save_project(self) -> None:
        """Write project.yaml back (keeps a .bak of the previous version)."""
        bak = self.file.with_suffix(".yaml.bak")
        bak.write_text(self.file.read_text())
        raw = Project.load(self.file)  # re-load without persona merge so persona data isn't inlined
        for s_new in self.project.scenes:
            try:
                s_old = raw.scene(s_new.id)
            except KeyError:
                continue
            s_old.fixes, s_old.seed, s_old.prompt, s_old.take = s_new.fixes, s_new.seed, s_new.prompt, s_new.take
        raw.save(self.file)

    def _shot_seed(self, i: int) -> int:
        s = self.project.scenes[i]
        base = s.seed if s.seed is not None else self.project.seed + 1000 + 31 * i
        return base + 104729 * s.take

    def _clip_inputs(self, i: int, frames: dict[str, images.ShotFrames]) -> dict:
        s = self.project.scenes[i]
        fr = frames.get(s.id, images.ShotFrames())
        prev = None
        if s.continuity == "continue" and i > 0 and self.project.scenes[i - 1].kind == "shot":
            prev = self.dir / "fixed" / f"{self.project.scenes[i - 1].id}.mp4"
        return {"prompt": video_prompt(self.project, s), "w": self.res.width, "h": self.res.height,
                "segments": segment_frames(s.seconds, self.project.fps), "fps": self.project.fps,
                "seed": self._shot_seed(i), "start": ref(fr.start), "end": ref(fr.end),
                "continue_from": ref(prev) if prev else None, **images.provider_tag(self.project, "video")}

    # ---------------------------------------------------------------- plan (dry run)
    def plan(self) -> list[PlanItem]:
        """Exactly what `build` would regenerate, using the same input hashes (no model is loaded)."""
        p, st = self.project, self.state
        items: list[PlanItem] = []
        frames, would = images.build(p, st, self.dir / "frames", self.res, dry_run=True)
        for name in would:
            items.append(PlanItem("frames", name, f"image {name}", 15 if p.quality != "tv" else 50))
        shot_est = st.typical_seconds(f"shot:{p.quality}", RENDER_SECONDS_ESTIMATE.get(p.quality, 200))
        stale: set[str] = set()
        for i, s in enumerate(p.scenes):
            if s.kind != "shot":
                continue
            fr = frames.get(s.id)
            upstream = s.continuity == "continue" and i > 0 and p.scenes[i - 1].id in stale
            start_new = bool(fr and fr.start and Path(fr.start).name in would)
            end_new = bool(fr and fr.end and Path(fr.end).name in would)
            if upstream or start_new or end_new or not st.fresh(f"clip:{s.id}", self._clip_inputs(i, frames)):
                stale.add(s.id)
                n = len(segment_frames(s.seconds, p.fps))
                why = "continues a re-rendered shot" if upstream else "changed" if st.get(f"clip:{s.id}") else "new"
                extra = " + speech check" if s.dialogue and p.speech_check else ""
                items.append(PlanItem("shots", f"clip:{s.id}", f"{s.id}: {s.seconds:.1f}s video ({why}){extra}",
                                      shot_est * n))
            retakes = [f for f in s.fixes if f.kind == "retake"]
            fixed = st.get(f"fixed:{s.id}")
            if retakes and (s.id in stale or not fixed or fixed.get("hash") is None):
                items.append(PlanItem("fixes", f"fixed:{s.id}", f"{s.id}: {len(retakes)} retake(s)", shot_est * 0.8))
        from ugc_studio.voice import stale_lines

        redo = stale_lines(p, st)
        if redo:
            items.append(PlanItem("voice", "voice", f"{len(redo)} narration line(s): {', '.join(redo)}",
                                  60 + 10 * len(redo)))
        if p.music.mode == "generate" and not st.get("music"):
            items.append(PlanItem("music", "music", "original music (2 candidates)", 150))
        items.append(PlanItem("edit", "edit", "screens, conform, graphics, mix, deliveries",
                              st.typical_seconds("overlay", 120) + 60))
        return items

    # ---------------------------------------------------------------- build
    def build(self, only: list[str] | None = None, deliveries: tuple[str, ...] = ("web",),
              offload: str | None = None) -> BuildResult:
        t0 = time.time()
        p, st, d = self.project, self.state, self.dir
        if self.ingest.errors:
            raise FileNotFoundError("problems with your files:\n  " + "\n  ".join(self.ingest.errors))
        for w in self.ingest.warnings:
            self.progress("frames", f"⚠ {w}")
        warnings: list[str] = []
        self._check_providers()

        # 1. frames
        self.progress("frames", "identity references and keyframes")
        frames = images.build(p, st, d / "frames", self.res)

        # 2. narration
        from ugc_studio import voice as voice_mod

        self.progress("voice", "narration")
        vo = voice_mod.build(p, st, d / "voice")

        # 3. timeline (needs voice lengths) and music (needs the total length)
        tl = timeline.build(p, vo)
        for s in tl.slots:
            warnings += [f"{s.id}: {w}" for w in s.warnings]
        tl.save(d / "timeline.json")
        from ugc_studio import music as music_mod

        self.progress("music", "music bed")
        bed = music_mod.build(p, st, d / "music", tl.total + 1.5 + p.edit.music.offset)

        # 4. shots + fixes (LTX loaded once, only if something needs rendering)
        self._render_shots(frames, only, offload)

        # 5. screen recordings
        seqs = self._screens(tl)

        # 6. conform (+ color match to the first shot)
        clips = self._conform(tl)

        # 7. base + narration stem + captions + overlay
        self.progress("edit", "live-action base layer")
        base_in = {"clips": {k: ref(v) for k, v in clips.items()}, "tl": tl.to_json(),
                   "canvas": [self.canvas.width, self.canvas.height], "code": _code_hash()}
        base = d / "render" / "base.mov"
        if not st.fresh("base", base_in):
            edit.render_base(p, tl, clips, base, self.canvas.width, self.canvas.height)
            st.commit("base", base_in, [base])
        vo_stem = None
        if vo:
            vo_stem = d / "render" / "voice.wav"
            vin = {"lines": {k: ref(v.file) for k, v in vo.items()}, "tl": tl.to_json(), "tempo": p.voice.tempo,
                   "code": _code_hash()}
            if not st.fresh("vostem", vin):
                edit.render_voice_stem(tl, vo, p.voice.tempo, vo_stem)
                st.commit("vostem", vin, [vo_stem])
        # extra sounds placed on the timeline (edit.audio): cheap, deterministic, so rebuilt every time
        sfx = speech_x = None
        if p.edit.audio:
            sfx, speech_x = edit.render_audio_stems(p, tl, d / "render")
        words = self._caption_words(base, vo_stem)
        overlay = None
        if motion.needs_overlay(p):
            self.progress("edit", "motion graphics")
            comp = motion.build_comp(p, tl, d / "motion", self.canvas.width, self.canvas.height, words, seqs)
            files = [s.image for s in p.scenes if s.image] + ([p.brand.logo] if p.brand.logo else [])
            files += [dv.image for s in p.scenes for dv in s.devices if dv.image]
            oin = {"comp": json.dumps(comp, sort_keys=True), "files": [ref(f) for f in files],
                   "seqs": {k: v["hash"] for k, v in seqs.items()}, "engine": _engine_hash()}
            overlay = d / "render" / "overlay.mov"
            if not st.fresh("overlay", oin):
                t1 = time.time()
                motion.render_overlay(comp, d / "motion", overlay)
                st.commit("overlay", oin, [overlay])
                st.record_timing("overlay", time.time() - t1)

        # 8. master + deliveries
        self.progress("edit", "mix and master")
        master = d / "render" / "master.mov"
        min_ = {"base": ref(base), "overlay": ref(overlay), "vo": ref(vo_stem), "music": ref(bed),
                "vol": p.music.volume, "mode": p.mode, "code": _code_hash(),
                **({"sfx": ref(sfx), "speech_x": ref(speech_x)} if p.edit.audio else {}),
                **({"music_edit": p.edit.music.model_dump()} if p.edit.music != type(p.edit.music)() else {})}
        if not st.fresh("master", min_):
            edit.render_final(p, tl, base, overlay, vo_stem, bed, master, sfx, speech_x)
            st.commit("master", min_, [master])
        outs = {}
        slug = "".join(c if c.isalnum() else "_" for c in p.title.lower()).strip("_")[:50] or "video"
        for kind in deliveries:
            out = d / "out" / f"{slug}_{kind}.mp4"
            din = {"master": ref(master), "kind": kind, "code": _code_hash()}
            if not st.fresh(f"deliver:{kind}", din):
                edit.deliver(master, out, "tv" if kind == "tv" else "web")
                st.commit(f"deliver:{kind}", din, [out])
            outs[kind] = out
        return BuildResult(master, outs, tl, warnings, time.time() - t0)

    # ---------------------------------------------------------------- stages
    def _render_shots(self, frames, only, offload) -> None:
        from ugc_studio.fix import apply_fixes

        p, st, d = self.project, self.state, self.dir
        renderer = retaker = None

        def get_renderer():
            nonlocal renderer
            if renderer is None:
                from ugc_studio import providers

                local = providers.choice(p, "video").provider == "local"
                self.progress("shots", "loading LTX-2.5" if local else f"video: {providers.choice(p, 'video').provider}")
                renderer = providers.create(p, "video", **({"offload": offload} if local else {}))
            return renderer

        def get_retaker():
            nonlocal retaker, renderer
            if renderer is not None:
                renderer.close()
                renderer = None
            if retaker is None:
                from ugc_studio.render import RetakeRenderer

                retaker = RetakeRenderer(offload=offload)
            return retaker

        try:
            for i, s in enumerate(p.scenes):
                if s.kind != "shot":
                    continue
                clip = d / "clips" / f"{s.id}.mp4"
                cin = self._clip_inputs(i, frames)
                if not st.fresh(f"clip:{s.id}", cin):
                    if only and s.id not in only:
                        raise RuntimeError(f"scene {s.id} needs rendering but is excluded by --only")
                    from ugc_studio.providers.base import ImageCondition

                    conds = []
                    fr = frames.get(s.id)
                    start = fr.start if fr else None
                    if s.continuity == "continue" and cin["continue_from"]:
                        start = str(extract_frame(Path(cin["continue_from"]["file"]), d / "frames" / f"{s.id}_from_prev.png", "last"))
                    if start:
                        conds.append(ImageCondition(start, 0, 1.0))
                    if fr and fr.end:
                        conds.append(ImageCondition(fr.end, 10_000, 1.0))  # clamped to the last frame
                    self.progress("shots", f"{s.id}: rendering {s.seconds:.1f}s")
                    r = get_renderer()

                    def take(seed: int, out: Path) -> None:
                        t1 = time.time()
                        if len(cin["segments"]) == 1:
                            r.render(cin["prompt"], out, cin["w"], cin["h"], cin["segments"][0], seed, conds, p.fps)
                        else:
                            r.render_long(cin["prompt"], out, cin["w"], cin["h"], cin["segments"], seed, conds, p.fps,
                                          d / "clips" / f".{s.id}_segments")
                        st.record_timing(f"shot:{p.quality}", (time.time() - t1) / len(cin["segments"]))

                    take(cin["seed"], clip)
                    meta = {"seed_used": cin["seed"]}
                    if (s.dialogue and p.speech_check) or p.visual_check:
                        meta.update(self._best_take(s, clip, cin["seed"], take))
                    st.commit(f"clip:{s.id}", cin, [clip], **meta)
                fixed = d / "fixed" / f"{s.id}.mp4"
                fin = {"clip": ref(clip), "fixes": [f.model_dump() for f in s.fixes], "prompt": cin["prompt"]}
                if not st.fresh(f"fixed:{s.id}", fin):
                    if s.fixes:
                        self.progress("fixes", f"{s.id}: applying {len(s.fixes)} fix(es)")
                        apply_fixes(clip, s.fixes, fixed, cin["prompt"], cin["seed"], get_retaker)
                    else:
                        fixed.write_bytes(clip.read_bytes())
                    st.commit(f"fixed:{s.id}", fin, [fixed])
        finally:
            if renderer is not None:
                renderer.close()
            if retaker is not None:
                retaker.close()

    def _check_providers(self) -> None:
        """Fail before any generation when the chosen video provider can't do what the script needs."""
        from ugc_studio import providers

        p = self.project
        if not any(s.kind == "shot" for s in p.scenes):
            return
        c = providers.choice(p, "video")
        cls = providers.load("video", c.provider)
        talking = [s.id for s in p.scenes if s.kind == "shot" and s.dialogue]
        if talking and not getattr(cls, "makes_audio", True):
            raise ValueError(f"Scenes {', '.join(talking)} have on-camera dialogue, but the video provider "
                             f"{c.provider!r} makes no speech. Use video: local (LTX-2.5), veo, kling or seedance, "
                             "or turn the dialogue into a voiceover.")
        if any(f.kind == "retake" for s in p.scenes for f in s.fixes) and not getattr(cls, "supports_retake", True):
            self.progress("fixes", "⚠ retake fixes use the local LTX-2.5 model (the cloud provider can't retake)")

    def _refs_for(self, s) -> list[str]:
        """Identity references of the characters/products in a shot (your photos, persona, or generated refs)."""
        out = []
        for c in self.project.characters:
            if c.id in s.characters:
                out += c.images[:2] or [str(self.dir / "frames" / f"ref_{c.id}.png")]
        for pr in self.project.products:
            if pr.id in s.products:
                out += pr.images[:1] or [str(self.dir / "frames" / f"ref_{pr.id}.png")]
        return [r for r in out if Path(r).is_file()]

    def _best_take(self, s, clip: Path, seed: int, take) -> dict:
        """Quality gate for EVERY generated shot, run on CPU (the GPU keeps the video model):
          visual  - no black/frozen video, the subject stays the same person/animal/product (identity drift)
          words   - Whisper transcript matches the dialogue            (speaking shots)
          sounds  - phoneme-level pronunciation matches the dialogue    (speaking shots; Whisper would "hear"
                    'bancaire' even when the speaker said 'banchaire')
        A failing take is re-shot with a new seed; the best take wins and every score is recorded."""
        from ugc_studio import asr, judge, phonetics
        from ugc_studio.voice import names as voice_names

        p = self.project
        speak = bool(s.dialogue and p.speech_check)
        use_ph = speak and phonetics.supported(p.language)
        refs = self._refs_for(s) if p.visual_check else []

        def score(path: Path) -> dict:
            r = {"ok": True, "rank": 0.0, "notes": []}
            if p.visual_check:
                v = judge.clip_checks(path, refs)
                r["visual"] = v
                if not v["ok"]:
                    r["ok"] = False
                    r["notes"] += v["issues"]
                r["rank"] += (min(v["identity"]) if v["identity"] else 0.5) - 0.5 * len(v["issues"])
            if speak:
                heard = asr.transcribe(str(path), p.language, device="cpu")["text"]
                words = asr.similarity(s.dialogue, heard, p.language, voice_names(p))
                ph = phonetics.check(path, s.dialogue, p.language) if use_ph else {"score": 1.0, "flagged": []}
                r.update(words=words, heard=heard, phon=ph["score"],
                         flagged=[f"{f['word']} /{f['expected']}/ heard /{f['heard']}/" for f in ph["flagged"]])
                if words < p.speech_min:
                    r["ok"] = False
                    r["notes"].append(f"words {words:.0%}")
                if ph["flagged"]:
                    r["ok"] = False
                    r["notes"].append("mispronounced: " + ", ".join(r["flagged"]))
                r["rank"] += words + ph["score"] - 0.25 * len(ph["flagged"])
            return r

        def report(k: int, r: dict) -> None:
            parts = []
            if "words" in r:
                parts.append(f"words {r['words']:.0%}, pronunciation {r['phon']:.0%}")
            if "visual" in r and r["visual"]["identity"]:
                parts.append(f"identity {min(r['visual']['identity']):.2f}")
            status = "OK" if r["ok"] else "✗ " + "; ".join(r["notes"])
            self.progress("shots", f"{s.id}: take {k + 1}: {', '.join(parts) or 'visual'} · {status}")

        best = score(clip)
        best_seed, tries = seed, [round(best["rank"], 3)]
        report(0, best)
        retries = max(p.speech_retries if speak else 0, 1 if p.visual_check else 0)
        for k in range(1, retries + 1):
            if best["ok"]:
                break
            alt_seed = seed + 7919 * k
            alt = clip.with_name(f"{clip.stem}.take{k}.mp4")
            self.progress("shots", f"{s.id}: re-shooting (take {k + 1})")
            take(alt_seed, alt)
            r = score(alt)
            tries.append(round(r["rank"], 3))
            report(k, r)
            if (r["ok"], r["rank"]) > (best["ok"], best["rank"]):
                best, best_seed = r, alt_seed
                alt.replace(clip)
            else:
                alt.unlink(missing_ok=True)
        if not best["ok"]:
            self.progress("shots", f"{s.id}: ⚠ kept the best take, still: {'; '.join(best['notes'])}. "
                                   "Rephrase the line / add a `pronounce` entry, or `ugc fix --mode reshoot`.")
        meta = {"qc_ok": best["ok"], "qc_notes": best["notes"], "speech_tries": tries, "seed_used": best_seed}
        if "words" in best:
            meta.update(speech=round(best["words"], 3), pronunciation=best["phon"], mispronounced=best["flagged"],
                        speech_heard=best["heard"])
        if "visual" in best:
            meta["identity"] = best["visual"]["identity"]
        return meta

    def _with_screen(self, s, tl: timeline.Timeline) -> Path:
        """The shot's clip with the real app composited onto its green phone screen (or the clip as is)."""
        from ugc_studio import composite, site

        fixed = self.dir / "fixed" / f"{s.id}.mp4"
        if not s.screen_insert:
            return fixed
        si = s.screen_insert
        n = probe(fixed)["frames"]
        rec = self.dir / "screens" / f"{s.id}_insert"
        rin = {"url": si.url, "image": ref(si.image), "frames": n, "scroll": si.scroll}
        if not self.state.fresh(f"insertsrc:{s.id}", rin):
            rec.mkdir(parents=True, exist_ok=True)
            if si.url:
                self.progress("screens", f"{s.id}: recording the app for the phone screen")
                site.record(si.url, rec, n if si.scroll else 1, "phone")
            else:
                from PIL import Image

                Image.open(si.image).convert("RGB").save(rec / "0000.jpg", quality=95)
            (rec / "done").write_text("ok")
            self.state.commit(f"insertsrc:{s.id}", rin, [rec / "done"])
        frames = sorted(rec.glob("*.jpg"))
        out = self.dir / "fixed" / f"{s.id}.screen.mp4"
        cin = {"clip": ref(fixed), "src": self.state.get(f"insertsrc:{s.id}")["hash"], "code": _code_hash()}
        if not self.state.fresh(f"insert:{s.id}", cin):
            self.progress("edit", f"{s.id}: putting the real app on the phone screen")
            stats = composite.insert_screen(fixed, frames, out)
            if stats["residual_max"] > 0.0005:  # gate: green must never reach the final video
                raise RuntimeError(f"{s.id}: screen replacement left green pixels ({stats['residual_max']:.4f}); "
                                   "`ugc fix --scene {s.id} --mode reshoot`")
            self.state.commit(f"insert:{s.id}", cin, [out], **stats)
        return out

    def _screens(self, tl: timeline.Timeline) -> dict[str, dict]:
        from ugc_studio import site

        out = {}
        for s in self.project.scenes:
            jobs = []
            if s.kind == "screen" and s.url:
                jobs = [(s.id, s.url, s.device, None)]
            elif s.kind == "devices":
                jobs = [(f"{s.id}__{k}", dv.url, "phone_sm", 420) for k, dv in enumerate(s.devices) if dv.url]
            if not jobs:
                continue
            slot = tl.slot(s.id)
            frames = round((slot.dur + slot.transition_s + 0.5) * tl.fps) + 2
            for key, url, device, distance in jobs:
                sin = {"url": url, "device": device, "frames": frames, "distance": distance}
                folder = self.dir / "screens" / key
                if not self.state.fresh(f"screen:{key}", sin):
                    self.progress("screens", f"{key}: recording {url}")
                    site.record(url, folder, frames, device, distance)
                    (folder / "done").write_text("ok")
                    self.state.commit(f"screen:{key}", sin, [folder / "done"])
                out[key] = {"dir": str(folder), "frames": frames, "hash": self.state.get(f"screen:{key}")["hash"]}
        return out

    def _conform(self, tl: timeline.Timeline) -> dict[str, Path]:
        p, st, d = self.project, self.state, self.dir
        shots = [s for s in p.scenes if s.kind in ("shot", "clip")]
        ref_clip = ((Path(shots[0].video) if shots[0].kind == "clip" else d / "fixed" / f"{shots[0].id}.mp4")
                    if shots else None)
        clips = {}
        # Shots joined by a seam (match / continue) form a chain that shares ONE grade, otherwise two
        # different LUTs would break the identical frame at the seam.
        head_of: dict[str, str] = {}
        for i, s in enumerate(p.scenes):
            if s.kind not in ("shot", "clip"):
                continue
            prev = p.scenes[i - 1] if i else None
            linked = prev is not None and prev.kind == "shot" and timeline.drops_first_frame(p, i)
            head_of[s.id] = head_of[prev.id] if linked else s.id
        for s in shots:
            slot = tl.slot(s.id)
            fixed = Path(s.video) if s.kind == "clip" else self._with_screen(s, tl)
            head = head_of[s.id]
            lut = None
            if p.color_match and ref_clip and head != shots[0].id:
                lut = d / "conform" / f"{head}.cube"
                hs = p.scene(head)
                head_clip = Path(hs.video) if hs.kind == "clip" else d / "fixed" / f"{head}.mp4"
                lin = {"src": ref(head_clip), "ref": ref(ref_clip)}
                if not st.fresh(f"lut:{head}", lin):
                    color_match_lut(sample_frames(head_clip), sample_frames(ref_clip), lut)
                    st.commit(f"lut:{head}", lin, [lut])
            out = d / "conform" / f"{s.id}.mov"
            drop = 1 if timeline.drops_first_frame(p, p.scenes.index(s)) else 0
            cin = {"src": ref(fixed), "lut": ref(lut), "fps": tl.fps, "code": _code_hash(), "canvas": [self.canvas.width, self.canvas.height],
                   "in": slot.clip_in, "dur": slot.dur, "stretch": slot.stretch, "drop": drop}
            if not st.fresh(f"conform:{s.id}", cin):
                conform(fixed, out, fps=tl.fps, width=self.canvas.width, height=self.canvas.height, start=slot.clip_in,
                        duration=slot.dur, stretch=slot.stretch, lut=lut, drop_first=drop)
                st.commit(f"conform:{s.id}", cin, [out])
            clips[s.id] = out
        return clips

    def _caption_words(self, base: Path, vo_stem: Path | None) -> list[dict]:
        if not self.project.captions.enabled:
            return []
        from ugc_studio import asr

        src = vo_stem if vo_stem else base
        scripts = [s.dialogue or s.voiceover or "" for s in self.project.scenes]
        cin = {"src": ref(src), "language": self.project.language, "scripts": scripts, "code": _code_hash()}
        if self.state.fresh("captions", cin):
            return self.state.get("captions")["words"]
        self.progress("edit", "transcribing for captions")
        heard = asr.transcribe(str(src), self.project.language)["words"]
        asr.unload()
        # Show the script's exact words (no ASR typos, no hallucinations) with the real spoken timing.
        tl = timeline.Timeline.load(self.dir / "timeline.json")
        words = []
        for slot in tl.slots:
            sc = self.project.scene(slot.id)
            line = sc.dialogue or sc.voiceover
            if not line:
                continue
            if sc.voiceover and slot.vo_at is not None:
                t0, t1 = slot.vo_at, slot.start + slot.dur + 0.5
            else:
                t0, t1 = slot.start, slot.start + slot.dur
            words += asr.align_to_script(line, heard, t0, t1)
        cap = self.dir / "render" / "captions.json"
        cap.write_text(json.dumps(words, ensure_ascii=False))
        self.state.commit("captions", cin, [cap], words=words)
        return words


def _code_hash() -> str:
    """Fingerprint of the editing code: a fix in the editor must invalidate edits built by the old code."""
    from ugc_studio.state import file_hash

    here = Path(__file__).parent
    return "".join(file_hash(here / f)[:8] for f in ("edit.py", "media.py", "timeline.py", "composite.py"))


def _engine_hash() -> str:
    from ugc_studio.state import file_hash
    from ugc_studio.config import MOTION_DIR

    return "".join(file_hash(MOTION_DIR / f)[:8] for f in ("engine.js", "style.css", "index.html"))


def locate(project_dir: Path, t: float) -> tuple[timeline.Slot, float]:
    tl_file = Path(project_dir) / "timeline.json"
    if not tl_file.is_file():
        raise FileNotFoundError("No timeline yet: build the project once before fixing it.")
    return timeline.Timeline.load(tl_file).locate(t)


def clip_seconds(project_dir: Path, scene_id: str) -> float:
    f = Path(project_dir) / "fixed" / f"{scene_id}.mp4"
    return probe(f)["seconds"] if f.is_file() else 5.0
