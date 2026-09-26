"""Edit timeline: scene start/duration, transition overlaps, voice-over placement, exact-length fitting,
and mapping a time in the final video back to (scene, local time) for surgical fixes."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ugc_studio.config import segment_frames
from ugc_studio.schema import Project, Scene

LEAD = {"shot": 0.25, "clip": 0.25, "image": 0.3, "title": 0.35, "screen": 0.35, "devices": 0.35, "features": 0.35, "endcard": 0.35}
TAIL = 0.3
END_HOLD = 1.2  # endcard stays after the last word
MAX_STRETCH = 1.25  # slow a live-action clip at most this much to cover its voice-over


@dataclass
class VoiceLine:
    file: str
    speech_start: float  # seconds of leading silence in the file
    speech_end: float
    words: list[dict] = field(default_factory=list)


@dataclass
class Slot:
    id: str
    kind: str
    start: float
    dur: float
    transition: str
    transition_s: float
    clip_seconds: float = 0.0  # natural length of the generated clip (shots)
    clip_in: float = 0.0
    stretch: float = 1.0
    vo_at: float | None = None  # absolute time the VO file starts playing
    vo_file: str | None = None
    vo_gain_db: float = 0.0
    vo_manual: bool = False  # pinned by hand (edit.voice): the scene does not stretch for it
    beats: dict[str, float] = field(default_factory=dict)  # word -> local time, for synced animation
    warnings: list[str] = field(default_factory=list)


@dataclass
class Timeline:
    fps: int
    total: float
    slots: list[Slot]

    def to_json(self) -> str:
        return json.dumps({"fps": self.fps, "total": self.total, "slots": [asdict(s) for s in self.slots]}, indent=1)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def load(cls, path: str | Path) -> Timeline:
        d = json.loads(Path(path).read_text())
        return cls(d["fps"], d["total"], [Slot(**s) for s in d["slots"]])

    def slot(self, sid: str) -> Slot:
        return next(s for s in self.slots if s.id == sid)

    def locate(self, t: float) -> tuple[Slot, float]:
        """Scene visible at time t (the incoming one during a transition) and the local time in its raw clip."""
        if not 0 <= t <= self.total:
            raise ValueError(f"time {t:.2f}s is outside the video (0 - {self.total:.2f}s)")
        hit = self.slots[0]
        for s in self.slots:
            if s.start <= t + 1e-6:
                hit = s
        local = hit.clip_in + (t - hit.start) / hit.stretch
        return hit, local


def drops_first_frame(project: Project, i: int) -> bool:
    """A shot whose first frame IS the previous shot's last frame (continue / match seam) drops it in the edit,
    otherwise the seam frame would be shown twice."""
    s = project.scenes[i]
    prev_is_shot = i > 0 and project.scenes[i - 1].kind == "shot"
    return prev_is_shot and not s.start_image and s.continuity in ("continue", "match")


def clip_seconds(scene: Scene, fps: int, drop_first: bool = False) -> float:
    """Usable length of a shot's generated clip (continuation segments drop their overlap frame)."""
    frames = segment_frames(scene.seconds, fps)
    usable = sum(frames) - (len(frames) - 1) - (1 if drop_first else 0)
    return usable / fps


def build(project: Project, voice: dict[str, VoiceLine] | None = None) -> Timeline:
    voice = voice or {}
    fps, tempo = project.fps, project.voice.tempo
    slots: list[Slot] = []
    t = 0.0
    for i, sc in enumerate(project.scenes):
        trans = sc.transition if i else sc.transition.model_copy(update={"type": "cut", "seconds": 0.0})
        ts = 0.0 if trans.type == "cut" else trans.seconds
        start = max(0.0, t - ts)
        slot = Slot(sc.id, sc.kind, round(start, 4), 0.0, trans.type, ts)
        # Voice starts halfway through the incoming transition (J-cut): tighter pacing, like a pro edit.
        lead = LEAD[sc.kind] + ts / 2
        need = 0.0
        vl = voice.get(sc.id)
        pin = project.edit.voice.get(sc.id)
        if vl:
            speech = (vl.speech_end - vl.speech_start) / tempo
            slot.vo_file = vl.file
            if pin:  # pinned by hand: exactly where the editor put it; the scene keeps its own length
                slot.vo_at, slot.vo_gain_db, slot.vo_manual = round(pin.at - vl.speech_start / tempo, 4), pin.gain_db, True
                lead = pin.at - start
            else:
                slot.vo_at = round(start + lead - vl.speech_start / tempo, 4)
                need = lead + speech + (END_HOLD if sc.kind == "endcard" else TAIL)
            for w in vl.words:
                key = w["w"].lower().strip(".,!?;:«»\"'")
                slot.beats.setdefault(key, round(lead + (w["t0"] - vl.speech_start) / tempo, 3))
        elif pin:
            raise ValueError(f"edit.voice.{sc.id}: scene {sc.id} has no voice-over line to place")
        if sc.kind in ("shot", "clip"):
            slot.clip_seconds = (sc.clip_in + sc.seconds if sc.kind == "clip"
                                 else clip_seconds(sc, fps, drops_first_frame(project, i)))
            slot.clip_in = min(sc.clip_in, max(0.0, slot.clip_seconds - 1.0))
            avail = slot.clip_seconds - slot.clip_in
            on_camera = project.mode in ("ugc", "influencer")
            # `seconds` is the intended on-screen length: a narrated shot is never cut below it (a transformation or
            # any action with an arc must play out), and it grows (slowed) only if its voice-over needs more time.
            dur = max(need, avail if on_camera or not vl else min(avail, sc.seconds))
            if dur > avail:
                slot.stretch = dur / avail
                if slot.stretch > MAX_STRETCH:
                    slot.warnings.append(
                        f"voice-over needs {need:.1f}s but the clip has {avail:.1f}s: slowed x{slot.stretch:.2f}. "
                        "Shorten the line or raise `seconds`."
                    )
        else:
            dur = max(sc.seconds, need)
        slot.dur = round(dur, 4)
        slots.append(slot)
        t = start + dur

    total = t
    target = project.target_seconds
    if target:
        flex = [s for s in slots if s.kind == "endcard"] or [slots[-1]]
        delta = target - total
        if delta < -1e-3:
            raise ValueError(
                f"The edit needs {total:.2f}s but target_seconds is {target:.2f}s. Shorten voice-over lines, reduce "
                f"scene seconds, or raise voice.tempo (now {tempo})."
            )
        flex[-1].dur = round(flex[-1].dur + delta, 4)
        total = target
    total = round(math.floor(total * fps + 1e-6) / fps, 4)  # whole frames, never past the last real frame
    _check_voice(project, voice, slots, total, tempo)
    return Timeline(fps, total, slots)


