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
voice_app = typer.Typer(no_args_is_help=True, help="Change only the voice-over: text, take, voice/engine or your own "
                                                   "recording. Rebuilds narration + mix only, never the video shots.")
app.add_typer(persona_app, name="persona")
timeline_app = typer.Typer(no_args_is_help=True, help="Edit the timeline by hand: move voice lines, add sounds, shape "
                                                        "the music. Rebuilds the mix only, never the video shots.")
app.add_typer(voice_app, name="voice")
app.add_typer(timeline_app, name="timeline")
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
def serve(host: Annotated[str, typer.Option(help="Bind address")] = "127.0.0.1",
          port: Annotated[int, typer.Option(help="Port")] = 8000,
          worker: Annotated[bool, typer.Option(help="Also run the job worker in this process")] = True) -> None:
    """HTTP API for the web app (docs at /docs). Without REDIS_URL, jobs live in memory and the worker runs here."""
    import threading

    import uvicorn

    from ugc_studio import jobs

    if worker:
        threading.Thread(target=jobs.work, daemon=True, name="worker").start()
    console.print(f"[green]UGC Studio API[/] on http://{host}:{port}  ·  docs http://{host}:{port}/docs  ·  "
                  f"jobs: {type(jobs.store()).__name__}" + (" + embedded worker" if worker else ""))
    uvicorn.run("ugc_studio.api:app", host=host, port=port, log_level="warning")


@app.command(rich_help_panel="System")
def worker() -> None:
    """Job worker (renders, mixes, exports...): reads the queue shared with the API through REDIS_URL."""
    import os as _os

    from ugc_studio import jobs

    if not _os.environ.get("REDIS_URL"):
        _fail("REDIS_URL is not set: without Redis, use `ugc serve` (API with an embedded worker).")
    console.print("[green]worker[/] waiting for jobs (gpu + light queues)…")
    jobs.work()


