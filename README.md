# UGC Studio

**Open-source AI video production that runs on one 12 GB GPU.** It makes UGC testimonials, AI-influencer videos, faceless viral clips and product commercials for social or TV, from a brief, your photos or your website. Local open-source models do the work by default, and cloud models can be plugged in if you prefer.

![demo](docs/media/demo.gif)

*Real outputs, unedited: a 30 s TV spot in Algerian Arabic, a UGC ad with the real app on the phone, 3D product reveals, RTL graphics.*

## What makes it different

- **Automatic quality gates on everything it generates.**
  - **Speech:** a Whisper word check, plus a *phoneme-level* pronunciation check (Whisper alone "hears" *bancaire* when the actor said *banchaire*).
  - **Images:** CLIP prompt match and DINOv2 identity consistency.
  - **Voice:** a speech-quality score picks the best take.
  - **Result:** a failing shot or line is regenerated automatically before you ever see it.
- **Surgical fixes.** `ugc fix --at 12.4` repairs a glitch, a time window or one shot. Everything else stays cached: the whole pipeline is content-addressed and incremental.
- **Your real product on screen.** App screens are composited onto AI-filmed phones with perspective tracking. Device mockups, feature cards and endcards come from an HTML/GSAP motion engine, with right-to-left support for Arabic.
- **An editor, not a black box.** Change one voice-over line, re-voice everything, move lines on the timeline, add sounds, shape the music. The mix rebuilds in minutes without re-rendering video. The CLI, an HTTP API and a web app all do the same things.
- **Local-first, provider-pluggable.**
  - **Local by default:** LTX-2.5 video with native audio and lip-sync, FLUX.2 klein images, Qwen3-TTS / Chatterbox / Habibi (Arabic dialects) narration, ACE-Step music.
  - **Cloud when you want:** Veo 3.1, Kling 3.0 or Seedance 2.5 video; OpenAI or Gemini images; ElevenLabs, OpenAI or Gemini voices and music.
  - **One switch:** a line in `.env` or `project.yaml`.
- **Multilingual:** English, French, Spanish… and Arabic, including dialects, diacritized for correct pronunciation.

## Quick start

### Docker (web app + API + GPU worker)

```bash
cp .env.example .env                       # optional: keys, model overrides
docker compose up -d --build               # web: http://localhost:3000 · API docs: http://localhost:8000/docs
docker compose run --rm worker ugc setup            # once: voice + music environments
docker compose run --rm worker ugc models download  # once: model weights (~90 GB, needs HF_TOKEN)
```

Requires an NVIDIA GPU (12 GB+) with the NVIDIA Container Toolkit, and about 64 GB RAM for local video.

### Command line

```bash
git clone --recurse-submodules <this repo> && cd video_ugc
uv sync && .venv/bin/ugc setup && .venv/bin/ugc models download && .venv/bin/ugc doctor
ugc new                               # wizard: mode, brief, photos/website → script
ugc plan outputs/<project>            # what will be generated + time estimate
ugc render outputs/<project>          # incremental, resumable
ugc fix outputs/<project> --at 12.4   # repair only what's broken
ugc voice set outputs/<project> s03 "New line."   # re-voice one line (video untouched)
ugc timeline move outputs/<project> s03 --at 9.5  # place it by hand
ugc serve                             # API + worker for the web app (no Docker)
```

## Documentation

| | |
|---|---|
| [GUIDE.md](docs/GUIDE.md) | Every mode, every combination of your own images / videos / voice / music, fixes, commands |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it works inside: pipeline, cache, quality gates, providers, API, extension points |
| [LICENSES.md](docs/LICENSES.md) | Model and tool licenses for commercial use (read before client work) |
| [.env.example](.env.example) | Every setting: providers, API keys, local model checkpoints |
| `/docs` on the API | Interactive HTTP API reference (OpenAPI: [docs/openapi.json](docs/openapi.json)) |

## Honest limits

- **Speed:** local 1080p video takes about 6 min per 5 s shot on a laptop RTX 4000 Ada (12 GB, 115 W), so a 30 s spot with 4-6 AI shots takes 30-60 min. Cloud video providers are faster but paid.
- **Voices:** voices are synthetic. Arabic dialect quality is checked word by word, but the accent can't be judged automatically. Have a native speaker listen before airing, or clone a real voice actor (with consent).
- **Licenses:** the default video model (LTX-2.5) is free for companies under $10M revenue and requires disclosing AI-generated content. Habibi dialect voices have an uncertain commercial status. See [LICENSES.md](docs/LICENSES.md).

## Tests

```bash
.venv/bin/python -m pytest tests -q   # whole pipeline with stub models + mocked cloud APIs + real API/worker jobs
```
