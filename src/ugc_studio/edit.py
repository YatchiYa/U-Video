"""Final edit: live-action runs with real transitions, graphics overlay, voice, music ducking, loudness, deliveries.

Layers (bottom to top): black canvas -> live-action runs (consecutive shots joined by xfade/acrossfade) ->
motion-graphics RGBA overlay (opaque scenes, captions, wipes). Audio: shot sound (dialogue or ambience),
narration, music (EQ'd and ducked under any speech), EBU R128 loudness.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ugc_studio.media import ffmpeg, probe
from ugc_studio.schema import Project
from ugc_studio.timeline import Timeline, VoiceLine

log = logging.getLogger(__name__)

XFADE = {"dissolve": "fade", "fade": "fade", "fadewhite": "fadewhite", "wipe": "wipeleft", "slide": "slideleft",
         "zoom": "zoomin", "whip": "hblur", "circle": "circleopen", "brand": "fade"}
DELIVERY = {"web": {"lufs": -14.0, "tp": -1.5}, "tv": {"lufs": -23.0, "tp": -2.0}}


@dataclass
class Run:
    slots: list  # consecutive shot slots
    start: float
    end: float


def shot_runs(tl: Timeline) -> list[Run]:
    runs, cur = [], []
    for s in tl.slots:
        if s.kind in ("shot", "clip"):
            cur.append(s)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return [Run(r, r[0].start, r[-1].start + r[-1].dur) for r in runs]


def _run_filter(run: Run, idx0: int, volumes: dict[str, float], fps: int, tag: str) -> tuple[list[str], str, str]:
    """Join a run's conformed clips: xfade/acrossfade for soft transitions, concat for cuts.
    Every label carries the run's `tag`: ffmpeg labels are global, and a duplicate label silently cross-wires runs."""
    chains = []
    chains.append(f"[{idx0}:v]setpts=PTS-STARTPTS,fps={fps}[{tag}v0]")
    chains.append(f"[{idx0}:a]volume={volumes[run.slots[0].id]:.3f},asetpts=PTS-STARTPTS[{tag}a0]")
    acc_v, acc_a = f"[{tag}v0]", f"[{tag}a0]"
    for k, s in enumerate(run.slots[1:], start=1):
        i = idx0 + k
        chains.append(f"[{i}:v]setpts=PTS-STARTPTS,fps={fps}[{tag}v{k}]")
        chains.append(f"[{i}:a]volume={volumes[s.id]:.3f},asetpts=PTS-STARTPTS[{tag}a{k}]")
        off = s.start - run.start
        if s.transition == "cut" or s.transition_s <= 0:
            chains.append(f"{acc_v}[{tag}v{k}]concat=n=2:v=1:a=0,fps={fps}[{tag}cv{k}]")
            chains.append(f"{acc_a}[{tag}a{k}]concat=n=2:v=0:a=1[{tag}ca{k}]")
        else:
            d = s.transition_s
            chains.append(f"{acc_v}[{tag}v{k}]xfade=transition={XFADE[s.transition]}:duration={d:.4f}:offset={off:.4f}[{tag}cv{k}]")
            chains.append(f"{acc_a}[{tag}a{k}]acrossfade=d={d:.4f}:c1=tri:c2=tri[{tag}ca{k}]")
        acc_v, acc_a = f"[{tag}cv{k}]", f"[{tag}ca{k}]"
    return chains, acc_v, acc_a


def render_base(project: Project, tl: Timeline, clips: dict[str, Path], out: Path, width: int, height: int) -> Path:
    """Live action on a black canvas (graphics scenes cover the gaps) + the shots' own sound."""
    fps, total = tl.fps, tl.total
    on_camera = project.mode in ("ugc", "influencer")
    volumes = {s.id: (1.0 if on_camera else s.ambience) for s in project.scenes}
    inputs, chains = [], [f"color=c=black:s={width}x{height}:r={fps}:d={total:.4f},format=yuv420p[canvas]",
                          f"anullsrc=r=48000:cl=stereo,atrim=duration={total:.4f}[silence]"]
    base_v, audio_parts = "[canvas]", ["[silence]"]
    for r_i, run in enumerate(shot_runs(tl)):
        idx0 = len(inputs) // 2
        for s in run.slots:
            inputs += ["-i", str(clips[s.id])]
        ch, rv, ra = _run_filter(run, idx0, volumes, fps, f"r{r_i}")
        chains += ch
        chains.append(f"{rv}setpts=PTS+{run.start:.4f}/TB[pv{r_i}]")
        chains.append(f"{base_v}[pv{r_i}]overlay=eof_action=pass:enable='between(t,{run.start:.4f},{run.end:.4f})'[bv{r_i}]")
        base_v = f"[bv{r_i}]"
        # Place the run's sound with real leading silence. (adelay followed by apad/atrim drops the delay in
        # ffmpeg 7: the second run's audio would land at t=0 and the rest of the track would be silent.)
        fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        if run.start > 1e-4:
            chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={run.start:.5f},{fmt}[lead{r_i}]")
            chains.append(f"{ra}{fmt}[body{r_i}]")
            chains.append(f"[lead{r_i}][body{r_i}]concat=n=2:v=0:a=1,apad,atrim=duration={total:.4f}[pa{r_i}]")
        else:
            chains.append(f"{ra}{fmt},apad,atrim=duration={total:.4f}[pa{r_i}]")
        audio_parts.append(f"[pa{r_i}]")
    chains.append(f"{''.join(audio_parts)}amix=inputs={len(audio_parts)}:normalize=0,atrim=duration={total:.4f}[aout]")
    chains.append(f"{base_v}trim=duration={total:.4f},format=yuv420p[vout]")
    ffmpeg([*inputs, "-filter_complex", ";".join(chains), "-map", "[vout]", "-map", "[aout]", "-r", str(fps),
            "-c:v", "libx264", "-preset", "medium", "-crf", "12", "-g", str(fps), "-c:a", "pcm_s16le", "-ar", "48000",
            "-t", f"{total:.4f}", str(out)])
    return out


