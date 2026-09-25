"""`ugc`: rich command line for UGC Studio."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
import warnings
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, Prompt
from rich.table import Table

from ugc_studio import config

app = typer.Typer(add_completion=True, no_args_is_help=True, rich_markup_mode="rich",
                  help="[bold]UGC Studio[/]: local AI video production. UGC, influencer, faceless viral, promo / TV.")
persona_app = typer.Typer(no_args_is_help=True, help="Reusable AI personas (face + voice) for influencer/UGC videos.")
models_app = typer.Typer(no_args_is_help=True, help="Model weights.")
app.add_typer(persona_app, name="persona")
app.add_typer(models_app, name="models")
console = Console()

MODES = {"ugc": "creator testimonial, on camera, lip-synced",
         "influencer": "persistent AI persona, on camera, reusable",
         "faceless": "viral narrated video, fast cuts, big captions",
         "promo": "product commercial from a website (TV / social)"}
ProjectArg = Annotated[Path, typer.Argument(help="Project folder (contains project.yaml)")]


@app.callback()
def _setup(verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logs")] = False) -> None:
    warnings.filterwarnings("ignore")
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(message)s",
                        handlers=[RichHandler(console=console, show_path=False, markup=False, show_time=False)])
    for noisy in ("httpx", "urllib3", "huggingface_hub", "filelock", "PIL", "transformers", "diffusers", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _fail(msg: str) -> None:
    console.print(Panel(msg, title="[red]error", border_style="red"))
    raise typer.Exit(1)


def _studio(project: Path, **kw):
    """Load a project with readable errors instead of tracebacks."""
    from pydantic import ValidationError

    from ugc_studio.engine import Studio

    try:
        return Studio(project, **kw)
    except ValidationError as e:
        lines = [f"[bold]{'.'.join(str(x) for x in err['loc'])}[/]: {err['msg']}" for err in e.errors()]
        _fail(f"{Path(project) / 'project.yaml'} is invalid:\n" + "\n".join(lines))
    except (FileNotFoundError, ValueError) as e:
        _fail(str(e))


# ====================================================================== system
@app.command(rich_help_panel="System")
def doctor() -> None:
    """Check GPU, power mode, memory, disk, environments and model weights."""
    import psutil
    import torch
    from huggingface_hub import get_token

    t = Table(title="UGC Studio doctor", show_header=False, box=None, padding=(0, 2))
    ok, bad, warn = "[green]OK[/]", "[red]MISSING[/]", "[yellow]WARN[/]"
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        t.add_row("GPU", f"{p.name} · {p.total_memory / 2**30:.1f} GiB · sm_{p.major}{p.minor}  {ok}")
    else:
        t.add_row("GPU", "[red]CUDA not available (driver/library mismatch? reboot)[/]")
    try:
        prof = subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True).stdout.strip()
        t.add_row("Power profile", f"{prof}  " + (ok if prof == "performance" else
                  f"{warn} GPU capped (40 W on this laptop): `powerprofilesctl set performance` renders ~2x faster"))
    except FileNotFoundError:
        pass
    t.add_row("RAM", f"{psutil.virtual_memory().total / 2**30:.0f} GiB")
    t.add_row("Disk free", f"{shutil.disk_usage(config.ROOT).free / 2**30:.0f} GiB")
    t.add_row("HF token", ok if get_token() else f"{warn} set HF_TOKEN in .env (needed for LTX-2.5)")
    missing = config.missing_ltx_files()
    t.add_row("LTX-2.5 video", ok if not missing else f"{bad} {len(missing)} files → `ugc models download`")
    t.add_row("FLUX.2 klein images", ok if (config.FLUX_DIR / "model_index.json").is_file() else bad)
    t.add_row("Voice (Qwen3-TTS env)", ok if config.TTS_PYTHON.is_file() else f"{bad} → `ugc setup`")
    t.add_row("Voice AR+13 (Chatterbox)", ok if config.CHATTERBOX_PYTHON.is_file() else f"{bad} → `ugc setup`")
    t.add_row("Voice dialects (Habibi)", ok if config.HABIBI_PYTHON.is_file() else f"{bad} → `ugc setup`")
    t.add_row("Music (ACE-Step env)", ok if config.ACE_PYTHON.is_file() else f"{bad} → `ugc setup`")
    t.add_row("Motion engine", ok if (config.MOTION_DIR / "node_modules" / "gsap").is_dir() else f"{bad} → `ugc setup`")
    try:
        import playwright  # noqa: F401

        t.add_row("Browser (Playwright)", ok)
    except ImportError:
        t.add_row("Browser (Playwright)", bad)
    console.print(t)


@app.command(rich_help_panel="System")
def setup() -> None:
    """Install everything that is missing: motion assets, voice and music environments, browser."""
    steps = []
    if not (config.MOTION_DIR / "node_modules" / "gsap").is_dir():
        steps.append(("motion assets (npm)", ["npm", "install", "--silent", "gsap", "lucide-static",
                      "@fontsource-variable/bricolage-grotesque", "@fontsource-variable/inter", "@fontsource/cairo",
                      "@fontsource/caveat", "@fontsource-variable/jetbrains-mono", "@fontsource/montserrat"],
                      config.MOTION_DIR))
    if not config.TTS_PYTHON.is_file():
        (config.VENDOR_DIR / "tts").mkdir(parents=True, exist_ok=True)
        steps.append(("voice env", ["uv", "venv", "-q", "--python", "3.12", ".venv"], config.VENDOR_DIR / "tts"))
        steps.append(("voice packages", ["uv", "pip", "install", "--python", ".venv/bin/python", "qwen-tts",
                                         "soundfile"], config.VENDOR_DIR / "tts"))
    if not config.CHATTERBOX_PYTHON.is_file():  # Arabic + 13 more narration languages (MIT)
        (config.VENDOR_DIR / "chatterbox").mkdir(parents=True, exist_ok=True)
        steps.append(("arabic voice env", ["uv", "venv", "-q", "--python", "3.11", ".venv"], config.VENDOR_DIR / "chatterbox"))
        steps.append(("arabic voice packages", ["uv", "pip", "install", "--python", ".venv/bin/python", "chatterbox-tts",
                                                "soundfile", "setuptools<81"], config.VENDOR_DIR / "chatterbox"))
    if not config.HABIBI_PYTHON.is_file():  # Arabic dialects (Apache-2.0 specialized checkpoints)
        (config.VENDOR_DIR / "habibi").mkdir(parents=True, exist_ok=True)
        steps.append(("dialect voice env", ["uv", "venv", "-q", "--python", "3.11", ".venv"], config.VENDOR_DIR / "habibi"))
        steps.append(("dialect voice packages", ["uv", "pip", "install", "--python", ".venv/bin/python", "habibi-tts",
                                                 "soundfile"], config.VENDOR_DIR / "habibi"))
        steps.append(("dialect voice torch", ["uv", "pip", "install", "--python", ".venv/bin/python", "--reinstall",
                                              "torch==2.8.0", "torchaudio==2.8.0", "--index-url",
                                              "https://download.pytorch.org/whl/cu128"], config.VENDOR_DIR / "habibi"))
    if not config.ACE_PYTHON.is_file():
        if not config.ACE_DIR.is_dir():
            steps.append(("music code", ["git", "clone", "--depth", "1",
                                         "https://github.com/ace-step/ACE-Step-1.5.git", str(config.ACE_DIR)],
                          config.VENDOR_DIR))
        steps.append(("music env", ["uv", "sync"], config.ACE_DIR))
    steps.append(("browser", [str(Path(os.sys.executable).parent / "playwright"), "install", "chromium"], config.ROOT))
    for name, cmd, cwd in steps:
        with console.status(f"[cyan]{name}[/]…"):
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        console.print(f"{'[green]✓' if r.returncode == 0 else '[red]✗'}[/] {name}")
        if r.returncode:
            console.print(r.stderr[-1500:])
    console.print("Run [bold]ugc models download[/] for the model weights, then [bold]ugc doctor[/].")


@models_app.command("download")
def models_download(only: Annotated[Optional[str], typer.Option(help="ltx | flux | whisper")] = None) -> None:
    """Download model weights (LTX-2.5 needs HF_TOKEN in .env and the license accepted)."""
    from huggingface_hub import hf_hub_download, snapshot_download

    if only in (None, "flux"):
        console.print("[bold]FLUX.2 klein 4B[/] (~16 GB)")
        snapshot_download(config.FLUX_REPO, local_dir=config.FLUX_DIR, ignore_patterns=["flux-2-klein-4b.safetensors", "*.jpg"])
    if only in (None, "whisper"):
        console.print("[bold]Whisper large-v3-turbo[/] (~1.6 GB)")
        snapshot_download(config.ASR_MODEL, allow_patterns=["*.json", "*.safetensors", "*.txt"])
    if only in (None, "ltx"):
        console.print("[bold]LTX-2.5 distilled[/] (~71 GB)")
        for rel in config.LTX_FILES.values():
            hf_hub_download(config.LTX_REPO, rel, local_dir=config.LTX_DIR)
    console.print("[green]Done.[/] Voice and music models download automatically on first use.")


# ====================================================================== create
@app.command(rich_help_panel="Create")
def new(
    name: Annotated[Optional[str], typer.Argument(help="Project name (folder under outputs/)")] = None,
    mode: Annotated[Optional[str], typer.Option(help="ugc | influencer | faceless | promo")] = None,
    brief: Annotated[Optional[str], typer.Option(help="What the video is about")] = None,
    seconds: Annotated[Optional[float], typer.Option(help="Length: 15, 20, 30, 45, 60, 90, 120…")] = None,
    aspect: Annotated[Optional[str], typer.Option(help="9:16 | 16:9 | 1:1 | 4:5")] = None,
    quality: Annotated[Optional[str], typer.Option(help="draft | standard | high | tv")] = None,
    language: Annotated[Optional[str], typer.Option(help="Spoken language")] = None,
    url: Annotated[Optional[str], typer.Option(help="Promo: product website")] = None,
    persona: Annotated[Optional[str], typer.Option(help="Saved persona name (influencer/ugc)")] = None,
    face: Annotated[Optional[list[Path]], typer.Option(help="Photo(s) of the person to use (repeatable)")] = None,
    product: Annotated[Optional[str], typer.Option(help="Product description")] = None,
    product_image: Annotated[Optional[list[Path]], typer.Option(help="Real product photo(s) (repeatable)")] = None,
    style: Annotated[Optional[str], typer.Option(help="Visual style override: anime | cinematic | realistic…")] = None,
    seed: int = 42,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Don't ask anything (use defaults)")] = False,
) -> None:
    """Create a project: an interactive wizard (or flags) → director → project.yaml ready to review and render."""
    from ugc_studio import director as dr
    from ugc_studio.schema import Brand

    ask = not yes
    if not mode:
        if ask:
            _table_modes()
        mode = Prompt.ask("Mode", choices=list(MODES), default="ugc") if ask else "ugc"
    if mode not in MODES:
        _fail(f"unknown mode {mode!r}: {list(MODES)}")
    if mode == "promo" and not url and ask:
        url = Prompt.ask("Product website URL (Enter to skip)", default="") or None
    if not brief:
        default = f"Promotional video for the product at {url}" if url else None
        brief = Prompt.ask("Brief (what is the video about?)", default=default) if ask else default
        if not brief:
            _fail("a --brief is required")
    if seconds is None:
        seconds = FloatPrompt.ask("Length in seconds", default=30.0 if mode == "promo" else 20.0) if ask else 20.0
    if not aspect:
        aspect = Prompt.ask("Format", choices=["9:16", "16:9", "1:1", "4:5"],
                            default="16:9" if mode == "promo" else "9:16") if ask else ("16:9" if mode == "promo" else "9:16")
    if not quality:
        quality = Prompt.ask("Quality", choices=["draft", "standard", "high", "tv"],
                             default="standard") if ask else "standard"
    if not language:
        language = Prompt.ask("Spoken language", default="English") if ask else "English"
    if mode in ("ugc", "influencer") and not persona and not face and ask:
        from ugc_studio import personas as pers

        known = [p.name for p in pers.list_personas()]
        if known:
            persona = Prompt.ask(f"Persona ({', '.join(known)}; Enter for a new face)", default="") or None
        if not persona:
            path = Prompt.ask("Photo of the person to use (Enter to generate one)", default="")
            face = [Path(path)] if path else None
    if not product and ask and mode != "faceless":
        product = Prompt.ask("Product description (Enter to skip)", default="") or None
    if product and not product_image and ask:
        path = Prompt.ask("Real product photo path (Enter to skip; strongly recommended for labels/logos)", default="")
        product_image = [Path(path)] if path else None
    for f in (face or []) + (product_image or []):
        if not f.expanduser().is_file():
            _fail(f"file not found: {f}")

    folder = config.OUTPUTS_DIR / (name or f"{time.strftime('%Y%m%d-%H%M')}_{mode}")
    folder.mkdir(parents=True, exist_ok=True)
    site_info, brand, facts = None, None, ""
    if url:
        from ugc_studio import site

        with console.status("[cyan]Reading the website (text, brand, screens)…"):
            site_info = site.analyze(url, folder / "site")
        brand = dr.brand_from_site(site_info)
        facts = dr.site_facts(site_info)
        console.print(f"[green]✓[/] site: [bold]{brand.name}[/] · colors {brand.primary} {brand.secondary} · "
                      f"{len(site_info.get('links', []))} pages")
    n, shot_s = dr.shots_for(mode, seconds)
    with console.status("[cyan]Director is writing the script (local LLM)…"):
        d = dr.Director()
        try:
            beats = d.beats(mode, brief, n, shot_s, language, facts)
        finally:
            d.close()
    proj = dr.assemble(mode, beats, seconds=seconds, aspect=aspect, quality=quality, language=language, seed=seed,
                       brand=brand or Brand(), persona=persona, char_images=[str(f.expanduser().resolve()) for f in face or []],
                       product_desc=product or "", product_images=[str(f.expanduser().resolve()) for f in product_image or []],
                       site=site_info, style=style)
    proj.save(folder / "project.yaml")
    _show_project(proj)
    console.print(Panel(f"[bold]{folder / 'project.yaml'}[/]\n\nReview/edit it, then:\n"
                        f"  ugc plan {folder}\n  ugc render {folder}", title="[green]project created", border_style="green"))


@app.command(rich_help_panel="Create")
def site(url: str, out: Annotated[Path, typer.Option(help="Where to save screenshots")] = Path("site_capture")) -> None:
    """Analyze a website: brand colors, fonts, logo, headlines, CTAs, pages, screenshots."""
    from ugc_studio import director as dr
    from ugc_studio import site as site_mod

    with console.status("[cyan]Reading the website…"):
        info = site_mod.analyze(url, out)
    b = dr.brand_from_site(info)
    t = Table(show_header=False, box=None)
    for k, v in [("name", b.name), ("headline", b.tagline), ("colors", f"{b.primary}  {b.secondary}  {b.dark}"),
                 ("fonts", f"{b.font_heading} / {b.font_body}"), ("logo", b.logo or "-"), ("phone", b.phone or "-"),
                 ("sections", " · ".join(info.get("h2", [])[:6])), ("CTAs", " · ".join(info.get("ctas", [])[:6])),
                 ("pages", str(len(info.get("links", []))))]:
        t.add_row(f"[bold]{k}", v)
    console.print(Panel(t, title=info.get("title", url)))


# ====================================================================== produce
@app.command(rich_help_panel="Produce")
def plan(project: ProjectArg) -> None:
    """Show the storyboard and exactly what a render would generate (and how long it should take)."""
    from ugc_studio.engine import Studio

    st = _studio(project)
    _show_project(st.project)
    for e in st.ingest.errors:
        console.print(f"[red]✗ {e}")
    for w in st.ingest.warnings:
        console.print(f"[yellow]⚠ {w}")
    items = st.plan()
    t = Table(title="Render plan", box=None)
    for c in ("stage", "item", "est."):
        t.add_column(c)
    for it in items:
        t.add_row(it.stage, it.what, _fmt(it.seconds))
    t.add_row("", "[bold]total", f"[bold]{_fmt(sum(i.seconds for i in items))}")
    console.print(t)


@app.command(rich_help_panel="Produce")
def render(
    project: ProjectArg,
    only: Annotated[Optional[str], typer.Option(help="Only allow these scenes to (re)render, e.g. s01,s03")] = None,
    deliver: Annotated[str, typer.Option(help="Outputs: web, tv (comma separated)")] = "web",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation")] = False,
    offload: str = "cpu",
    qa: Annotated[bool, typer.Option(help="Run the quality check at the end")] = True,
) -> None:
    """Build the video. Resumable and incremental: only what changed since last time is regenerated."""
    from ugc_studio.engine import Studio

    stage_icon = {"frames": "🖼", "voice": "🎙", "music": "🎵", "shots": "🎬", "fixes": "🩹", "screens": "🌐", "edit": "✂"}

    def progress(stage: str, msg: str) -> None:
        console.print(f"  {stage_icon.get(stage, '•')} [cyan]{stage:<7}[/] {msg}")

    st = _studio(project, progress=progress)
    items = st.plan()
    est = sum(i.seconds for i in items)
    gpu = [i for i in items if i.stage in ("frames", "shots", "fixes", "voice", "music")]
    console.print(f"[bold]{st.project.title}[/] · {st.project.mode} · {len(st.project.scenes)} scenes · "
                  f"{len(gpu)} generation step(s) · est. {_fmt(est)}")
    if gpu and not yes and not Confirm.ask("Start rendering?", default=True):
        raise typer.Exit()
    try:
        res = st.build(only=only.split(",") if only else None, deliveries=tuple(deliver.split(",")), offload=offload)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        _fail(str(e))
    for w in res.warnings:
        console.print(f"[yellow]⚠ {w}")
    for kind, path in res.deliveries.items():
        console.print(f"[green]✓ {kind}:[/] {path}")
    console.print(f"[dim]{res.timeline.total:.2f}s video · built in {_fmt(res.seconds)}")
    if qa and res.deliveries:
        _run_qa(next(iter(res.deliveries.values())), st)


@app.command(rich_help_panel="Produce")
def status(project: ProjectArg) -> None:
    """Scene-by-scene state: cached vs pending, fixes, timing in the final video."""
    from ugc_studio.engine import Studio
    from ugc_studio.timeline import Timeline

    st = _studio(project)
    tl_file = st.dir / "timeline.json"
    tl = Timeline.load(tl_file) if tl_file.is_file() else None
    t = Table(title=f"{st.project.title} [{st.project.mode}]")
    for c in ("scene", "kind", "time", "image", "video", "voice", "fixes", "content"):
        t.add_column(c, overflow="fold")
    mark = lambda k: "[green]✓" if st.state.get(k) else "[yellow]●"  # noqa: E731
    for s in st.project.scenes:
        tm = ""
        if tl:
            try:
                sl = tl.slot(s.id)
                tm = f"{sl.start:5.2f}+{sl.dur:.2f}"
            except StopIteration:
                pass
        img = mark(f"kf:{s.id}:start") if s.kind == "shot" and s.continuity == "cut" and not s.start_image else "·"
        vid = mark(f"clip:{s.id}") if s.kind == "shot" else "·"
        vo = mark(f"voice:{s.id}") if s.voiceover else "·"
        text = s.dialogue or s.voiceover or s.headline or s.prompt
        t.add_row(s.id, s.kind, tm, img, vid, vo, str(len(s.fixes)) if s.fixes else "", (text or "")[:70])
    console.print(t)
    outs = sorted((st.dir / "out").glob("*.mp4"))
    for o in outs:
        console.print(f"[green]output:[/] {o}")


@app.command(rich_help_panel="Produce")
def preview(
    project: ProjectArg,
    at: Annotated[Optional[list[float]], typer.Option(help="Times (s) to grab; default: one per second")] = None,
    open_: Annotated[bool, typer.Option("--open", help="Open the result")] = False,
) -> None:
    """Contact sheet (or stills at --at times) of the latest render, labelled with timestamps."""
    from ugc_studio.qa import contact_sheet

    outs = sorted((Path(project) / "out").glob("*.mp4"))
    if not outs:
        _fail("no render yet: run `ugc render` first")
    video = outs[0]
    if at:
        from ugc_studio.media import ffmpeg

        paths = []
        for t in at:
            p = Path(project) / "render" / f"still_{t:07.2f}.png"
            ffmpeg(["-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", str(p)])
            paths.append(p)
        console.print("\n".join(f"[green]{p}" for p in paths))
        target = paths[0]
    else:
        target = contact_sheet(video, Path(project) / "render" / "contact.png", every_s=1.0)
        console.print(f"[green]{target}")
    if open_:
        subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@app.command(rich_help_panel="Produce")
def fix(
    project: ProjectArg,
    at: Annotated[Optional[float], typer.Option(help="Time (s) in the final video where the problem is")] = None,
    duration: Annotated[float, typer.Option(help="How long the problem lasts (s)")] = 0.1,
    mode: Annotated[str, typer.Option(help="auto | interpolate | freeze | retake | reshoot")] = "auto",
    prompt: Annotated[Optional[str], typer.Option(help="Retake/reshoot: what it should show instead")] = None,
    seed: Annotated[Optional[int], typer.Option(help="Reshoot/retake seed (default: a new one)")] = None,
    scene: Annotated[Optional[str], typer.Option(help="Target a scene id directly (reshoot)")] = None,
    undo: Annotated[Optional[str], typer.Option(help="Remove the last fix of this scene")] = None,
    now: Annotated[bool, typer.Option("--render", help="Rebuild right away")] = False,
) -> None:
    """Repair only what's broken. Everything else stays cached, and seams stay seamless.

    [bold]interpolate[/]: a few bad frames are rebuilt from their neighbours (seconds, no AI).
    [bold]retake[/]: only a ~1 s window of the shot is regenerated.
    [bold]reshoot[/]: the whole shot is regenerated with a new seed/prompt, keeping its keyframes."""
    from ugc_studio import fix as fx_mod
    from ugc_studio.engine import Studio, clip_seconds, locate

    st = _studio(project)
    if undo:
        removed = fx_mod.undo_fix(st.project, undo)
        st.save_project()
        console.print(f"[green]removed[/] {removed}" if removed else f"[yellow]{undo} has no fixes")
        return
    if at is None and not scene:
        _fail("give --at <seconds> (where the problem is) or --scene <id>")
    if at is not None:
        slot, local = locate(st.dir, at)
        target = slot.id
        console.print(f"{at:.2f}s → scene [bold]{slot.id}[/] ({slot.kind}) at {local:.2f}s of its clip")
    else:
        target, local, slot = scene, 0.0, None
    sc = st.project.scene(target)
    if sc.kind != "shot":
        console.print(Panel(f"Scene {target} is a [bold]{sc.kind}[/] (graphics). Edit its text in project.yaml; "
                            "a render then redraws only the graphics layer (no AI generation).", border_style="yellow"))
        return
    if mode == "reshoot":
        if seed is not None:
            sc.seed = seed  # an explicit seed also re-draws the keyframe
        else:
            sc.take += 1  # same keyframes and seams, new video take
        if prompt:
            sc.prompt = prompt
        console.print(f"[green]reshoot[/] {target}: " + (f"seed {seed}" if seed is not None else f"take {sc.take}")
                      + (", new prompt" if prompt else ""))
    else:
        fx = fx_mod.plan_fix(local, duration, mode, clip_seconds(st.dir, target))
        fx.prompt, fx.seed = prompt, seed
        fx_mod.add_fix(st.project, target, fx)
        console.print(f"[green]{fx.kind}[/] {target} {fx.start:.2f}-{fx.end:.2f}s (clip time)")
    st.save_project()
    if now:
        render(Path(project), None, "web", True, "cpu", True)
    else:
        console.print(f"Apply with: [bold]ugc render {project}[/] (only {target} and the final edit are rebuilt)")


@app.command(rich_help_panel="Produce")
def edit(project: ProjectArg) -> None:
    """Open project.yaml in your editor."""
    f = Path(project) / "project.yaml"
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("code" if shutil.which("code") else "nano")
    subprocess.call([editor, str(f)])


@app.command(rich_help_panel="Produce")
def export(
    project: ProjectArg,
    fmt: Annotated[str, typer.Option("--format", help="tv | web | vertical | square | portrait | cover")] = "tv",
    at: Annotated[float, typer.Option(help="cover: time of the frame to use (default: first frame = the hook)")] = 0.0,
) -> None:
    """Extra deliveries from the master: TV (-23 LUFS), web (-14 LUFS), a reframed social cut, or a cover image."""
    from ugc_studio.edit import deliver

    master = Path(project) / "render" / "master.mov"
    if not master.is_file():
        _fail("render the project first")
    if fmt == "cover":
        from ugc_studio.media import ffmpeg

        out = Path(project) / "out" / "cover.jpg"
        ffmpeg(["-ss", f"{at:.3f}", "-i", str(master), "-frames:v", "1", "-q:v", "2", str(out)])
        console.print(f"[green]✓ {out}[/] (upload it as the TikTok/Reels cover)")
        return
    sizes = {"vertical": (1080, 1920), "square": (1080, 1080), "portrait": (1080, 1350)}
    out = Path(project) / "out" / f"export_{fmt}.mp4"
    w, h = sizes.get(fmt, (None, None))
    with console.status(f"[cyan]encoding {fmt}…"):
        deliver(master, out, "tv" if fmt == "tv" else "web", w, h)
    if w:
        console.print("[yellow]Reframed by center crop: for a native layout, set aspect in project.yaml and render.")
    console.print(f"[green]✓ {out}")


@app.command(rich_help_panel="Produce")
def qa(target: Annotated[Path, typer.Argument(help="Project folder or video file")]) -> None:
    """Quality report: frames, audio loudness, speech vs script, black/frozen/flicker, contact sheet."""
    video, st = target, None
    if target.is_dir():
        from ugc_studio.engine import Studio

        st = _studio(target)
        outs = sorted((target / "out").glob("*.mp4"))
        if not outs:
            _fail("no render yet")
        video = outs[0]
    _run_qa(video, st)


# ====================================================================== personas
@persona_app.command("create")
def persona_create(
    name: str,
    description: Annotated[str, typer.Option(help="Age, look, hair, style, signature outfit")],
    image: Annotated[Optional[list[Path]], typer.Option(help="Your photos of this person (repeatable)")] = None,
    voice: Annotated[str, typer.Option(help="How they sound on camera")] = "",
    language: str = "English",
) -> None:
    """Create a persona from photos, or generate a consistent 3-view identity sheet from the description."""
    from ugc_studio import personas

    with console.status("[cyan]creating persona…"):
        p = personas.create(name, description, [str(i) for i in image or []], voice, language)
    console.print(f"[green]✓[/] persona [bold]{p.name}[/] · {len(p.images)} reference image(s) in {p.folder}")


@persona_app.command("list")
def persona_list() -> None:
    """List saved personas."""
    from ugc_studio import personas

    t = Table()
    for c in ("name", "images", "voice", "description"):
        t.add_column(c, overflow="fold")
    for p in personas.list_personas():
        t.add_row(p.name, str(len(p.images)), p.voice_style[:40], p.description[:80])
    console.print(t)


# ====================================================================== discover
@app.command(rich_help_panel="Discover")
def modes() -> None:
    """Video modes."""
    _table_modes()


@app.command(rich_help_panel="Discover")
def styles() -> None:
    """Visual styles."""
    from ugc_studio.styles import STYLES

    t = Table()
    t.add_column("style")
    t.add_column("look")
    for k, v in STYLES.items():
        t.add_row(k, v.video[:110])
    console.print(t)


@app.command(rich_help_panel="Discover")
def transitions() -> None:
    """Transition types (set per scene: transition: {type: whip, seconds: 0.3})."""
    rows = [("cut", "hard cut (UGC jump cuts)"), ("dissolve / fade", "cross-dissolve"), ("fadewhite", "flash to white"),
            ("whip", "whip pan with motion blur"), ("zoom", "punch-in zoom"), ("slide", "push"),
            ("circle", "circular reveal"), ("wipe / brand", "diagonal wipe in brand colors")]
    t = Table()
    t.add_column("type")
    t.add_column("effect")
    for r in rows:
        t.add_row(*r)
    console.print(t)


@app.command(rich_help_panel="Discover")
def icons() -> None:
    """Icon names for feature cards (any Lucide icon also works)."""
    from ugc_studio.director import ICONS

    console.print(", ".join(ICONS))


# ====================================================================== quick tools
@app.command(rich_help_panel="Quick tools")
def image(prompt: str, out: Annotated[Path, typer.Option("--out", "-o")] = Path("image.png"),
          ref: Annotated[Optional[list[Path]], typer.Option(help="Reference image(s)")] = None,
          aspect: str = "9:16", seed: int = 42) -> None:
    """Generate or edit one image with FLUX.2 klein (use --ref to keep a person/product consistent)."""
    from ugc_studio.images import keyframe_size
    from ugc_studio.keyframes import KeyframeGenerator

    w, h = keyframe_size(config.resolution(aspect, "standard"), 1.0)
    g = KeyframeGenerator()
    try:
        g.generate(prompt, w, h, seed, references=[str(r) for r in ref or []], out_path=out)
    finally:
        g.close()
    console.print(f"[green]✓ {out}[/] ({w}x{h})")


# ====================================================================== helpers
def _table_modes() -> None:
    t = Table(title="Modes")
    t.add_column("mode", style="bold")
    t.add_column("what you get")
    for k, v in MODES.items():
        t.add_row(k, v)
    console.print(t)


def _show_project(p) -> None:
    t = Table(title=f"{p.title} · {p.mode} · {p.aspect} · {p.quality}", show_lines=True)
    for c in ("scene", "kind", "sec", "trans", "on screen", "spoken"):
        t.add_column(c, overflow="fold")
    for s in p.scenes:
        vis = s.prompt or s.headline or ", ".join(f.title for f in s.features) or s.url or ""
        t.add_row(s.id, s.kind, f"{s.seconds:g}", s.transition.type, vis[:90], (s.dialogue or s.voiceover or "")[:80])
    console.print(t)


def _fmt(sec: float) -> str:
    return f"{sec / 60:.0f} min" if sec >= 90 else f"{sec:.0f} s"


def _run_qa(video: Path, st=None) -> None:
    from ugc_studio.qa import analyze
    from ugc_studio.voice import names as voice_names

    expected = None
    if st is not None:
        expected = " ".join((s.dialogue or s.voiceover or "") for s in st.project.scenes).strip() or None
    ignore = []
    if st is not None and (st.dir / "timeline.json").is_file():
        from ugc_studio.timeline import Timeline

        tl = Timeline.load(st.dir / "timeline.json")
        ignore = [(s.start, s.start + s.transition_s) for s in tl.slots if s.transition != "cut" and s.transition_s]
        # designed light bursts of 3D reveals are intentional flashes, not flicker
        for s in tl.slots:
            sc = st.project.scene(s.id)
            if sc.kind == "devices" or (sc.kind == "screen" and sc.reveal == "spin"):
                ignore.append((s.start, s.start + 1.6))
    with console.status("[cyan]quality check…"):
        r = analyze(video, expected_speech=expected, run_asr=bool(expected), ignore=ignore,
                    language=st.project.language if st is not None else None,
                     names=voice_names(st.project) if st is not None else None)
    colour = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}[r.verdict]
    t = Table(title=f"QA: {video.name}  [{colour}]{r.verdict}[/]", show_header=False)
    t.add_row("video", f"{r.width}x{r.height} @ {r.fps:.2f} fps · {r.frames} frames · {r.duration_s:.2f}s")
    t.add_row("audio", f"{r.integrated_lufs} LUFS · peak {r.true_peak_dbfs} dBFS · clip {r.clipping_ratio:.4%}")
    if r.speech_similarity is not None:
        t.add_row("speech vs script", f"{r.speech_similarity:.0%}")
    for i in r.issues:
        t.add_row(f"[{'red' if i.level == 'fail' else 'yellow'}]{i.check}", i.detail)
    t.add_row("contact sheet", str(r.contact_sheet))
    console.print(t)


if __name__ == "__main__":
    app()