@app.command(rich_help_panel="System")
def providers(project: Annotated[Optional[Path], typer.Argument(help="Project folder (optional)")] = None) -> None:
    """Which model/provider generates images, video, voice and music (local or cloud), and whether keys are set."""
    from ugc_studio import providers as prov

    p = _studio(project).project if project else None
    t = Table(title="Providers" + (f" · {p.title}" if p else " (from .env)"))
    for col in ("capability", "provider", "model", "set by", "API key", "license", "available"):
        t.add_column(col, overflow="fold")
    for r in prov.describe(p):
        keys = ", ".join(f"{'[green]✓' if ok else '[red]✗'}[/] {k}" for k, ok in r["keys"].items()) or "-"
        lic = r["license"] or "-"
        lic = f"[yellow]{lic}" if "UNCERTAIN" in lic or "non-commercial" in lic.lower() else lic
        t.add_row(r["kind"], f"[bold]{r['provider']}", r["model"] or "default", r["source"], keys, lic,
                  ", ".join(r["available"]))
    console.print(t)
    console.print("[dim]Change: providers: {video: kling} in project.yaml, or UGC_VIDEO_PROVIDER=kling in .env "
                  "(see .env.example). Local model checkpoints: UGC_LTX_*, UGC_FLUX_*, UGC_ASR_MODEL...")


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
        steps.append(("voice env", ["uv", "venv", "-q", "--python-preference", "only-managed", "--python", "3.12", ".venv"], config.VENDOR_DIR / "tts"))
        steps.append(("voice packages", ["uv", "pip", "install", "--python", ".venv/bin/python", "qwen-tts",
                                         "soundfile"], config.VENDOR_DIR / "tts"))
    chatterbox_ok = config.CHATTERBOX_PYTHON.is_file() and subprocess.run(
        [str(config.CHATTERBOX_PYTHON), "-c", "import chatterbox, catt_tashkeel"], capture_output=True).returncode == 0
    if not chatterbox_ok:  # Arabic (+ automatic diacritics) and 22 more narration languages (MIT)
        (config.VENDOR_DIR / "chatterbox").mkdir(parents=True, exist_ok=True)
        if not config.CHATTERBOX_PYTHON.is_file():
            steps.append(("arabic voice env", ["uv", "venv", "-q", "--python-preference", "only-managed", "--python",
                                               "3.11", ".venv"], config.VENDOR_DIR / "chatterbox"))
        steps.append(("arabic voice packages", ["uv", "pip", "install", "--python", ".venv/bin/python", "chatterbox-tts",
                                                "soundfile", "setuptools<81", "catt-tashkeel"], config.VENDOR_DIR / "chatterbox"))
    if not config.HABIBI_PYTHON.is_file():  # Arabic dialects (Apache-2.0 specialized checkpoints)
        (config.VENDOR_DIR / "habibi").mkdir(parents=True, exist_ok=True)
        steps.append(("dialect voice env", ["uv", "venv", "-q", "--python-preference", "only-managed", "--python", "3.11", ".venv"], config.VENDOR_DIR / "habibi"))
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
    browsers = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path.home() / ".cache" / "ms-playwright")
    if not any(browsers.glob("chromium-*")):  # already in the Docker image
        steps.append(("browser", [str(Path(os.sys.executable).parent / "playwright"), "install", "chromium"],
                      config.ROOT))
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

    from ugc_studio import service

    with console.status("[cyan]Creating the project (website, then the director writes the script)…") as status:
        r = _svc(service.create_project, name or f"{time.strftime('%Y%m%d-%H%M')}_{mode}", mode, brief, seconds,
                 aspect, quality, language, url, persona, [str(f.expanduser()) for f in face or []], product,
                 [str(f.expanduser()) for f in product_image or []], style, seed,
                 progress=lambda stage, msg: status.update(f"[cyan]{stage}: {msg}"))
    folder = Path(r["path"])
    _show_project(service.load(folder))
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
    offload: Annotated[Optional[str], typer.Option(help="LTX weights: cpu (12 GB GPUs) or none; default UGC_LTX_OFFLOAD")] = None,
    qa: Annotated[bool, typer.Option(help="Run the quality check at the end")] = True,
) -> None:
    """Build the video. Resumable and incremental: only what changed since last time is regenerated."""

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
    from ugc_studio import service

    if undo:
        r = _svc(service.undo_fix, project, undo)
        console.print(f"[green]undone[/] {r['removed']}" if r["removed"] else f"[yellow]{undo} has no fix or reshoot to undo")
        return
    if at is None and not scene:
        _fail("give --at <seconds> (where the problem is) or --scene <id>")
    r = _svc(service.add_fix, project, at, duration, mode, prompt, seed, scene)
    if at is not None:
        console.print(f"{at:.2f}s → scene [bold]{r['scene']}[/] at {r.get('local', 0):.2f}s of its clip")
    if r["action"] == "none":
        console.print(Panel(r["message"], border_style="yellow"))
        return
    if r["action"] == "reshoot":
        console.print(f"[green]reshoot[/] {r['scene']}: " + (f"seed {seed}" if seed is not None else f"take {r['take']}")
                      + (", new prompt" if prompt else ""))
    else:
        console.print(f"[green]{r['action']}[/] {r['scene']} {r['start']:.2f}-{r['end']:.2f}s (clip time)")
    if now:
        render(Path(project), None, "web", True, None, True)
    else:
        console.print(f"Apply with: [bold]ugc render {project}[/] (only {r['scene']} and the final edit are rebuilt)")


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
    from ugc_studio import service

    with console.status(f"[cyan]encoding {fmt}…"):
        out = _svc(service.export, project, fmt, at)
    if fmt == "cover":
        console.print(f"[green]✓ {out}[/] (upload it as the TikTok/Reels cover)")
        return
    if fmt in service.EXPORT_SIZES:
        console.print("[yellow]Reframed by center crop: for a native layout, set aspect in project.yaml and render.")
    console.print(f"[green]✓ {out}")