# Voice-over polish: a light presence EQ (clearer over music on TV speakers) and a de-esser. No compression: measured
# with a MOS predictor, compressing TTS voices lowered their quality (4.70 -> 4.37-4.47); this chain is neutral (4.7).
BROADCAST_VOICE = ("highpass=f=70,equalizer=f=250:t=q:w=1:g=-1.5,equalizer=f=3000:t=q:w=1.5:g=1.5,deesser=i=0.4")


@dataclass
class Cue:
    """One sound placed on the timeline."""

    file: str
    at: float                   # start in the final video (s); negative = the file's head is cut off
    trim_start: float = 0.0     # skip into the file (s)
    duration: float | None = None
    gain_db: float = 0.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    tempo: float = 1.0


def _stem(cues: list[Cue], total: float, out: Path, post: str = "") -> Path:
    """Place every cue at its time (leading silence by concat: adelay is unreliable with apad/atrim), mix, pad/trim
    to the video length."""
    inputs, parts = [], []
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
    for k, c in enumerate(cues):
        inputs += ["-i", c.file]
        skip = c.trim_start + max(0.0, -c.at) * c.tempo  # output seconds -> file seconds
        chain = [f"[{k}:a]aresample=48000"]
        if skip > 1e-4 or c.duration:
            dur = f":duration={c.duration:.4f}" if c.duration else ""
            chain.append(f"atrim=start={skip:.4f}{dur},asetpts=PTS-STARTPTS")
        if abs(c.tempo - 1) > 1e-3:
            chain.append(f"atempo={c.tempo:.4f}")
        if c.fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={c.fade_in:.3f}")
        if c.fade_out > 0 and c.duration:
            chain.append(f"afade=t=out:st={max(0.0, c.duration - c.fade_out):.4f}:d={c.fade_out:.3f}")
        elif c.fade_out > 0:
            chain.append(f"areverse,afade=t=in:st=0:d={c.fade_out:.3f},areverse")
        if abs(c.gain_db) > 1e-3:
            chain.append(f"volume={c.gain_db:.2f}dB")
        chain.append(fmt)
        line = ",".join(chain)
        if c.at > 1e-4:
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={c.at:.5f},{fmt}[lead{k}]")
            parts.append(f"{line}[body{k}]")
            parts.append(f"[lead{k}][body{k}]concat=n=2:v=0:a=1,apad,atrim=duration={total:.4f}[c{k}]")
        else:
            parts.append(f"{line},apad,atrim=duration={total:.4f}[c{k}]")
    labels = "".join(f"[c{k}]" for k in range(len(cues)))
    tail = f",{post}" if post else ""
    parts.append(f"{labels}amix=inputs={len(cues)}:normalize=0{tail},atrim=duration={total:.4f}[st]")
    ffmpeg([*inputs, "-filter_complex", ";".join(parts), "-map", "[st]", "-c:a", "pcm_s16le", "-ar", "48000", str(out)])
    return out


def render_voice_stem(tl: Timeline, voice: dict[str, VoiceLine], tempo: float, out: Path) -> Path | None:
    cues = [Cue(s.vo_file, s.vo_at, gain_db=s.vo_gain_db, tempo=tempo) for s in tl.slots if s.vo_file]
    return _stem(cues, tl.total, out, BROADCAST_VOICE) if cues else None


