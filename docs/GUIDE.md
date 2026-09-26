# UGC Studio: the complete guide

UGC Studio makes finished videos on your own GPU: **UGC testimonials**, **AI influencer** content, **faceless viral**
videos and **product commercials** (social or TV), from 15 seconds to several minutes. You can give it photos of a
person or a product; it generates every other image and frame it needs, then the video, voice, music, captions and
edit. Nothing leaves your machine.

---

## Contents

1. [How it works](#1-how-it-works)
2. [Setup (once)](#2-setup-once)
3. [Your first video in 3 commands](#3-your-first-video-in-3-commands)
4. [The four modes](#4-the-four-modes)
   - [UGC testimonial](#41-ugc-testimonial)
   - [Influencer (reusable persona)](#42-influencer-reusable-persona)
   - [Faceless viral](#43-faceless-viral)
   - [Promo / TV commercial from a website](#44-promo--tv-commercial-from-a-website)
5. [Using your own images (or none)](#5-using-your-own-images-or-none)
   - [Every combination: what you have → what to write](#5b-every-combination-what-you-have--what-to-write)
6. [Seamless videos: continuity and transitions](#6-seamless-videos-continuity-and-transitions)
7. [Review, fix, re-render (only what changed)](#7-review-fix-re-render-only-what-changed)
   - [Change only the voice-over](#7b-change-only-the-voice-over)
   - [Choose your models: local or cloud](#7c-choose-your-models-local-or-cloud)
   - [Place things by hand on the timeline](#7d-place-things-by-hand-on-the-timeline)
8. [project.yaml reference](#8-projectyaml-reference)
9. [Command reference](#9-command-reference)
10. [Quality, speed and limits](#10-quality-speed-and-limits)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. How it works

Every video is a **project folder** with one file you can read and edit: `project.yaml`. It lists **scenes** in
order. Everything else (images, clips, voice, music, the edit) is generated from it and cached.

```
you ──► ugc new ──► project.yaml ──► ugc render ──► out/<title>_web.mp4
          │              ▲  │                          │
     (director writes    │  └── edit it anytime ───────┘
      the script)        └──── ugc fix --at 12.4 (repairs only what's broken)
```

| Stage | Model (all local) | What it makes |
|---|---|---|
| Script | Qwen3-4B | scenes, dialogue, narration, headlines |
| Images | FLUX.2 [klein] 4B | identity references, first frames, seam frames, stills |
| Video + on-camera speech | LTX-2.5 22B (distilled) | each shot, lip-synced dialogue, ambient sound |
| Narration | Qwen3-TTS | one designed voice, cloned for every line, checked with Whisper |
| Music | ACE-Step 1.5 | original instrumental, best of 2 candidates |
| Screens | Chromium | real scroll recordings of your website |
| Graphics | HTML + GSAP engine | titles, device mockups, feature cards, end card, QR, captions, transitions |
| Edit | ffmpeg | transitions, color match, ducking, loudness, TV/web deliveries |

**Incremental by design.** Each asset remembers exactly what it was made from. Change one line in
`project.yaml` and `ugc render` regenerates only that scene and the final edit. A second render with no changes
takes seconds.

---

## 2. Setup (once)

```bash
cd ~/Bureau/discovery/video_ugc
uv sync                           # Python environment
echo "HF_TOKEN=hf_xxx" > .env     # Hugging Face read token; accept https://huggingface.co/Lightricks/LTX-2.5
.venv/bin/ugc setup               # motion engine assets, voice + music environments, browser
.venv/bin/ugc models download     # ~90 GB of weights
.venv/bin/ugc doctor              # everything should say OK
```

> **Laptop tip:** `ugc doctor` warns when the power profile caps the GPU. On this laptop "balanced" limits the GPU to
> 40 W; `powerprofilesctl set performance` gives it 115 W and renders about twice as fast.

Add `.venv/bin` to your PATH (or prefix commands with `.venv/bin/`). All commands have `--help`.

### Or: the web app (Docker)

No command line needed after installation. The web app guides you step by step: create, check the storyboard,
generate, fix a moment, change the voice, edit the timeline, export.

```bash
cp .env.example .env
docker compose up -d --build                         # web app: http://localhost:3000
docker compose run --rm worker ugc setup             # once
docker compose run --rm worker ugc models download   # once (skip if ./models is already filled)
```

To reuse the models you already downloaded, point the containers at your folders in `.env`:
`UGC_MODELS_HOST=/path/to/models`, `UGC_OUTPUTS_HOST=/path/to/outputs`, `HF_CACHE_HOST=/home/you/.cache/huggingface`.
Without Docker, `ugc serve` starts the API with a built-in worker (the web app then runs with `npm run dev` in `web/`).

---

## 3. Your first video in 3 commands

```bash
ugc new my_first --mode ugc --brief "Testimonial for a vitamin C face serum" --seconds 20
ugc plan outputs/my_first        # storyboard + what will be generated + time estimate
ugc render outputs/my_first      # ~15 min for 20 s at standard quality
```

Run `ugc new` with **no options** for an interactive wizard that asks for mode, brief, length, format, quality,
language, photos and product.

The result is in `outputs/my_first/out/`. `ugc render` ends with a quality report (length, loudness, speech
accuracy against the script, black/frozen/flicker frames) and a contact sheet.

---

## 4. The four modes

| Mode | Who's on screen | Voice | Typical length | Format |
|---|---|---|---|---|
| `ugc` | one creator, selfie style | their own voice, lip-synced | 15-60 s | 9:16 |
| `influencer` | your persistent AI persona | their own voice, lip-synced | 15-90 s | 9:16 |
| `faceless` | cinematic b-roll only | AI narrator | 20-120 s | 9:16 |
| `promo` | live action + your real website + graphics | AI narrator | 15 / 30 / 45 / 60 s exact | 16:9 or 9:16 |

### 4.1 UGC testimonial

```bash
ugc new serum_ugc --mode ugc --seconds 30 \
  --brief "Honest testimonial for Glow Drops vitamin C serum, skin brighter after two weeks" \
  --product "small amber glass dropper bottle with a white label" \
  --product-image ~/photos/glow_drops.jpg \
  --face ~/photos/creator.jpg          # optional: omit to generate a new face
```

- Each 5 s shot has ~12 spoken words, so there is no dead air.
- Shots in the same setup use `continuity: match` (seamless); new setups are clean jump cuts, like real UGC.
- The person's voice is described once (`voice_style`) and reused in every shot so it stays consistent.

### 4.2 Influencer (reusable persona)

Create the persona once, then reuse it in every video: same face, same outfit, same voice.

```bash
# from your photos (2-4 photos: face, three-quarter, half body work best)
ugc persona create mia --description "27-year-old woman, long wavy auburn hair, freckles, cream blazer" \
  --image ~/mia/1.jpg --image ~/mia/2.jpg --voice "a bright, confident female voice, slight British accent"

# or fully generated (a 3-view identity sheet is created from the description)
ugc persona create leo --description "30-year-old man, short black curly hair, trimmed beard, denim jacket" \
  --voice "a calm, warm male voice"

ugc persona list
ugc new mia_skincare --mode influencer --persona mia --seconds 45 \
  --brief "Mia's 3-step morning routine, ends by asking followers their favorite step"
```

Influencer videos get word-by-word TikTok captions and varied setups (home, street, café...) with whip, zoom
and flash transitions.

### 4.3 Faceless viral

```bash
ugc new ocean_facts --mode faceless --seconds 45 --language English \
  --brief "3 terrifying facts about the deep ocean that nobody talks about"
```

- Scroll-stopping first line, a new visual every ~3 s, big centered captions synced to the narration.
- The narrator voice is designed once from `voice.description` and cloned for every line; each line is checked
  with Whisper and regenerated if it doesn't match the script.
- Narration languages: English, French, Spanish, German, Italian, Portuguese, Russian, Chinese, Japanese, Korean.

### 4.4 Promo / TV commercial from a website

```bash
ugc site https://dz-menu.com/fr                  # optional: preview what it reads (brand, pages, headlines)
ugc new dzmenu_30 --mode promo --url https://dz-menu.com/fr --seconds 30 --aspect 16:9 --quality tv \
  --language French --brief "Promote DZ-MeNU to café and restaurant owners in Algeria"
ugc render outputs/dzmenu_30 --deliver web,tv
```

From the URL alone it reads:
- **Brand:** name, colors (from the logo), fonts, logo, phone number.
- **Content:** headlines, sections, calls to action, and real claims. The director is told never to invent numbers.
- **Pages:** used for **scroll recordings on a phone or laptop mockup**. These are frame-exact, with sticky
  headers and fixed bars behaving like on a real phone.

The spot follows a proven structure: problem hook → product reveal → real screens → features → lifestyle →
end card (logo, offer, URL, phone, **a QR code that really scans**). `target_seconds` makes it **exactly** 15, 30, 45 or
60 s, as broadcasters require. `--deliver tv` adds a TV master at -23 LUFS (EBU R128).

**Your other products:** the same command with another URL. Add `--product-image` for physical products so labels
are real, not AI-drawn.

---

## 5. Using your own images (or none)

| You give | Where | Effect |
|---|---|---|
| Photos of a person | `--face`, or `characters[].images` | the same face appears in every generated shot |
| **A video** of a person, pet or product | anywhere an image list is accepted (`characters[].images`, `products[].images`) | the sharpest, most varied frames are extracted as references |
| A saved persona | `--persona mia`, or `characters[].persona` | face + outfit + voice from the persona library |
| Product photos | `--product-image`, or `products[].images` | real product (labels, logo, shape) in the shots |
| An exact first frame | `scenes[].start_image` | the shot starts precisely on your image |
| An exact last frame | `scenes[].end_image` | the shot lands precisely on your image |
| A still to feature | `kind: image` + `image:` | your photo, animated with a slow camera move + captions |
| A screenshot | `kind: screen` + `image:` | shown (and scrolled) inside a phone/laptop mockup |
| Your logo | `brand.logo` (svg/png) | end card, title, logo bug |
| Your own voice | `voice.reference_audio` (+ `reference_text`) | narration cloned from your recording |
| Your own music | `music: {mode: file, file: track.mp3}` | used instead of generated music, auto-ducked |

**Nothing given?** Everything is generated: an identity portrait for each character (then reused in every shot),
a clean packshot for each product, a first frame per shot, seam frames between shots, stills for image scenes.

**Best results with photos:** sharp, well lit, face clearly visible, plain background, no sunglasses. For
products, a clean front shot of the real packaging.

---

## 5b. Every combination: what you have → what to write

The rule is simple: **anything you provide is used as-is, anything missing is generated.** Mix freely. All examples
are complete `project.yaml` files (or the parts to add); run `ugc plan <folder>` to see exactly what will be
generated, then `ugc render <folder>`.

### A. Nothing but an idea

```bash
ugc new my_video --mode faceless --seconds 30 --language Arabic --brief "3 reasons cafés switch to QR menus"
```
Script, images, video, narration, music, captions: all generated.

### B. I have images (people, pet, product, logo, screenshots)

| Your image | Put it in | What happens |
|---|---|---|
| a person / pet (1-4 photos) | `characters: [{id: hero, images: [a.jpg, b.jpg]}]` + `characters: [hero]` in shots | same face/animal in every AI shot |
| a product | `products: [{id: p, images: [box.png]}]` + `products: [p]` in shots | the real product (label, shape) in the shots |
| an exact first frame | `start_image: photo.jpg` in a shot | the AI animates **your** photo |
| an exact last frame | `end_image: final.jpg` | the shot lands on your image |
| a still to show as is | `kind: image` + `image: photo.jpg` | slow camera move + captions over your photo |
| a screenshot of your app/site | `kind: screen` + `image: shot.png` (or `url:`) | shown and scrolled inside a phone/laptop |
| your app on a phone held in an AI shot | `screen_insert: {image: shot.png}` (or `url:`) | your screen composited on the AI phone |
| your logo | `brand: {logo: logo.svg}` | end card, title, logo badge |

```yaml
characters: [{id: sky, description: "gray tabby cat", images: [sky1.jpg, sky2.jpg]}]
scenes:
  - {id: s01, prompt: "the cat dances on a table at a party", characters: [sky]}
  - {id: s02, kind: image, image: shop_front.jpg, caption: ["Now open!"]}
```
Any format works: JPG, PNG, WebP, HEIC (iPhone), AVIF, TIFF, CMYK, transparent PNG, rotated phone photos.

### C. I have videos

| Your video | Put it in | What happens |
|---|---|---|
| footage to use **in** the edit | `kind: clip` + `video: my.mp4` (+ `clip_in`, `seconds`) | your footage becomes a shot: reframed to the format, color-matched, transitions, captions |
| a video **of** a person/pet/product | in `images:` of a character/product | the sharpest, most varied frames become identity references |
| a video to fix | render it as a `kind: clip`, then `ugc fix --at T` | frame repair on your own footage |

```yaml
scenes:
  - {id: intro, kind: clip, video: my_cafe.mp4, clip_in: 3.0, seconds: 4, caption: ["Chez nous"]}
  - {id: ai, prompt: "slow push-in on a latte art cup", seconds: 4, transition: {type: dissolve, seconds: 0.4}}
```

### D. I have my own voice-over (mp3, wav, m4a…)

```yaml
voice: {file: my_voiceover.mp3}
```
- **Without text in the scenes:** your recording is transcribed, split into sentences and spread over the scenes in
  order (proportionally to their `seconds`). The words become the captions.
- **With `voiceover:` text in each scene:** each scene is matched to where that text is spoken in your recording.
- The edit is timed to your voice (scenes stretch or shrink); music ducks under it automatically.

To keep **your voice** but let the system write/redo lines: `voice: {reference_audio: me.wav}` (≥ 5 s of clear
speech). Every narration line is then spoken in your voice.

### E. I have music

```yaml
music: {mode: file, file: track.mp3, volume: 0.5}
```
Your track is used under the whole video, faded out at the end and ducked under speech.

### F. I have a website / an app

```yaml
source_url: https://my-site.com       # or: ugc new --mode promo --url https://my-site.com
```
Brand colors, fonts, logo, headlines and phone number are read automatically. Use real pages in `kind: screen`,
`kind: devices` (2-4 phones, e.g. one per language) and `screen_insert` on AI shots.

### G. I have everything (the complete combination)

```yaml
title: Grand opening
mode: promo
aspect: "9:16"
quality: tv
language: French
target_seconds: 30
brand: {name: Chez Nous, url: https://chez-nous.dz, logo: logo.svg, offer: "-20% cette semaine"}
characters: [{id: chef, description: "the chef", images: [chef1.jpg, chef2.jpg, chef_video.mp4]}]
products: [{id: dish, description: "signature couscous", images: [couscous.jpg]}]
voice: {file: my_voiceover.mp3}                  # your narration
music: {mode: file, file: our_song.mp3}          # your music
captions: {enabled: true, style: tiktok}
scenes:
  - {id: open, kind: clip, video: opening_day.mp4, seconds: 4}                     # your footage
  - {id: chef, prompt: "the chef plates the couscous with a proud smile", characters: [chef], products: [dish]}
  - {id: menu, kind: screen, url: https://chez-nous.dz/menu, reveal: spin, theme: dark, headline: "Notre carte"}
  - {id: photo, kind: image, image: terrace.jpg, caption: ["La terrasse"]}           # your photo
  - {id: scan, prompt: "a customer scans the QR code on the table", screen_insert: {url: https://chez-nous.dz/menu}}
  - {id: end, kind: endcard}
```

### Voices and languages

| Narration language | Engine (automatic) | License |
|---|---|---|
| French, English, Spanish, German, Italian, Portuguese, Russian, Chinese, Japanese, Korean | Qwen3-TTS (designed voice, cloned for every line) | Apache-2.0 |
| **Arabic** (MSA) and Danish, Greek, Finnish, Hebrew, Hindi, Malay, Dutch, Norwegian, Polish, Swedish, Swahili, Turkish | Chatterbox Multilingual | MIT |
| **Arabic dialects**: Algerian (`voice: {dialect: ALG}`), Egyptian (EGY), Iraqi (IRQ), Moroccan (MAR) | Habibi-TTS specialized checkpoints | Apache-2.0 |
| any language | your own recording: `voice: {file: …}` | yours |

Brand names and acronyms: write them normally and add a pronunciation, e.g.
`pronounce: {"DZ-MeNU": "دي زاد مينيو"}`: captions show "DZ-MeNU", the narrator says it right. Arabic, Hebrew and
other right-to-left text is laid out right-to-left automatically in every title, card, caption and end card.

## 6. Seamless videos: continuity and transitions

This is what makes many shots feel like **one** video.

### Continuity (per shot: `continuity:`)

| Value | How the shot starts | Use it for |
|---|---|---|
| `cut` | its own generated (or given) first frame | a new setup, a new angle |
| `continue` | the previous shot's real last frame | **the default for "same setup, the action goes on"**: nothing can pop in, the second shot simply carries on (re-rendering the previous shot re-renders this one) |
| `match` | a generated seam frame pinned as the last frame of the previous shot and the first of this one | two shots you want to re-render independently. **Rule:** the seam must not introduce anything new (no object appearing, no outfit change), or it will pop into the previous shot's last frame |

For `match` and `continue`, the duplicated seam frame is dropped automatically, so there's no stutter.

### Transitions (per scene: `transition: {type: …, seconds: …}`)

`cut` · `dissolve` · `fade` · `fadewhite` · `whip` (motion-blur pan) · `zoom` · `slide` · `circle` · `wipe` / `brand`
(diagonal wipe in your brand colors). Audio crossfades with the picture. Run `ugc transitions` to list them.

### Also automatic

- **Color match:** every shot is graded toward the first shot's look (`color_match: true`), so lighting doesn't
  jump between shots.
- **One voice:** UGC/influencer voices come from one `voice_style`, and narration is cloned from one reference.
- **Music** runs under the whole video and ducks under speech.
- **Long shots:** a shot longer than ~5 s is generated in invisible continuation segments.

---

### Automatic speech check (on-camera modes)

Right after each speaking shot is rendered, its audio is transcribed (Whisper) and compared with the script. If the
words don't match (a mispronounced "bancaire", a missing word), the shot is **re-shot automatically with new
seeds** and the best take is kept (`speech_min: 0.95`, `speech_retries: 2` in `project.yaml`). `ugc plan` shows
which shots will be checked.

### Quality gates (automatic, every project)

Every generated asset is measured before it is used, and retried automatically when it misses. You get the best
take, and `ugc status` / `.ugc/state.json` record every score.

| Asset | Checks | On failure |
|---|---|---|
| Your files | readable, any format (JPG/PNG/WebP/HEIC/AVIF/TIFF, CMYK, transparent, EXIF-rotated; videos; any audio) | normalized automatically, or a clear error before anything runs |
| Keyframes | best of `image_candidates` (default 2): prompt match (CLIP) + identity to your references (DINOv2); exact number of phone screens for screen inserts | extra candidates; the best one is kept |
| Every shot | no black/frozen video, the subject stays the same person/animal/product | automatic re-take (new seed) |
| Speaking shots | words (Whisper) **and** pronunciation (phonemes: catches "banchaire" for "bancaire") | re-takes up to `speech_retries`, best take kept |
| Narration | words + pronunciation per line | regenerated up to 3 times |
| Screen inserts | zero green left on the phone, on every frame | the render stops with the shot to reshoot |
| Final video | length, loudness, black/frozen/flicker, speech vs script | reported by `ugc qa` |

Settings in `project.yaml`: `image_candidates`, `visual_check`, `speech_check`, `speech_min`, `speech_retries`,
`pronounce` (e.g. `{"DZ-MeNU": "Dé-Zèd Menu"}`: scripts and captions keep the written form, voices say the spoken
one).

### Your real app on phones filmed by the AI

Add `screen_insert` to any shot where a phone appears:

```yaml
  - id: s02
    prompt: "She holds her phone up and shows the screen to the camera..."
    screen_insert: {url: "https://your-site.com/menu"}   # or {image: screenshot.png}
```

The shot is generated with a chroma-green screen (the keyframe is checked to contain exactly one), then your page is
recorded live and composited in perspective on every frame: phone tracked by optical flow, fingers kept in front,
shading preserved, dark glass when the phone is edge-on. Works in any shot, at any angle.

## 7. Review, fix, re-render (only what changed)

```bash
ugc status outputs/my_video          # every scene: cached ✓ / pending ●, fixes, time in the final video
ugc preview outputs/my_video --open  # contact sheet, one frame per second, timestamped
ugc preview outputs/my_video --at 12.4 --at 12.5
ugc qa outputs/my_video              # the quality report again
```

### Something is wrong at second 12.4?

```bash
ugc fix outputs/my_video --at 12.4                   # auto: picks the smallest fix that works
ugc fix outputs/my_video --at 12.4 --duration 0.1    # a glitch of a few frames
ugc render outputs/my_video                          # rebuilds ONLY that scene + the final edit
```

`--at` finds the scene and the exact frame inside its clip (transitions and speed changes included), then applies:

| Mode | When | What happens | Cost |
|---|---|---|---|
| `interpolate` | glitch ≤ 0.25 s (flicker, a warped hand for a few frames) | frames rebuilt from their neighbours with optical flow | seconds, no AI |
| `freeze` | a very short glitch where motion doesn't matter | the last good frame is held | seconds |
| `retake` | a longer problem (0.25-3 s) | LTX regenerates **only that window**; the rest of the clip is untouched | ~2-6 min |
| `reshoot` | the whole shot is wrong | a new video take (`take: N` in the scene); keyframes and seams are kept; add `--seed` to also redraw the keyframe | one shot render |

```bash
ugc fix outputs/my_video --at 12.4 --mode retake --prompt "her hand holds the bottle steadily"
ugc fix outputs/my_video --scene s04 --mode reshoot --seed 123
ugc fix outputs/my_video --undo s04        # remove the last fix of a scene
```

Fixes are written into `project.yaml` (under the scene's `fixes:`), so they're **non-destructive, repeatable and
undoable**: the original clip is never modified.

**Text or graphics wrong?** (headline, caption, feature, offer...) Edit `project.yaml` (`ugc edit`) and render:
only the graphics layer is redrawn, with no AI generation.

### 7b. Change only the voice-over

The narration never forces a new video. These commands re-voice what you ask, re-mix, and **refuse** if the change
would need new shots (they tell you to run `ugc render` instead). About 4 minutes, no GPU video work.

```bash
ugc voice list outputs/my_video                           # every line: text, accuracy, sound quality, heard as...
ugc voice set  outputs/my_video s03 "Nouveau texte ici."  # new words for one line
ugc voice redo outputs/my_video s03 s05                   # new takes of these lines (others untouched)
ugc voice engine outputs/my_video elevenlabs --voice-id <id>   # another voice/engine for the whole video
ugc voice file outputs/my_video my_voiceover.mp3          # your own recording, cut per scene automatically
```

Add `--no-render` to only edit `project.yaml`. A `.bak` of the previous file is kept. On-camera `dialogue` (UGC) is
spoken by the video model: change it with `ugc fix --scene s01 --mode reshoot` after editing the line.

### 7c. Choose your models: local or cloud

By default everything runs locally with open-source models. Any capability can use another provider:

| Capability | Choices |
|---|---|
| images | `local` (FLUX.2 klein), `openai`, `gemini`, `huggingface` |
| video | `local` (LTX-2.5), `veo` (Google Veo 3.1), `kling` (Kling 3.0), `seedance` (ByteDance) |
| voice | `auto` / `qwen` / `chatterbox` / `habibi` (local), `elevenlabs`, `openai`, `gemini` |
| music | `local` (ACE-Step), `elevenlabs` |

For all projects, in `.env` (copy `.env.example`):

```bash
UGC_VIDEO_PROVIDER=kling
KLING_API_KEY=...
```

For one project, in `project.yaml` (wins over `.env`):

```yaml
providers: {video: veo, image: openai}
voice: {engine: elevenlabs, voice_id: <your ElevenLabs voice id>}
```

Check what will be used and whether keys are set: `ugc providers` (or `ugc providers outputs/my_video`).
Quality gates, captions, edit and fixes work the same with every provider. Local checkpoints can be swapped too
(`UGC_LTX_*`, `UGC_FLUX_REPO`, `UGC_ASR_MODEL`...): see `.env.example` and [ARCHITECTURE.md](ARCHITECTURE.md).

### 7d. Place things by hand on the timeline

Everything is placed automatically; take control only where you want. Same effect in the web app's timeline editor.

```bash
ugc timeline show outputs/my_video                       # tracks: scenes, voice lines, music, extra sounds
ugc timeline move outputs/my_video s03 --at 9.5          # this line starts at 9.5 s (may overlap the next scene)
ugc timeline move outputs/my_video s03 --auto            # back to automatic
ugc timeline add-audio outputs/my_video whoosh.wav --at 4.2 --gain -6 --fade-out 0.3
ugc timeline add-audio outputs/my_video testimonial.mp3 --at 12 --duck   # speech: lowers the music under it
ugc timeline set-audio outputs/my_video whoosh --at 4.0
ugc timeline remove-audio outputs/my_video whoosh
ugc timeline music outputs/my_video --start 1.5 --offset 8 --gain -3 --fade-out 2
```

Each command saves the change in `project.yaml` (under `edit:`) and rebuilds only the sound mix: never the video.
A voice line moved past the end of the video is refused and nothing changes.

---

## 8. project.yaml reference

```yaml
title: Glow Drops UGC            # used for output file names
mode: ugc                        # ugc | influencer | faceless | promo
style: ugc                       # visual style: ugc | promo | anime | cinematic | realistic
aspect: "9:16"                   # 9:16 | 16:9 | 1:1 | 4:5
quality: standard                # draft | standard | high | tv (native 1080p)
fps: 24                          # 24 (social) / 25 (TV)
language: English
seed: 42
target_seconds: 30               # optional: exact final length (promo)
look: ""                         # extra visual direction for every shot
voice_style: "a warm, upbeat female voice"     # on-camera voice (ugc/influencer)
color_match: true
logo_bug: false                  # small brand badge on live-action scenes

brand: {name: Acme, tagline: "...", url: https://acme.com, phone: "+1 ...", offer: "30 days free",
        logo: logo.svg, primary: "#6c2bd9", secondary: "#a163ff", dark: "#161320", light: "#fbf9f6"}

characters:
  - id: hero
    description: "28-year-old woman, long curly brown hair, freckles, beige knit sweater"
    images: [photos/me1.jpg, photos/me2.jpg]   # optional
    persona: mia                               # optional: use a saved persona instead
products:
  - {id: serum, description: "small amber dropper bottle, white label", images: [photos/serum.jpg]}

voice:   {enabled: true, description: "a warm professional male voice-over", tempo: 1.0,
          reference_audio: null, reference_text: null}
music:   {mode: generate, prompt: "uplifting pop instrumental", volume: 0.5}   # generate | file | none
captions: {enabled: true, style: tiktok, position: bottom}                    # tiktok | clean

scenes:
  - id: s01                      # letters, digits, - and _
    kind: shot                   # shot | image | title | screen | features | endcard
    seconds: 5
    prompt: "Selfie close-up in a bright bathroom, she holds the bottle next to her cheek, handheld"
    dialogue: "Okay, I have to tell you about this serum, it's honestly insane."   # on camera (ugc/influencer)
    # voiceover: "..."           # narration instead (faceless/promo)
    caption: ["Menus abîmés.", "Prix raturés."]   # optional kinetic lines on screen
    characters: [hero]
    products: [serum]
    continuity: cut              # cut | match | continue
    start_image: null            # your exact first frame (optional)
    start_prompt: null           # describe the first frame (otherwise derived from prompt)
    end_image: null              # your exact last frame (optional)
    end_prompt: null
    transition: {type: cut, seconds: 0.0}
    clip_in: 0.0                 # skip the first seconds of the generated clip
    seed: null                   # set to lock or change this shot
    ambience: 0.35               # level of the shot's own sound (narrated modes)
    fixes: []                    # written by `ugc fix`

  - {id: t1, kind: title, seconds: 3, headline: "Meet Acme", eyebrow: "New", caption: ["subtitle line"]}
  - {id: sc1, kind: screen, seconds: 4.5, url: "https://acme.com/app", device: phone,
     eyebrow: "No app needed", headline: "Scan and go", bullets: ["Instant", "Always up to date"]}
  - {id: sc2, kind: screen, seconds: 4, url: "https://acme.com/app", reveal: spin, theme: dark,   # 3D spin + light burst
     headline: "Your menu, in one scan"}
  - {id: langs, kind: devices, seconds: 3.5, theme: dark, headline: "3 languages. 1 QR.",        # 3D fan of 2-4 phones
     devices: [{url: "https://acme.com/fr", label: Français}, {url: "https://acme.com/ar", label: العربية},
               {url: "https://acme.com/en", label: English}]}
  - {id: im1, kind: image, seconds: 3, image: photos/storefront.jpg, caption: ["Now open in Oran"]}
  - {id: f1, kind: features, seconds: 4.5, headline: "Everything in one place",
     features: [{title: Reservations, subtitle: "hours, capacity", icon: calendar-check}]}
  - {id: end, kind: endcard, seconds: 3, headline: "Your menu online today", offer: "30 days free"}
```

Validation is strict: a typo in a field name, an unknown character id or a missing file is reported before
anything is generated.

---

## 9. Command reference

| Command | Purpose |
|---|---|
| `ugc doctor` | check GPU, power profile, disk, environments, weights |
| `ugc setup` | install missing environments and assets |
| `ugc models download [--only ltx\|flux\|whisper]` | model weights |
| `ugc new [NAME] [options]` | wizard / flags → director → `project.yaml` |
| `ugc site URL` | preview what the promo mode reads from a website |
| `ugc plan PROJECT` | storyboard + generation plan + time estimate (nothing is generated) |
| `ugc render PROJECT [--deliver web,tv] [--only s01,s02] [-y]` | build (incremental, resumable) |
| `ugc status PROJECT` | scene states, fixes, timings, outputs |
| `ugc preview PROJECT [--at T] [--open]` | contact sheet / stills |
| `ugc fix PROJECT --at T [--duration D] [--mode ...] [--prompt ...]` | surgical repair |
| `ugc fix PROJECT --scene ID --mode reshoot [--seed N]` | regenerate one shot |
| `ugc fix PROJECT --undo ID` | remove a fix |
| `ugc voice list\|set\|redo\|engine\|file PROJECT ...` | change only the voice-over (never re-renders video) |
| `ugc providers [PROJECT]` | which model/provider makes images, video, voice, music; API keys present; license notes |
| `ugc timeline show\|move\|add-audio\|set-audio\|remove-audio\|music PROJECT ...` | place voice lines, sounds and music by hand |
| `ugc serve [--port 8000]` / `ugc worker` | HTTP API for the web app (+ embedded worker) / standalone worker with Redis |
| `ugc edit PROJECT` | open `project.yaml` in your editor |
| `ugc export PROJECT --format tv\|web\|vertical\|square\|portrait` | extra deliveries |
| `ugc export PROJECT --format cover [--at T]` | cover image (thumbnail) for TikTok / Reels |
| `ugc qa PROJECT\|VIDEO` | quality report |
| `ugc persona create/list` | reusable personas |
| `ugc modes / styles / transitions / icons` | discover options |
| `ugc image PROMPT [--ref IMG]` | one-off image |

---

### 3D reveals and transformations (promo)

- **AI transformation shot:** give a shot both `start_prompt` (e.g. a paper menu) and `end_prompt` (e.g. a phone
  floating in the same place). The video model generates the metamorphosis between the two pinned frames.
- **`reveal: spin`** on a `screen` scene: the device spins in from depth and lands with a light burst and sparkles.
  `reveal: flip` tips it up from below; `rise` (default) slides it in.
- **`kind: devices`:** 2-4 phones fly out of a stack and fan out in 3D, each playing its own live page (e.g. one per
  language) with a label.
- **`theme: dark`** gives graphics scenes (title, screen, devices, features, endcard) a deep, glowing brand-colored
  background; an Arabic endcard mirrors its layout automatically.

### Ready for TikTok / Instagram

9:16 at 1080×1920, -14 LUFS audio, the hook text visible from frame 0 (the thumbnail), captions placed above the
platform UI, and `ugc export PROJECT --format cover` for the cover image. Keep UGC videos 20-30 s and end cards short
(3-4 s): set `target_seconds` accordingly.

## 10. Quality, speed and limits

Measured on this laptop (RTX 4000 Ada 12 GB, "performance" power profile):

| Quality | Shot resolution | One 5 s shot | 20 s video | 60 s video |
|---|---|---|---|---|
| `draft` | 448×768 | ~1.5 min | ~8 min | ~25 min |
| `standard` | 576×1024 | ~3 min | ~15 min | ~45 min |
| `high` | 704×1280 | ~4.5 min | ~22 min | ~65 min |
| `tv` | 1088×1920 / 1920×1088 | ~6 min | ~30 min | ~90 min |

Graphics-only scenes (title, screen, features, endcard, image) render in seconds; a promo with many graphics
scenes is much faster than a 100 % live-action video of the same length. Use `ugc plan` for an estimate.

**Honest limits of the current models**

- Text **inside** AI shots (labels, signs) can come out garbled. Give real product photos, and put text in
  graphics scenes or captions.
- Hands and fast complex motion are the hardest for video models. Use `ugc fix` (interpolate / retake) or simpler
  actions.
- On-camera speech (ugc/influencer) works well in English and French (every line is checked and re-shot if wrong);
  other languages vary more. Narration (faceless/promo) covers 23 languages incl. Arabic, plus Algerian, Egyptian,
  Iraqi and Moroccan dialects, or use your own recording (`voice.file`).
- Each generation is ≤ 5 s. Longer shots are chained automatically; for the best continuity keep shots 3-5 s.

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `CUDA not available` after a driver update | reboot (driver/library version mismatch) |
| Renders slower than the table | `powerprofilesctl set performance`; close other GPU apps |
| `401/403` downloading LTX | accept the license on the LTX-2.5 page; `HF_TOKEN=` in `.env` |
| Voice line sounds wrong | re-render: failing lines are auto-retried; or edit the line text; or set `voice.reference_audio` |
| The person changes between shots | give 2-3 photos (`--face`) or a persona; use `continuity: match` inside one setup |
| Repeated or trailing words in on-camera speech | keep ~12 words per 5 s shot (the director already does) |
| A glitch at second X | `ugc fix PROJECT --at X` |
| Want to start a scene over | `ugc fix PROJECT --scene ID --mode reshoot` |
| Anything else | `ugc render PROJECT -v` for debug logs; `ugc doctor` |
