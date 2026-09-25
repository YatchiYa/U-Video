# UGC Studio

Local AI video production on a single 12 GB GPU: **UGC testimonials**, **AI influencers** (reusable personas),
**faceless viral** videos and **product commercials from a website** (social or TV), from 15 s to several minutes.
Accepts your photos of people and products, generates every other frame, then video, voice, music, captions and edit.

**Read the guide: [docs/GUIDE.md](docs/GUIDE.md)**

```bash
uv sync && .venv/bin/ugc setup && .venv/bin/ugc models download && .venv/bin/ugc doctor
ugc new                     # interactive wizard
ugc plan outputs/<project>  # what will be generated, time estimate
ugc render outputs/<project>
ugc fix outputs/<project> --at 12.4   # repair only what's broken
```

Stack: LTX-2.5 (video + speech), FLUX.2 klein (images), Qwen3-TTS (narration), ACE-Step 1.5 (music),
Whisper (QA, captions), Qwen3-4B (director), HTML/GSAP motion engine, ffmpeg.

Tests: `.venv/bin/python -m pytest tests` (runs the whole pipeline with stub models, no GPU generation).
