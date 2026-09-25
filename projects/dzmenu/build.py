"""DZ-MeNU TV spot assembly.

  python build.py timeline   # scene timing from the validated voice-over (vo/manifest.json)
  python build.py screens    # frame-exact scroll recordings of the real site (Playwright)
  python build.py render     # motion-design frames (RGBA) over live action + audio mix -> masters
"""

from __future__ import annotations

import asyncio
import json
import math
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

HERE = Path(__file__).parent
MG, VO, CLIPS, SCREENS, OUT = HERE / "mg", HERE / "vo", HERE / "broll" / "clips", HERE / "mg" / "screens", HERE / "out"
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
FPS, W, H = 25, 1920, 1080
CLIP_SECONDS = 121 / FPS  # LTX clip length

# (scene id, kind, b-roll clip, voice line, min seconds)
SCENES = [
    ("s_paper", "ai", "a_paper2", "vo01", 3.6),
    ("s_terrace", "ai", "b_terrace", "vo02", 3.0),
    ("s_logo", "mg", None, "vo03", 4.2),
    ("s_scan", "ai", "d_scan", "vo04", 3.0),
    ("s_phone", "mg", None, "vo05", 5.0),
    ("s_tri", "mg", None, "vo06", 3.8),
    ("s_owner", "ai", "g_owner", "vo07", 3.2),
    ("s_digit", "mg", None, "vo08", 5.4),
    ("s_service", "mg", None, "vo09", 5.2),
    ("s_features", "mg", None, "vo10", 5.0),
    ("s_family", "ai", "j_family", None, 3.4),
    ("s_end", "mg", None, "vo11", 0.0),
]
CLIP_IN = {"s_scan": 1.6}  # seconds skipped at the head of a b-roll clip (keep its best moment)
LEAD = {"ai": 0.25, "mg": 0.35}
TAIL = 0.25
END_MIN_HOLD = 1.2   # logo/URL stays on screen at least this long after the last word
SPOT_SECONDS = 60.0  # broadcast length
TEMPO = 1.07         # voice-over speed-up (atempo), keeps pitch


def _word_time(words: list[dict], needle: str, key: str = "t0") -> float | None:
    for w in words:
        if needle in w["w"].lower():
            return w[key]
    return None


def timeline() -> dict:
    vo = json.loads((VO / "manifest.json").read_text())
    t, scenes, vo_cues = 0.0, {}, []
    for sid, kind, clip, vid, min_s in SCENES:
        lead = LEAD[kind] if sid != "s_paper" else 0.35
        speech = 0.0
        if vid:
            v = vo[vid]
            speech = (v["speech_end"] - v["speech_start"]) / TEMPO
            vo_cues.append({"id": vid, "at": round(t + lead - v["speech_start"] / TEMPO, 3)})
        dur = max(min_s, lead + speech + (END_MIN_HOLD if sid == "s_end" else TAIL))
        if sid == "s_end":
            if t + dur > SPOT_SECONDS:
                raise SystemExit(f"Spot runs {t + dur:.2f}s > {SPOT_SECONDS}s: shorten the voice-over")
            dur = SPOT_SECONDS - t
        scenes[sid] = {"start": round(t, 3), "dur": round(dur, 3), "kind": kind, "clip": clip, "vo": vid, "lead": lead}
        t += dur
    total = round(t * FPS) / FPS

    # Word-synced beats (seconds relative to scene start).
    def beats(sid: str, vid: str, needles: list[str], key: str = "t0") -> list[float]:
        v, s = vo[vid], scenes[sid]
        out = []
        for n in needles:
            wt = _word_time(v["words"], n, key)
            out.append(round(s["lead"] + (wt - v["speech_start"]) / TEMPO, 3) if wt is not None else None)
        return out

    scenes["s_paper"]["beats"] = [b if b is not None else d for b, d in zip(beats("s_paper", "vo01", ["menus", "prix", "clients"]), [0.35, 1.35, 2.4])]
    scenes["s_tri"]["beats"] = [b if b is not None else d for b, d in zip(beats("s_tri", "vo06", ["français", "arabe", "anglais"]), [0.35, 1.05, 1.85])]
    tm = beats("s_digit", "vo08", ["minutes"], "t1")[0]
    if tm:
        scenes["s_digit"]["twoMin"] = tm
    ob = beats("s_end", "vo11", ["trente"])[0] or beats("s_end", "vo11", ["30"])[0]
    if ob:
        scenes["s_end"]["offerBeat"] = ob
    ph = beats("s_owner", "vo07", ["carte"])[0]
    scenes["s_owner"]["flash"] = ph if ph else 1.6

    seqs = {
        "phone_fr": {"start": scenes["s_phone"]["start"], "frames": round(scenes["s_phone"]["dur"] * FPS) + 2, "dir": "screens/phone_fr"},
        "tri_fr": {"start": scenes["s_tri"]["start"], "frames": round(scenes["s_tri"]["dur"] * FPS) + 2, "dir": "screens/tri_fr"},
        "tri_ar": {"start": scenes["s_tri"]["start"], "frames": round(scenes["s_tri"]["dur"] * FPS) + 2, "dir": "screens/tri_ar"},
        "tri_en": {"start": scenes["s_tri"]["start"], "frames": round(scenes["s_tri"]["dur"] * FPS) + 2, "dir": "screens/tri_en"},
        "laptop": {"start": scenes["s_features"]["start"], "frames": round(scenes["s_features"]["dur"] * FPS) + 2, "dir": "screens/laptop"},
    }
    tl = {"fps": FPS, "total": total, "scenes": scenes, "seqs": seqs, "vo": vo_cues}
    (MG / "timeline.js").write_text("window.TL = " + json.dumps(tl, indent=1) + ";\n")
    (HERE / "timeline.json").write_text(json.dumps(tl, indent=1))
    for sid, s in scenes.items():
        print(f"{sid:11s} {s['start']:6.2f} +{s['dur']:5.2f}  {s['kind']}  {s.get('vo') or ''}")
    print(f"TOTAL {total:.2f}s")
    return tl