@app.command(rich_help_panel="Produce")
def qa(target: Annotated[Path, typer.Argument(help="Project folder or video file")]) -> None:
    """Quality report: frames, audio loudness, speech vs script, black/frozen/flicker, contact sheet."""
    video, st = target, None
    if target.is_dir():

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
    """Generate or edit one image (UGC_IMAGE_PROVIDER, default FLUX.2 klein; --ref keeps a person/product)."""
    from ugc_studio import providers
    from ugc_studio.images import keyframe_size

    w, h = keyframe_size(config.resolution(aspect, "standard"), 1.0)
    g = providers.create(None, "image")
    try:
        g.generate(prompt, w, h, seed, references=[str(r) for r in ref or []], out_path=out)
    finally:
        g.close()
    console.print(f"[green]✓ {out}[/] ({w}x{h})")


# ====================================================================== voice-over and timeline (mix only)
def _svc(fn, *a, **kw):
    """Run a service call with readable errors (ServiceError and invalid project.yaml are both ValueErrors)."""
    try:
        return fn(*a, **kw)
    except (ValueError, FileNotFoundError, KeyError) as e:
        _fail(str(e))


def _mix_rebuild(project: Path) -> None:
    """Narration + mix only: refuses (with the reason) if the change would need new keyframes or video shots."""
    from ugc_studio import service

    def progress(stage: str, msg: str) -> None:
        console.print(f"  [cyan]{stage:<7}[/] {msg}")

    try:
        res = service.rebuild_mix(project, progress)
    except (service.ServiceError, FileNotFoundError, ValueError, RuntimeError) as e:
        _fail(str(e))
    for w in res.warnings:
        console.print(f"[yellow]⚠ {w}")
    for kind, path in res.deliveries.items():
        console.print(f"[green]✓ {kind}:[/] {path}")
    console.print(f"[dim]{res.timeline.total:.2f}s video · voice + mix rebuilt in {_fmt(res.seconds)}")


RenderOpt = Annotated[bool, typer.Option(help="Rebuild narration + mix now")]


@voice_app.command("list")
def voice_list(project: ProjectArg) -> None:
    """Every narration line: text, accuracy, sound quality, length, what was heard, and what would be redone."""
    from ugc_studio import service

    v = _svc(service.voice_lines, project)
    console.print(f"Engine: [bold]{v['engine']}[/]" + (f" · voice {v['voice_id']}" if v["voice_id"] else "")
                  + (f" · file {v['file']}" if v["file"] else ""))
    t = Table(show_lines=True)
    for col in ("scene", "text", "words", "sound", "length", "heard", "state"):
        t.add_column(col, overflow="fold")
    for ln in v["lines"]:
        state = "[yellow]will redo" if ln["stale"] else "[green]ok" + (f" (take {ln['take']})" if ln["take"] else "")
        if ln["pinned_at"] is not None:
            state += f" · pinned {ln['pinned_at']:.2f}s"
        t.add_row(ln["id"], ln["text"], f"{ln['score']:.0%}" if ln["score"] is not None else "-",
                  f"{ln['quality']:.2f}" if ln["quality"] else "-", f"{ln['seconds']:.1f}s" if ln["seconds"] else "-",
                  ln["heard"] or "-", state)
    console.print(t)


@voice_app.command("set")
def voice_set(project: ProjectArg, scene: str, text: str, render: RenderOpt = True) -> None:
    """Change the words of one narration line."""
    from ugc_studio import service

    _svc(service.voice_set, project, scene, text)
    console.print(f"[green]✓[/] {scene}: {text}")
    if render:
        _mix_rebuild(project)