def _check_voice(project: Project, voice: dict, slots: list[Slot], total: float, tempo: float) -> None:
    """Pinned lines must end inside the video; overlapping narration is reported."""
    unknown = set(project.edit.voice) - {s.id for s in project.scenes}
    if unknown:
        raise ValueError(f"edit.voice: unknown scene(s) {', '.join(sorted(unknown))}")
    spans = []
    for s in slots:
        if s.vo_at is None:
            continue
        vl = voice[s.id]
        a, b = s.vo_at + vl.speech_start / tempo, s.vo_at + vl.speech_end / tempo
        if s.vo_manual and b > total + 1e-3:
            raise ValueError(f"{s.id}: the voice line pinned at {a:.2f}s ends at {b:.2f}s, after the end of the video "
                             f"({total:.2f}s). Move it earlier.")
        spans.append((a, b, s))
    spans.sort(key=lambda t: t[0])
    for (a1, b1, s1), (a2, b2, s2) in zip(spans, spans[1:]):
        if a2 < b1 - 0.05:
            s2.warnings.append(f"its voice line ({a2:.2f}s) overlaps {s1.id}'s line (ends {b1:.2f}s)")


def tracks(project: Project, tl: Timeline, voice: dict[str, VoiceLine] | None = None) -> dict:
    """The edit as tracks of clips (video, voice, music, audio): what `ugc timeline show` and the editor display.
    Times are seconds in the final video. `manual` marks what was placed by hand (edit.*)."""
    voice = voice or {}
    tempo = project.voice.tempo
    scenes = {s.id: s for s in project.scenes}
    video = []
    for s in tl.slots:
        sc = scenes[s.id]
        label = sc.headline or sc.caption[0] if (sc.headline or sc.caption) else (sc.prompt or sc.kind)
        video.append({"id": s.id, "kind": s.kind, "start": round(s.start, 3), "dur": round(s.dur, 3),
                      "transition": s.transition, "transition_s": s.transition_s, "label": (label or "")[:80],
                      "stretch": round(s.stretch, 3)})
    vo = []
    for s in tl.slots:
        if s.vo_at is None or s.id not in voice:
            continue
        vl = voice[s.id]
        a = s.vo_at + vl.speech_start / tempo
        vo.append({"id": s.id, "start": round(a, 3), "dur": round((vl.speech_end - vl.speech_start) / tempo, 3),
                   "text": scenes[s.id].voiceover, "manual": s.vo_manual, "gain_db": s.vo_gain_db})
    me = project.edit.music
    music = []
    if project.music.mode != "none":
        music.append({"id": "music", "start": me.start, "dur": round(max(0.0, tl.total - me.start), 3),
                      "offset": me.offset, "gain_db": me.gain_db, "fade_in": me.fade_in, "fade_out": me.fade_out,
                      "manual": me != type(me)()})
    audio = [{"id": a.id, "file": a.file, "start": a.at, "dur": a.duration, "trim_start": a.trim_start,
              "gain_db": a.gain_db, "fade_in": a.fade_in, "fade_out": a.fade_out, "duck": a.duck, "manual": True}
             for a in project.edit.audio]
    return {"fps": tl.fps, "total": tl.total, "tracks": [
        {"id": "video", "kind": "video", "clips": video}, {"id": "voice", "kind": "voice", "clips": vo},
        {"id": "music", "kind": "music", "clips": music}, {"id": "audio", "kind": "audio", "clips": audio}]}