# ---------------------------------------------------------------- screen recordings
def _ease(x: float) -> float:  # easeInOutCubic
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def _scroll_plan(n: int, segments: list[tuple[float, float, float]]) -> list[float]:
    """segments: (t0_frac, t1_frac, pixels) eased scroll moves over normalized scene time."""
    ys = []
    for i in range(n):
        x, y = i / max(1, n - 1), 0.0
        for a, b, px in segments:
            y += px * (0 if x <= a else 1 if x >= b else _ease((x - a) / (b - a)))
        ys.append(y)
    return ys


async def _record(ctx, url: str, out: Path, ys: list[float], settle_ms: int = 60) -> None:
    out.mkdir(parents=True, exist_ok=True)
    page = await ctx.new_page()
    await page.goto(url, wait_until="networkidle", timeout=60000)
    # Warm lazy images across the scroll range, then start from the top.
    for y in range(0, int(max(ys)) + 1400, 350):
        await page.evaluate(f"window.scrollTo(0,{y})")
        await page.wait_for_timeout(90)
    await page.evaluate("window.scrollTo(0,0)")
    await page.wait_for_timeout(1200)
    await page.add_style_tag(content="html{scroll-behavior:auto!important} *{caret-color:transparent!important}")
    for i, y in enumerate(ys):
        await page.evaluate(f"window.scrollTo(0,{y:.2f})")
        await page.wait_for_timeout(settle_ms)
        await page.screenshot(path=out / f"{i:04d}.jpg", type="jpeg", quality=93)
    await page.close()