@voice_app.command("redo")
def voice_redo(project: ProjectArg, scenes: Annotated[list[str], typer.Argument(help="Scene id(s)")],
               render: RenderOpt = True) -> None:
    """Record a new take of these lines (same words, new delivery); the other lines stay as they are."""
    from ugc_studio import service

    _svc(service.voice_redo, project, scenes)
    console.print(f"[green]✓[/] new take for {', '.join(scenes)}")
    if render:
        _mix_rebuild(project)


@voice_app.command("engine")
def voice_engine(project: ProjectArg,
                 engine: Annotated[str, typer.Argument(help="auto, qwen, chatterbox, habibi, elevenlabs, openai, gemini")],
                 voice_id: Annotated[Optional[str], typer.Option(help="Cloud voice id/name")] = None,
                 model: Annotated[Optional[str], typer.Option(help="Cloud TTS model")] = None,
                 dialect: Annotated[Optional[str], typer.Option(help="Arabic dialect for habibi: MSA ALG EGY IRQ MAR")] = None,
                 render: RenderOpt = True) -> None:
    """Switch the narration voice/engine for the whole video (all lines are re-voiced, the shots are kept)."""
    from ugc_studio import service

    _svc(service.voice_engine, project, engine, voice_id, model, dialect)
    console.print(f"[green]✓[/] voice engine: {engine}")
    if render:
        _mix_rebuild(project)


@voice_app.command("file")
def voice_file(project: ProjectArg, audio: Annotated[Path, typer.Argument(help="Your voice-over (mp3, wav, m4a...)")],
               render: RenderOpt = True) -> None:
    """Use your own recording as the voice-over (copied into the project, transcribed and cut per scene)."""
    from ugc_studio import service

    _svc(service.voice_file, project, audio)
    console.print(f"[green]✓[/] voice-over file: {audio}")
    if render:
        _mix_rebuild(project)


@timeline_app.command("show")
def timeline_show(project: ProjectArg) -> None:
    """The edit as tracks: video scenes, voice lines, music, extra audio (times in the final video)."""
    from ugc_studio import service

    v = _svc(service.timeline_view, project)
    console.print(f"[bold]{v['total']:.2f}s[/] · {v['fps']} fps")
    for tr in v["tracks"]:
        t = Table(title=tr["id"], title_justify="left", box=None)
        for col in ("clip", "start", "end", "details"):
            t.add_column(col, overflow="fold")
        for cl in tr["clips"]:
            end = cl["start"] + cl["dur"] if cl.get("dur") else None
            if tr["id"] == "video":
                det = f"{cl['kind']} · {cl['transition']} · {cl['label']}"
            elif tr["id"] == "voice":
                det = ("[magenta]pinned[/] " if cl["manual"] else "") + cl["text"]
            elif tr["id"] == "music":
                det = f"offset {cl['offset']}s · {cl['gain_db']:+.1f} dB · fades {cl['fade_in']}/{cl['fade_out']}s"
            else:
                det = f"{Path(cl['file']).name} · {cl['gain_db']:+.1f} dB" + (" · ducks music" if cl["duck"] else "")
            t.add_row(cl["id"], f"{cl['start']:.2f}", f"{end:.2f}" if end is not None else "end", det)
        if tr["clips"]:
            console.print(t)
    for w in v["warnings"]:
        console.print(f"[yellow]⚠ {w}")
    if v["missing_voice"]:
        console.print(f"[dim]not generated yet (placed after the next render): {', '.join(v['missing_voice'])}")


@timeline_app.command("move")
def timeline_move(project: ProjectArg, scene: Annotated[str, typer.Argument(help="Scene id of the voice line")],
                  at: Annotated[Optional[float], typer.Option(help="Start of the line (s in the final video)")] = None,
                  auto: Annotated[bool, typer.Option("--auto", help="Back to automatic placement")] = False,
                  gain: Annotated[Optional[float], typer.Option(help="Line volume (dB)")] = None,
                  render: RenderOpt = True) -> None:
    """Move a narration line anywhere on the timeline (it may overlap the next scene, like an L-cut)."""
    from ugc_studio import service

    if not auto and at is None:
        _fail("give --at <seconds> or --auto")
    _svc(service.move_voice, project, scene, None if auto else at, gain)
    console.print(f"[green]✓[/] {scene}: " + ("automatic placement" if auto else f"starts at {at:.2f}s"))
    if render:
        _mix_rebuild(project)


