"""Operations on projects, shared by the CLI and the HTTP API (no printing, no prompts: values in, values out).

Every change goes through `edit_project`: load project.yaml, apply, validate, keep a .bak, save. Heavy work (render,
export, QA) is started by the caller (CLI directly, API as a background job).
"""

from __future__ import annotations

import re
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from ugc_studio import config
from ugc_studio.schema import AudioClip, Project, VoicePlacement


class ServiceError(ValueError):
    """A request that can't be done as asked; the message says why and what to do."""


# ------------------------------------------------------------------ projects
def project_file(folder: str | Path) -> Path:
    f = Path(folder) / "project.yaml"
    if not f.is_file():
        raise ServiceError(f"{f} not found")
    return f


def list_projects(root: Path | None = None) -> list[dict]:
    """Every folder with a project.yaml under the outputs folder, newest first."""
    root = root or config.OUTPUTS_DIR
    out = []
    for f in sorted(root.glob("*/project.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            p = Project.load(f)
        except Exception as e:  # noqa: BLE001 - a broken project is listed with its error, not hidden
            out.append({"id": f.parent.name, "path": str(f.parent), "error": str(e)[:300]})
            continue
        video = main_video(f.parent)
        out.append({"id": f.parent.name, "path": str(f.parent), "title": p.title, "mode": p.mode,
                    "aspect": p.aspect, "language": p.language, "scenes": len(p.scenes),
                    "video": str(video) if video else None, "updated": f.stat().st_mtime})
    return out


def main_video(folder: str | Path) -> Path | None:
    """The project's main render (<slug>_web.mp4, else _tv.mp4), never an extra export."""
    out = Path(folder) / "out"
    for pattern in ("*_web.mp4", "*_tv.mp4"):
        found = [f for f in sorted(out.glob(pattern)) if not f.name.startswith("export_")]
        if found:
            return max(found, key=lambda f: f.stat().st_mtime)
    return None


def load(folder: str | Path) -> Project:
    return Project.load(project_file(folder))


def edit_project(folder: str | Path, change: Callable[[Project], None]) -> Project:
    """Apply `change(project)` to project.yaml (validated; the previous version is kept as project.yaml.bak)."""
    from pydantic import ValidationError

    f = project_file(folder)
    raw = Project.load(f)
    change(raw)
    try:
        raw = Project.model_validate(raw.model_dump())
    except ValidationError as e:
        raise ServiceError("invalid change: " + "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())) from e
    f.with_suffix(".yaml.bak").write_text(f.read_text())
    raw.save(f)
    return raw


def replace_project(folder: str | Path, data: dict) -> Project:
    """Write a whole project (e.g. from the editor) after validation."""
    from pydantic import ValidationError

    try:
        p = Project.model_validate(data)
    except ValidationError as e:
        raise ServiceError("invalid project: " + "; ".join(
            f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())) from e
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "project.yaml"
    if f.is_file():
        f.with_suffix(".yaml.bak").write_text(f.read_text())
    p.save(f)
    return p


def import_media(folder: str | Path, src: str | Path, sub: str = "media") -> Path:
    """Copy a user file into the project (so the project stays self-contained); returns the new path."""
    src = Path(src)
    if not src.is_file():
        raise ServiceError(f"{src} not found")
    dst_dir = Path(folder) / sub
    dst_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", src.name)
    dst = dst_dir / name
    if src.resolve() != dst.resolve():
        shutil.copy(src, dst)
    return dst


# ------------------------------------------------------------------ plan / status
def plan(folder: str | Path) -> dict:
    from ugc_studio.engine import Studio

    st = Studio(folder)
    items = st.plan()
    return {"items": [asdict(i) for i in items], "total_seconds": sum(i.seconds for i in items),
            "errors": st.ingest.errors, "warnings": st.ingest.warnings}


def status(folder: str | Path) -> dict:
    from ugc_studio.engine import Studio
    from ugc_studio.timeline import Timeline

    st = Studio(folder)
    tl_file = st.dir / "timeline.json"
    tl = Timeline.load(tl_file) if tl_file.is_file() else None
    rows = []
    for s in st.project.scenes:
        slot = next((x for x in tl.slots if x.id == s.id), None) if tl else None
        rows.append({
            "id": s.id, "kind": s.kind, "start": slot.start if slot else None, "dur": slot.dur if slot else None,
            "keyframe": bool(st.state.get(f"kf:{s.id}:start")) if s.kind == "shot" else None,
            "video": bool(st.state.get(f"clip:{s.id}")) if s.kind == "shot" else None,
            "voice": bool(st.state.get(f"voice:{s.id}")) if s.voiceover else None,
            "fixes": len(s.fixes), "text": s.dialogue or s.voiceover or s.headline or s.prompt})
    outs = [str(o) for o in sorted((st.dir / "out").glob("*"))]
    return {"title": st.project.title, "mode": st.project.mode, "scenes": rows, "outputs": outs,
            "total": tl.total if tl else None}


# ------------------------------------------------------------------ voice-over
def _voice_scene(p: Project, sid: str):
    try:
        s = p.scene(sid)
    except KeyError:
        raise ServiceError(f"no scene {sid!r}. Scenes: {', '.join(x.id for x in p.scenes)}") from None
    if s.dialogue:
        raise ServiceError(f"{sid} is on-camera dialogue (spoken by the video model): changing it needs a new take "
                           f"(fix --scene {sid} --mode reshoot after editing `dialogue`).")
    return s


def voice_lines(folder: str | Path) -> dict:
    """Every narration line with its state: accuracy, sound quality, length, transcript, stale or not."""
    from ugc_studio.engine import Studio
    from ugc_studio.voice import pick_engine, stale_lines

    st = Studio(folder)
    p = st.project
    try:
        engine = "file" if p.voice.file else pick_engine(p)
    except ValueError as e:
        engine = f"error: {e}"
    redo = set(stale_lines(p, st.state))
    lines = []
    for s in p.scenes:
        if not s.voiceover:
            continue
        a = st.state.get(f"voice:{s.id}") or {}
        lines.append({"id": s.id, "text": s.voiceover, "take": s.voice_take, "score": a.get("score"),
                      "quality": a.get("quality") or a.get("mos"), "seconds": round(a["speech_end"] - a["speech_start"], 2)
                      if "speech_end" in a else None, "heard": a.get("transcript"), "stale": s.id in redo,
                      "pinned_at": p.edit.voice[s.id].at if s.id in p.edit.voice else None})
    return {"engine": engine, "voice_id": p.voice.voice_id, "file": p.voice.file, "lines": lines}


def voice_set(folder, sid: str, text: str) -> Project:
    def change(p):
        _voice_scene(p, sid).voiceover = text
    return edit_project(folder, change)


def voice_redo(folder, sids: list[str]) -> Project:
    def change(p):
        for sid in sids:
            s = _voice_scene(p, sid)
            if not s.voiceover:
                raise ServiceError(f"{sid} has no voiceover line")
            s.voice_take += 1
    return edit_project(folder, change)


def voice_engine(folder, engine: str, voice_id: str | None = None, model: str | None = None,
                 dialect: str | None = None) -> Project:
    def change(p):
        p.voice.engine, p.voice.file = engine, None
        if voice_id is not None:
            p.voice.voice_id = voice_id
        if model is not None:
            p.voice.model = model
        if dialect is not None:
            p.voice.dialect = dialect
    return edit_project(folder, change)


def voice_file(folder, audio: str | Path) -> Project:
    dst = import_media(folder, audio, "media")

    def change(p):
        p.voice.file = str(dst.resolve())
    return edit_project(folder, change)


# ------------------------------------------------------------------ timeline (manual edit)
def current_voice(st) -> dict:
    """Voice lines already generated (from the cache), as timeline.VoiceLine: no model is run."""
    from ugc_studio.timeline import VoiceLine

    out = {}
    for s in st.project.scenes:
        a = st.state.get(f"voice:{s.id}")
        if s.voiceover and a and "speech_end" in a:
            out[s.id] = VoiceLine(file=str(st.state.path_of(f"voice:{s.id}")), speech_start=a["speech_start"],
                                  speech_end=a["speech_end"], words=a.get("words", []))
    return out


def timeline_view(folder: str | Path) -> dict:
    """Tracks and clips of the edit as it would be built now (narration lines not generated yet are left out)."""
    from ugc_studio import timeline
    from ugc_studio.engine import Studio

    st = Studio(folder)
    vo = current_voice(st)
    try:
        tl = timeline.build(st.project, vo)
    except ValueError as e:
        raise ServiceError(str(e)) from e
    view = timeline.tracks(st.project, tl, vo)
    view["warnings"] = [f"{s.id}: {w}" for s in tl.slots for w in s.warnings]
    view["missing_voice"] = [s.id for s in st.project.scenes if s.voiceover and s.id not in vo]
    return view


def move_voice(folder, sid: str, at: float | None, gain_db: float | None = None) -> Project:
    """Pin a narration line at `at` seconds (None = back to automatic placement)."""
    def change(p):
        s = _voice_scene(p, sid)
        if not s.voiceover:
            raise ServiceError(f"{sid} has no voice-over line")
        if at is None:
            p.edit.voice.pop(sid, None)
        else:
            old = p.edit.voice.get(sid)
            p.edit.voice[sid] = VoicePlacement(at=at, gain_db=gain_db if gain_db is not None else (old.gain_db if old else 0.0))
    f = project_file(folder)
    before = f.read_text()
    p = edit_project(folder, change)
    try:
        timeline_view(folder)  # the edit must give a valid timeline (e.g. not past the end of the video)
    except ServiceError:
        f.write_text(before)   # refused: project.yaml is left exactly as it was
        raise
    return p


def add_audio(folder, file: str | Path, at: float = 0.0, clip_id: str | None = None, **opts) -> AudioClip:
    dst = import_media(folder, file, "media")
    p0 = load(folder)
    base = clip_id or re.sub(r"[^A-Za-z0-9_-]+", "_", Path(file).stem)[:30] or "audio"
    taken = {a.id for a in p0.edit.audio}
    cid, k = base, 2
    while cid in taken:
        cid, k = f"{base}_{k}", k + 1
    clip = AudioClip(id=cid, file=str(dst.resolve()), at=at, **{k: v for k, v in opts.items() if v is not None})

    def change(p):
        p.edit.audio.append(clip)
    edit_project(folder, change)
    return clip


def update_audio(folder, clip_id: str, **fields) -> Project:
    """Set the given fields (None resets an optional one, e.g. duration = whole file)."""
    def change(p):
        for a in p.edit.audio:
            if a.id == clip_id:
                for k, v in fields.items():
                    setattr(a, k, v)
                return
        raise ServiceError(f"no audio clip {clip_id!r}")
    return edit_project(folder, change)


def remove_audio(folder, clip_id: str) -> Project:
    def change(p):
        n = len(p.edit.audio)
        p.edit.audio = [a for a in p.edit.audio if a.id != clip_id]
        if len(p.edit.audio) == n:
            raise ServiceError(f"no audio clip {clip_id!r}")
    return edit_project(folder, change)


def set_music(folder, **fields) -> Project:
    def change(p):
        for k, v in fields.items():
            if v is not None:
                setattr(p.edit.music, k, v)
    return edit_project(folder, change)


# ------------------------------------------------------------------ surgical fixes
def add_fix(folder, at: float | None = None, duration: float = 0.1, mode: str = "auto", prompt: str | None = None,
            seed: int | None = None, scene: str | None = None) -> dict:
    """Record a fix for the problem at `at` seconds (or a reshoot of `scene`). Returns what was decided."""
    from ugc_studio import fix as fx_mod
    from ugc_studio.engine import Studio, clip_seconds, locate

    st = Studio(folder)
    if at is None and not scene:
        raise ServiceError("give the time of the problem (at) or a scene id")
    if at is not None:
        try:
            slot, local = locate(st.dir, at)
        except FileNotFoundError as e:
            raise ServiceError(str(e)) from e
        target = slot.id
    else:
        target, local = scene, 0.0
    try:
        sc = st.project.scene(target)
    except KeyError:
        raise ServiceError(f"no scene {target!r}") from None
    if sc.kind != "shot":
        return {"scene": target, "kind": sc.kind, "action": "none",
                "message": f"{target} is a {sc.kind} (graphics): edit its text; a render redraws only the graphics."}
    if mode == "reshoot":
        if seed is not None:
            sc.seed = seed  # an explicit seed also re-draws the keyframe
        else:
            sc.take += 1
        if prompt:
            sc.prompt = prompt
        result = {"scene": target, "action": "reshoot", "take": sc.take, "seed": seed, "local": local}
    else:
        try:
            fx = fx_mod.plan_fix(local, duration, mode, clip_seconds(st.dir, target))
        except ValueError as e:
            raise ServiceError(str(e)) from e
        fx.prompt, fx.seed = prompt, seed
        fx_mod.add_fix(st.project, target, fx)
        result = {"scene": target, "action": fx.kind, "start": fx.start, "end": fx.end, "local": local}
    st.save_project()
    return result


def undo_fix(folder, scene: str) -> dict:
    from ugc_studio import fix as fx_mod
    from ugc_studio.engine import Studio

    st = Studio(folder)
    try:
        sc = st.project.scene(scene)
    except KeyError:
        raise ServiceError(f"no scene {scene!r}") from None
    if sc.fixes:
        removed = fx_mod.undo_fix(st.project, scene)
        st.save_project()
        return {"scene": scene, "removed": removed.model_dump(), "kind": "fix"}
    if sc.take > 0:  # a reshoot (new take): go back to the previous take, which is still cached
        sc.take -= 1
        st.save_project()
        return {"scene": scene, "removed": {"kind": "reshoot", "take": sc.take + 1}, "kind": "reshoot"}
    return {"scene": scene, "removed": None, "kind": None}


# ------------------------------------------------------------------ mix-only rebuild
def rebuild_mix(folder, progress=None):
    """Narration + mix only. Refuses if the project needs new keyframes or shots (then a full render is needed)."""
    from ugc_studio.engine import Studio

    st = Studio(folder, progress=progress)
    video = [i for i in st.plan() if i.stage in ("frames", "shots", "fixes")]
    if video:
        raise ServiceError("This change also needs new video (" + ", ".join(i.what for i in video) + "). "
                           "Run a full render instead.")
    return st.build(only=["-voice-only-"])  # any shot that would render raises instead of rendering


# ------------------------------------------------------------------ create
MODES = {"ugc": "creator testimonial, on camera, lip-synced",
         "influencer": "persistent AI persona, on camera, reusable",
         "faceless": "viral narrated video, fast cuts, big captions",
         "promo": "product commercial from a website (TV / social)"}


def slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_")[:60]
    if not s:
        raise ServiceError("project name is empty")
    return s


def create_project(name: str, mode: str, brief: str, seconds: float = 20.0, aspect: str = "9:16",
                   quality: str = "standard", language: str = "English", url: str | None = None,
                   persona: str | None = None, faces: list[str] | None = None, product: str | None = None,
                   product_images: list[str] | None = None, style: str | None = None, seed: int = 42,
                   progress: Callable[[str, str], None] | None = None) -> dict:
    """Brief -> (website analysis) -> director LLM -> validated project.yaml in outputs/<name>/."""
    from ugc_studio import director as dr
    from ugc_studio.schema import Brand

    say = progress or (lambda stage, msg: None)
    if mode not in MODES:
        raise ServiceError(f"unknown mode {mode!r}: {', '.join(MODES)}")
    if not brief or not brief.strip():
        raise ServiceError("a brief is required (what the video is about)")
    for f in (faces or []) + (product_images or []):
        if not Path(f).expanduser().is_file():
            raise ServiceError(f"file not found: {f}")
    folder = config.OUTPUTS_DIR / slug(name)
    if (folder / "project.yaml").is_file():
        raise ServiceError(f"a project named {folder.name!r} already exists")
    folder.mkdir(parents=True, exist_ok=True)
    faces = [str(import_media(folder, f, "media").resolve()) for f in faces or []]
    product_images = [str(import_media(folder, f, "media").resolve()) for f in product_images or []]
    site_info, brand, facts = None, None, ""
    if url:
        from ugc_studio import site

        say("site", f"reading {url}")
        site_info = site.analyze(url, folder / "site")
        brand = dr.brand_from_site(site_info)
        facts = dr.site_facts(site_info)
        say("site", f"brand {brand.name} · colors {brand.primary} {brand.secondary}")
    n, shot_s = dr.shots_for(mode, seconds)
    say("director", "writing the script (local LLM)")
    d = dr.Director()
    try:
        beats = d.beats(mode, brief, n, shot_s, language, facts)
    finally:
        d.close()
    proj = dr.assemble(mode, beats, seconds=seconds, aspect=aspect, quality=quality, language=language, seed=seed,
                       brand=brand or Brand(), persona=persona, char_images=faces, product_desc=product or "",
                       product_images=product_images, site=site_info, style=style)
    proj.save(folder / "project.yaml")
    say("director", f"{len(proj.scenes)} scenes")
    return {"id": folder.name, "path": str(folder), "title": proj.title, "scenes": len(proj.scenes)}


# ------------------------------------------------------------------ deliveries and checks
def qa(folder: str | Path | None, video: str | Path):
    """Quality report of a delivered video; with its project, speech is compared to the script and the designed
    transitions / 3D light bursts are not counted as flicker."""
    from ugc_studio.qa import analyze

    video = Path(video)
    if folder is None:
        return analyze(video, run_asr=False)
    from ugc_studio.timeline import Timeline
    from ugc_studio.voice import names as voice_names

    p = load(folder)
    expected = " ".join((s.dialogue or s.voiceover or "") for s in p.scenes).strip() or None
    ignore = []
    tl_file = Path(folder) / "timeline.json"
    if tl_file.is_file():
        tl = Timeline.load(tl_file)
        ignore = [(s.start, s.start + s.transition_s) for s in tl.slots if s.transition != "cut" and s.transition_s]
        for s in tl.slots:
            try:
                sc = p.scene(s.id)
            except KeyError:
                continue
            if sc.kind == "devices" or (sc.kind == "screen" and sc.reveal == "spin"):
                ignore.append((s.start, s.start + 1.6))  # designed light bursts, not flicker
    return analyze(video, expected_speech=expected, run_asr=bool(expected), ignore=ignore, language=p.language,
                   names=voice_names(p))


EXPORT_SIZES = {"vertical": (1080, 1920), "square": (1080, 1080), "portrait": (1080, 1350)}
EXPORT_FORMATS = ("tv", "web", "vertical", "square", "portrait", "cover")


def export(folder: str | Path, fmt: str = "tv", at: float = 0.0) -> Path:
    """Extra delivery from the master: tv (-23 LUFS), web (-14 LUFS), a center-cropped social cut, or a cover."""
    from ugc_studio.edit import deliver
    from ugc_studio.media import ffmpeg

    if fmt not in EXPORT_FORMATS:
        raise ServiceError(f"unknown format {fmt!r}: {', '.join(EXPORT_FORMATS)}")
    master = Path(folder) / "render" / "master.mov"
    if not master.is_file():
        raise ServiceError("render the project first")
    (Path(folder) / "out").mkdir(exist_ok=True)
    if fmt == "cover":
        out = Path(folder) / "out" / "cover.jpg"
        ffmpeg(["-ss", f"{at:.3f}", "-i", str(master), "-frames:v", "1", "-q:v", "2", str(out)])
        return out
    out = Path(folder) / "out" / f"export_{fmt}.mp4"
    w, h = EXPORT_SIZES.get(fmt, (None, None))
    deliver(master, out, "tv" if fmt == "tv" else "web", w, h)
    return out


def contact_sheet(folder: str | Path) -> Path:
    from ugc_studio.qa import contact_sheet as sheet

    video = main_video(folder)
    if not video:
        raise ServiceError("render the project first")
    return sheet(video, Path(folder) / "render" / "contact.png", every_s=1.0)


def scene_thumbnails(folder: str | Path) -> dict[str, str]:
    """One still per scene (middle of its slot) from the latest render; cached until the render changes."""
    from ugc_studio.media import ffmpeg
    from ugc_studio.timeline import Timeline

    folder = Path(folder)
    video = main_video(folder)
    tl_file = folder / "timeline.json"
    if not video or not tl_file.is_file():
        return {}
    tl = Timeline.load(tl_file)
    out_dir = folder / "render" / "thumbs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(int(video.stat().st_mtime))
    thumbs = {}
    for s in tl.slots:
        f = out_dir / f"{s.id}_{stamp}.jpg"
        if not f.is_file():
            for old in out_dir.glob(f"{s.id}_*.jpg"):
                old.unlink()
            ffmpeg(["-ss", f"{s.start + s.dur / 2:.3f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2",
                    "-q:v", "4", str(f)])
        thumbs[s.id] = str(f)
    return thumbs