async def _screens() -> None:
    from playwright.async_api import async_playwright

    tl = json.loads((HERE / "timeline.json").read_text())
    seqs = tl["seqs"]
    ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
    async with async_playwright() as p:
        b = await p.chromium.launch()
        # Phone screen in the mockup is 408x892 CSS px (440 - 2*16 bezel) minus a 50 px status bar.
        mob = await b.new_context(viewport={"width": 408, "height": 842}, device_scale_factor=2.5, is_mobile=True,
                                  has_touch=True, user_agent=ua)
        n = seqs["phone_fr"]["frames"]
        await _record(mob, "https://dz-menu.com/fr/menu/baraka-glace", SCREENS / "phone_fr",
                      _scroll_plan(n, [(0.28, 0.62, 900), (0.72, 0.95, 700)]))
        for lang in ("fr", "ar", "en"):
            n = seqs[f"tri_{lang}"]["frames"]
            small = await b.new_context(viewport={"width": 334, "height": 688}, device_scale_factor=2.5, is_mobile=True,
                                        has_touch=True, user_agent=ua)
            await _record(small, f"https://dz-menu.com/{lang}/menu/baraka-glace", SCREENS / f"tri_{lang}",
                          _scroll_plan(n, [(0.35, 0.85, 420)]))
            await small.close()
        desk = await b.new_context(viewport={"width": 1440, "height": 834}, device_scale_factor=1.0)
        n = seqs["laptop"]["frames"]
        await _record(desk, "https://dz-menu.com/fr/landing", SCREENS / "laptop",
                      _scroll_plan(n, [(0.15, 0.55, 760), (0.62, 0.95, 820)]))
        await b.close()


def screens() -> None:
    asyncio.run(_screens())


# ---------------------------------------------------------------- render + composite
def _base_video_filter(tl: dict) -> tuple[list[str], str]:
    """Live-action base track: each AI clip in its slot (retimed if the slot is longer), black elsewhere."""
    inputs, parts, labels = [], [], []
    for sid, s in tl["scenes"].items():
        k = len(labels)
        if s["kind"] == "ai":
            inputs += ["-i", str(CLIPS / f"{s['clip']}.mp4")]
            idx = len(inputs) // 2 - 1
            cin = CLIP_IN.get(sid, 0.0)
            stretch = max(1.0, s["dur"] / (CLIP_SECONDS - cin))
            parts.append(
                f"[{idx}:v]trim=start={cin:.3f},crop={W}:{H}:0:4,setpts={stretch:.5f}*(PTS-STARTPTS),fps={FPS},"
                f"trim=duration={s['dur']:.4f},setpts=PTS-STARTPTS,format=yuv420p[b{k}]"
            )
        else:
            parts.append(f"color=c=black:s={W}x{H}:r={FPS}:d={s['dur']:.4f},format=yuv420p[b{k}]")
        labels.append(f"[b{k}]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0,trim=duration={tl['total']:.4f}[base]")
    return inputs, ";".join(parts)


def _audio_filter(tl: dict, first_input: int, music: Path | None) -> tuple[list[str], str]:
    inputs, parts, vo_labels, amb_labels = [], [], [], []
    i = first_input
    for cue in tl["vo"]:
        inputs += ["-i", str(VO / f"{cue['id']}.wav")]
        ms = max(0, round(cue["at"] * 1000))
        parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,atempo={TEMPO},adelay={ms}|{ms}[vo{i}]")
        vo_labels.append(f"[vo{i}]")
        i += 1
    # Ambient sound from the live-action clips, under everything, only inside their slots.
    for sid, s in tl["scenes"].items():
        if s["kind"] != "ai":
            continue
        inputs += ["-i", str(CLIPS / f"{s['clip']}.mp4")]
        ms = round(s["start"] * 1000)
        cin = CLIP_IN.get(sid, 0.0)
        d = min(s["dur"], CLIP_SECONDS - cin)
        parts.append(
            f"[{i}:a]atrim=start={cin:.3f}:duration={d:.3f},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume=0.35,"
            f"afade=t=in:d=0.08,afade=t=out:st={max(0, d - 0.25):.3f}:d=0.25,adelay={ms}|{ms}[amb{i}]"
        )
        amb_labels.append(f"[amb{i}]")
        i += 1
    total = tl["total"]
    parts.append(f"{''.join(vo_labels)}amix=inputs={len(vo_labels)}:normalize=0,apad,atrim=duration={total:.3f}[vox]")
    parts.append(f"{''.join(amb_labels)}amix=inputs={len(amb_labels)}:normalize=0,apad,atrim=duration={total:.3f}[amb]")
    if music:
        inputs += ["-i", str(music)]
        parts.append(
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={total:.3f},"
            # Clear room for the voice: low cut, tamed low-mids, gentle dip in the speech band.
            f"highpass=f=35,bass=g=-4:f=140,equalizer=f=2500:t=q:w=1.2:g=-3,"
            f"afade=t=out:st={total - 1.2:.3f}:d=1.2,volume=0.55[mus]"
        )
        parts.append("[vox]asplit=2[vox1][key]")
        parts.append("[mus][key]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350:makeup=1[duck]")
        parts.append("[vox1][duck][amb]amix=inputs=3:normalize=0[mix]")
    else:
        parts.append("[vox][amb]amix=inputs=2:normalize=0[mix]")
    return inputs, ";".join(parts)