def render_audio_stems(project: Project, tl: Timeline, out_dir: Path) -> tuple[Path | None, Path | None]:
    """edit.audio clips -> (sound stem, speech stem). Clips marked `duck` count as speech (they lower the music)."""
    def cues(duck: bool) -> list[Cue]:
        return [Cue(a.file, a.at, a.trim_start, a.duration, a.gain_db, a.fade_in, a.fade_out)
                for a in project.edit.audio if a.duck == duck and a.at < tl.total]

    out = []
    for duck, name in ((False, "sfx.wav"), (True, "speech_extra.wav")):
        c = cues(duck)
        out.append(_stem(c, tl.total, out_dir / name) if c else None)
    return out[0], out[1]


def render_final(project: Project, tl: Timeline, base: Path, overlay: Path | None, vo_stem: Path | None,
                 music: Path | None, out_master: Path, sfx: Path | None = None, speech_extra: Path | None = None) -> Path:
    """Composite + mix. Master keeps full quality; deliveries are encoded from it."""
    total = tl.total
    inputs = ["-i", str(base)]
    chains = []
    v = "[0:v]"
    if overlay:
        inputs += ["-i", str(overlay)]
        chains.append(f"[1:v]format=yuva444p10le[ov];{v}[ov]overlay=0:0:format=auto[v1]")
        v = "[v1]"
    chains.append(f"{v}format=yuv422p10le[vout]")
    speech = ["[0:a]"] if project.mode in ("ugc", "influencer") else []
    beds = [] if speech else ["[0:a]"]
    for stem in (vo_stem, speech_extra):  # narration and extra speech clips duck the music
        if stem:
            inputs += ["-i", str(stem)]
            speech.append(f"[{len(inputs) // 2 - 1}:a]")
    if sfx:  # sound effects / jingles: mixed as they are, never ducked
        inputs += ["-i", str(sfx)]
        beds.append(f"[{len(inputs) // 2 - 1}:a]")
    if music:
        inputs += ["-i", str(music)]
        m = len(inputs) // 2 - 1
        me = project.edit.music
        fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        head = f"atrim=start={me.offset:.4f},asetpts=PTS-STARTPTS," if me.offset > 0 else ""
        fade_in = f"afade=t=in:st=0:d={me.fade_in:.3f}," if me.fade_in > 0 else ""
        vol = project.music.volume * 10 ** (me.gain_db / 20)
        chains.append(f"[{m}:a]aresample=48000,{fmt},{head}highpass=f=35,bass=g=-4:f=140,"
                      f"equalizer=f=2500:t=q:w=1.2:g=-3,{fade_in}volume={vol:.4f}[mraw]")
        if me.start > 1e-4:  # music enters later: real leading silence
            chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={me.start:.5f},{fmt}[mlead]")
            chains.append("[mlead][mraw]concat=n=2:v=0:a=1[mplaced]")
            src = "[mplaced]"
        else:
            src = "[mraw]"
        fade_out = f",afade=t=out:st={max(0, total - me.fade_out):.4f}:d={me.fade_out:.3f}" if me.fade_out > 0 else ""
        chains.append(f"{src}apad,atrim=duration={total:.4f}{fade_out}[mus]")
    if speech:
        chains.append(f"{''.join(speech)}amix=inputs={len(speech)}:normalize=0[sp]")
        if music:
            chains.append("[sp]asplit=2[sp1][key]")
            chains.append("[mus][key]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[duck]")
            mix = ["[sp1]", "[duck]", *beds]
        else:
            mix = ["[sp]", *beds]
    else:
        mix = (["[mus]"] if music else []) + beds
    chains.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0,atrim=duration={total:.4f}[aout]")
    ffmpeg([*inputs, "-filter_complex", ";".join(chains), "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.4f}",
            "-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s24le", "-ar", "48000", "-r", str(tl.fps),
            str(out_master)])
    return out_master


def deliver(master: Path, out: Path, kind: str = "web", width: int | None = None, height: int | None = None) -> Path:
    t = DELIVERY[kind]
    vf = ["format=yuv420p"]
    if width and height:
        vf.insert(0, f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height}")
    video = (["-b:v", "20M", "-maxrate", "25M", "-bufsize", "40M"] if kind == "tv" else ["-crf", "16"])
    ffmpeg(["-i", str(master), "-vf", ",".join(vf), "-c:v", "libx264", "-preset", "slow", "-profile:v", "high",
            *video, "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-af", f"loudnorm=I={t['lufs']}:TP={t['tp']}:LRA=11,aresample=48000,"
                   f"alimiter=limit={10 ** ((t['tp'] - 0.3) / 20):.3f}:level=false:attack=2:release=60",
            "-ar", "48000", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(out)])
    info = probe(out)
    log.info("Delivered %s: %dx%d %.2fs", out.name, info["width"], info["height"], info["seconds"])
    return out