@timeline_app.command("add-audio")
def timeline_add_audio(project: ProjectArg, file: Annotated[Path, typer.Argument(help="Sound, jingle, recording")],
                       at: Annotated[float, typer.Option(help="Start (s in the final video)")] = 0.0,
                       trim_start: Annotated[Optional[float], typer.Option(help="Skip into the file (s)")] = None,
                       duration: Annotated[Optional[float], typer.Option(help="Play this long (s)")] = None,
                       gain: Annotated[Optional[float], typer.Option(help="Volume (dB)")] = None,
                       fade_in: Optional[float] = None, fade_out: Optional[float] = None,
                       duck: Annotated[bool, typer.Option(help="It is speech: lower the music under it")] = False,
                       clip_id: Annotated[Optional[str], typer.Option("--id")] = None,
                       render: RenderOpt = True) -> None:
    """Place an extra sound on the timeline (copied into the project)."""
    from ugc_studio import service

    clip = _svc(service.add_audio, project, file, at, clip_id, trim_start=trim_start, duration=duration,
                gain_db=gain, fade_in=fade_in, fade_out=fade_out, duck=duck)
    console.print(f"[green]✓[/] audio [bold]{clip.id}[/] at {clip.at:.2f}s")
    if render:
        _mix_rebuild(project)


@timeline_app.command("set-audio")
def timeline_set_audio(project: ProjectArg, clip_id: Annotated[str, typer.Argument(help="Audio clip id")],
                       at: Optional[float] = None, trim_start: Optional[float] = None,
                       duration: Optional[float] = None, gain: Optional[float] = None,
                       fade_in: Optional[float] = None, fade_out: Optional[float] = None,
                       duck: Annotated[Optional[bool], typer.Option("--duck/--no-duck")] = None,
                       render: RenderOpt = True) -> None:
    """Move or adjust an extra sound."""
    from ugc_studio import service

    fields = dict(at=at, trim_start=trim_start, duration=duration, gain_db=gain, fade_in=fade_in, fade_out=fade_out,
                  duck=duck)
    _svc(service.update_audio, project, clip_id, **{k: v for k, v in fields.items() if v is not None})
    console.print(f"[green]✓[/] audio {clip_id} updated")
    if render:
        _mix_rebuild(project)


@timeline_app.command("remove-audio")
def timeline_remove_audio(project: ProjectArg, clip_id: str, render: RenderOpt = True) -> None:
    """Remove an extra sound from the timeline."""
    from ugc_studio import service

    _svc(service.remove_audio, project, clip_id)
    console.print(f"[green]✓[/] removed {clip_id}")
    if render:
        _mix_rebuild(project)


@timeline_app.command("music")
def timeline_music(project: ProjectArg,
                   start: Annotated[Optional[float], typer.Option(help="Music enters at (s)")] = None,
                   offset: Annotated[Optional[float], typer.Option(help="Skip into the music (s)")] = None,
                   gain: Annotated[Optional[float], typer.Option(help="Extra volume (dB)")] = None,
                   fade_in: Optional[float] = None, fade_out: Optional[float] = None,
                   render: RenderOpt = True) -> None:
    """Place and shape the music bed."""
    from ugc_studio import service

    _svc(service.set_music, project, start=start, offset=offset, gain_db=gain, fade_in=fade_in, fade_out=fade_out)
    console.print("[green]✓[/] music updated")
    if render:
        _mix_rebuild(project)


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
    from ugc_studio import service

    with console.status("[cyan]quality check…"):
        r = _svc(service.qa, st.dir if st is not None else None, video)
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