async def _render_frames(tl: dict, pipe) -> None:
    from playwright.async_api import async_playwright

    n = round(tl["total"] * FPS)
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--allow-file-access-from-files", "--force-color-profile=srgb"])
        page = await b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        await page.goto((MG / "index.html").as_uri())
        await page.evaluate("window.compReady")
        for f in range(n):
            await page.evaluate(f"window.seek({f / FPS:.6f})")
            png = await page.screenshot(type="png", omit_background=True)
            pipe.write(png)
            if f % 125 == 0:
                print(f"  frame {f}/{n}", flush=True)
        await b.close()


def overlay() -> Path:
    """Pass 1: motion-design layer -> ProRes 4444 with alpha (single stdin input, cannot deadlock)."""
    tl = json.loads((HERE / "timeline.json").read_text())
    OUT.mkdir(exist_ok=True)
    ov = OUT / "overlay_rgba.mov"
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS),
           "-c:v", "png", "-i", "-", "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
           "-alpha_bits", "16", "-vendor", "apl0", str(ov)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        asyncio.run(_render_frames(tl, proc.stdin))
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise SystemExit(f"ffmpeg overlay encode failed ({rc})")
    return ov


def render(music: str | None = None, reuse_overlay: bool = False) -> None:
    """Pass 2: live action + overlay + audio mix -> broadcast master and delivery files."""
    tl = json.loads((HERE / "timeline.json").read_text())
    OUT.mkdir(exist_ok=True)
    ov = OUT / "overlay_rgba.mov"
    if not (reuse_overlay and ov.exists()):
        overlay()
    music_path = Path(music) if music else (HERE / "music" / "bed.wav" if (HERE / "music" / "bed.wav").exists() else None)
    base_in, base_f = _base_video_filter(tl)
    overlay_idx = len(base_in) // 2
    aud_in, aud_f = _audio_filter(tl, overlay_idx + 1, music_path)
    master = OUT / "dzmenu_tv_master_1080p25.mov"
    fc = ";".join([
        base_f,
        f"[{overlay_idx}:v]format=yuva444p10le[ov]",
        "[base][ov]overlay=0:0:format=auto,format=yuv422p10le[vout]",
        aud_f,
        "[mix]loudnorm=I=-23:TP=-2:LRA=9,aresample=48000[aout]",   # EBU R128 broadcast level
    ])
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *base_in, "-i", str(ov), *aud_in,
           "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]", "-t", f"{tl['total']:.3f}",
           "-c:v", "prores_ks", "-profile:v", "3", "-c:a", "pcm_s24le", "-r", str(FPS), str(master)]
    subprocess.run(cmd, check=True)
    # Delivery encodes: TV (H.264 high bitrate, -23 LUFS kept) and web/social (-14 LUFS).
    tv = OUT / "dzmenu_tv_1080p25.mp4"
    web = OUT / "dzmenu_web_1080p.mp4"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(master), "-c:v", "libx264",
                    "-preset", "slow", "-b:v", "20M", "-maxrate", "25M", "-bufsize", "40M", "-pix_fmt", "yuv420p",
                    "-profile:v", "high", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-c:a", "aac", "-b:a", "320k", "-movflags", "+faststart", str(tv)], check=True)
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", str(master), "-c:v", "libx264",
                    "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
                    "-color_primaries", "bt709", "-color_trc", "bt709",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.79:level=false:attack=2:release=60", "-ar", "48000", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart",
                    str(web)], check=True)
    print("masters:", master, tv, web)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "timeline":
        timeline()
    elif cmd == "screens":
        screens()
    elif cmd == "overlay":
        overlay()
    elif cmd == "render":
        render(sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "-" else None, reuse_overlay="--reuse" in sys.argv)
