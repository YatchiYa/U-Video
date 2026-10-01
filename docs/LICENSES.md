# Licenses of the models and tools UGC Studio uses

Checked on **2026-09-26** from primary sources (model cards, LICENSE files, official license pages). This is a
factual summary, **not legal advice**. Licenses change: re-check before commercial or client work. UGC Studio's own
code does not include any model weights: they are downloaded by each user, who accepts each license (LTX-2.5 is a
gated model on Hugging Face).

## Summary for commercial video work (ads, client work, TV)

| Component | License | Commercial use | What you must do |
|---|---|---|---|
| **LTX-2.5** video (default local video model) and the LTX-2 code | [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) + [Acceptable Use Policy](https://static.lightricks.com/legal/ltx-acceptable-use-policy.pdf) | **Free if your company (with affiliates) makes under $10M revenue per year**; above that, a paid license from Lightricks | **Disclose that published videos are AI-generated.** No deepfakes or fake personas presented as real people without consent; clear any real likeness, brand or location. Don't remove watermark or provenance features. A product that competes with Lightricks' commercial products needs their written OK. When redistributing LTX code or weights, ship the license and pass its use restrictions on. |
| **FLUX.2 klein 4B** images | [Apache-2.0](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B) | Yes | Keep the notice. **The 9B variant is non-commercial**: UGC Studio refuses it unless `UGC_ALLOW_NONCOMMERCIAL=1`. |
| **Qwen3-4B** (script director), **Qwen3-TTS** (narration) | [Apache-2.0](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base) | Yes | Only clone voices you have the rights to. |
| **Whisper large-v3-turbo** (speech check) | [MIT](https://huggingface.co/openai/whisper-large-v3-turbo) | Yes | — |
| **Qwen3.5-9B** (script writer), **Qwen3-ASR-1.7B** (Arabic speech check) | [Apache-2.0](https://huggingface.co/Qwen/Qwen3.5-9B) | Yes | — |
| **Qwen-Image-Edit-2511** (identity keyframes) + **Lightning LoRA** (lightx2v) + unsloth GGUF | [Apache-2.0](https://huggingface.co/Qwen/Qwen-Image-Edit-2511) | Yes | — |
| **Qwen-Image-2.1** (best keyframes, optional: `ugc models download --only qwen21`) | Qwen research license | **No** | Personal and research use only. For client work, set `UGC_KEYFRAME_EDIT=qwen-edit` and `UGC_KEYFRAME_T2I=zimage`, or don't install it. |
| **Z-Image Turbo** (optional keyframes) | [Apache-2.0](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo) | Yes | — |
| **Chatterbox** Multilingual v3 (Arabic and 22 other languages) | [MIT](https://github.com/resemble-ai/chatterbox) | Yes | Outputs carry an inaudible Perth watermark: keep it. |
| **Higgs TTS 3** (optional voice: `voice.engine: higgs`) | [Boson Higgs TTS 3 Research and Non-Commercial License](https://huggingface.co/bosonai/higgs-tts-3-4b) | **No** (except its creator grant) | Personal use. Its *creator use grant* allows monetized videos and social content **with attribution**: "This audio was created with Boson AI's Higgs Audio — https://www.boson.ai/higgs-audio". No ads or client work without a commercial license from Boson AI. |
| **Habibi-TTS** (Arabic dialects) | [Card](https://huggingface.co/SWivid/Habibi-TTS): ALG/EGY/IRQ/MAR/MSA "Apache-2.0"; Unified/SAU/UAE CC-BY-NC-SA (never loaded by UGC Studio) | **Uncertain** | The Specialized models are fine-tuned from the F5-TTS base, which is [CC-BY-NC](https://github.com/SWivid/F5-TTS#license). The maintainers haven't answered [the commercial-use question](https://github.com/SWivid/Habibi-TTS/issues/10). UGC Studio warns on every Habibi run. **For client work, use Chatterbox or a cloud voice, or get written confirmation from the authors.** UGC Studio never uses the Unified checkpoint. |
| **ACE-Step 1.5** music (turbo and XL) | [MIT](https://github.com/ace-step/ACE-Step-1.5) | Yes | Avoid prompts that imitate a protected artist or style. |
| **Stable Audio 3 Medium** (optional music) | [Stability AI Community License](https://stability.ai/license) + Gemma Terms (T5Gemma text encoder) | **Yes, under $1M annual revenue** | Gated on Hugging Face. Above $1M revenue, an Enterprise license from Stability AI. |
| **Audiobox Aesthetics** (music judge) | CC-BY-4.0 | Yes | Used only to rate candidates. |
| **CATT** Arabic diacritization | [Apache-2.0](https://github.com/abjadai/catt) | Yes | — |
| **wav2vec2-xlsr-53-espeak** (phoneme check) | [Apache-2.0](https://huggingface.co/facebook/wav2vec2-xlsr-53-espeak-cv-ft) | Yes | — |
| **CLIP ViT-L/14**, **DINOv2** (image judges) | MIT, [Apache-2.0](https://huggingface.co/facebook/dinov2-base) | Yes | Used only for internal quality checks. |
| **SQUIM objective** (voice take quality) | CC-BY-4.0 | Yes | Attribution. (The SQUIM *subjective* MOS model is CC-BY-NC, so UGC Studio does not use it.) |
| **GSAP** (motion graphics) | [GSAP Standard "No Charge" License](https://gsap.com/standard-license/) | Yes | Not OSI-licensed: don't use it to build a no-code visual *animation builder* that competes with Webflow. UGC Studio's code-driven graphics are fine. |
| **lucide-static** icons, **Fontsource** fonts | ISC, OFL-1.1 | Yes | Keep the notices; fonts can't be sold standalone. |
| **Playwright** + Chromium | Apache-2.0, BSD-3 | Yes | — |
| **espeak-ng**, **phonemizer** | GPL-3.0 | Yes, for making videos | Only matters when **redistributing** a bundle (see below). |
| **FFmpeg** (imageio-ffmpeg static build, PyAV wheels with x264/x265) | GPL-3.0 builds | Yes, for making videos | Encoded videos are not covered by the GPL. Redistribution: see below. H.264/H.265 patent licensing is a separate topic. |

## Cloud providers

When you switch a capability to a cloud provider, that provider's terms govern the model and its outputs. This covers Google Veo and Gemini, Kling, Seedance / BytePlus, OpenAI, ElevenLabs and Hugging Face Inference Providers. Several of them require AI disclosure or keep provenance marks (SynthID, C2PA). UGC Studio doesn't remove any.

## Redistribution and GPL

- **This repository:** the source code declares its dependencies and downloads them at install time. It doesn't bundle GPL binaries or model weights. That keeps it compatible with a permissive license for your own code.
- **A Docker image or frozen app you publish:** it contains GPL components (espeak-ng through phonemizer, FFmpeg builds with x264/x265). Distribute that bundle under GPL-3-compatible terms and offer the corresponding source. Keep model weights out of the image, as the provided Dockerfile does: weights stay in a volume that each user fills after accepting the licenses.
- **Running it as a hosted service:** plain GPL-3 (not AGPL) imposes nothing on server-side use.

## Practical checklist before publishing client ads

1. Check your company's revenue against the LTX-2.5 $10M threshold.
2. Add an "AI-generated" disclosure to the ad (the LTX license requires it, and many platforms and regulators do too, e.g. the EU AI Act, art. 50).
3. Personas and avatars: show them as fictional presenters, not real customers giving a testimonial. Get signed releases for any real person, likeness or voice you use.
4. Arabic dialect narration: use Chatterbox (MSA) or a cloud voice until Habibi's commercial status is confirmed.
5. Real brands, logos, places: have the rights. UGC Studio's prompts already ask for unbranded devices.

Qwen-Image-2.1 and Higgs TTS 3 are the non-commercial models UGC Studio can use, and only when you install them and select them yourself. Not used, because their weights are non-commercial: OmniVoice (CC-BY-NC), FLUX.2 dev and klein 9B, SQUIM subjective MOS, the Unified, SAU and UAE Habibi checkpoints, and the MMS alignment models.
