"""Provider layer: selection (project > .env > local), and every cloud client against a mocked HTTP API.

The mocks follow each provider's documented request/response shapes (see the module docstrings); they check what we
send (URL, auth header, body) and that results are decoded, polled, downloaded and conformed correctly.
"""

from __future__ import annotations

import base64
import io
import json
import textwrap

import httpx
import numpy as np
import pytest
import soundfile as sf
from PIL import Image

import ugc_studio.providers.base as base
from ugc_studio import providers
from ugc_studio.media import ffmpeg, probe
from ugc_studio.providers.base import ImageCondition, ProviderError
from ugc_studio.schema import Project, Voice

KEYS = {"OPENAI_API_KEY": "sk-test", "GEMINI_API_KEY": "gm-test", "ELEVENLABS_API_KEY": "el-test",
        "KLING_API_KEY": "kl-test", "ARK_API_KEY": "ark-test", "HF_TOKEN": "hf_test"}


def _project(**extra) -> Project:
    return Project.model_validate({"title": "t", "scenes": [{"id": "s", "kind": "title"}], **extra})


# ------------------------------------------------------------------ media fixtures (real files, tiny)
@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    png = io.BytesIO()
    Image.new("RGB", (300, 200), (200, 30, 30)).save(png, "PNG")
    ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "3", "-c:v", "libx264", "-pix_fmt",
            "yuv420p", str(d / "silent.mp4")])
    ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24", "-f", "lavfi", "-i", "sine=frequency=440",
            "-t", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(d / "sound.mp4")])
    ffmpeg(["-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100", "-t", "1.5", str(d / "tone.mp3")])
    ffmpeg(["-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100", "-ac", "2", "-t", "4", str(d / "music.mp3")])
    wav = io.BytesIO()
    sf.write(wav, np.zeros(24000, np.float32), 24000, format="WAV")
    frame = d / "frame.png"
    Image.new("RGB", (1024, 576), (10, 120, 200)).save(frame)
    return {"png": png.getvalue(), "silent": (d / "silent.mp4").read_bytes(), "sound": (d / "sound.mp4").read_bytes(),
            "mp3": (d / "tone.mp3").read_bytes(), "music": (d / "music.mp3").read_bytes(), "wav": wav.getvalue(),
            "frame": frame}


@pytest.fixture
def api(monkeypatch):
    """Mock HTTP: register `routes[(method, url_prefix)] = handler(request) -> httpx.Response`; `sent` logs calls."""
    for k, v in KEYS.items():
        monkeypatch.setenv(k, v)
    state = {"routes": {}, "sent": []}

    def handler(req: httpx.Request):
        state["sent"].append(req)
        url = str(req.url)
        for (method, prefix), fn in sorted(state["routes"].items(), key=lambda kv: -len(kv[0][1])):
            if req.method == method and url.startswith(prefix):
                return fn(req)
        return httpx.Response(404, json={"error": f"no mock for {req.method} {url}"})

    monkeypatch.setattr(base, "_TRANSPORT", httpx.MockTransport(handler))
    return state


def _json(req) -> dict:
    return json.loads(req.content)


# ------------------------------------------------------------------ selection
def test_provider_priority_project_then_env_then_local(monkeypatch):
    for k in ("UGC_VIDEO_PROVIDER", "UGC_VIDEO_MODEL", "UGC_IMAGE_PROVIDER", "UGC_VOICE_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    assert providers.choice(_project(), "video").provider == "local"
    monkeypatch.setenv("UGC_VIDEO_PROVIDER", "kling")
    monkeypatch.setenv("UGC_VIDEO_MODEL", "kling-3.0-turbo")
    c = providers.choice(_project(), "video")
    assert (c.provider, c.model, c.source) == ("kling", "kling-3.0-turbo", "env")
    c = providers.choice(_project(providers={"video": "veo"}), "video")
    assert (c.provider, c.source) == ("veo", "project")
    monkeypatch.setenv("UGC_VOICE_PROVIDER", "elevenlabs")
    assert providers.choice(_project(), "voice").provider == "elevenlabs"
    assert providers.choice(_project(voice={"engine": "habibi", "dialect": "ALG"}), "voice").provider == "habibi"


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("KLING_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="KLING_API_KEY"):
        providers.create(_project(providers={"video": "kling"}), "video")


def test_unknown_provider_lists_the_choices():
    with pytest.raises(ProviderError, match="Available"):
        providers.load("video", "runway")


# ------------------------------------------------------------------ OpenAI
def test_openai_image_generation_and_reference_edit(api, media, tmp_path):
    b64 = base64.b64encode(media["png"]).decode()
    api["routes"][("POST", "https://api.openai.com/v1/images/")] = lambda r: httpx.Response(200, json={"data": [{"b64_json": b64}]})
    from ugc_studio.providers.openai import OpenAIImage

    g = OpenAIImage()
    im = g.generate("a lawyer", 1088, 1920, 7, out_path=tmp_path / "a.png")
    req = api["sent"][-1]
    assert str(req.url).endswith("/images/generations") and req.headers["authorization"] == "Bearer sk-test"
    body = _json(req)
    assert body["model"] == "gpt-image-2.5-flare" and body["size"] == "1088x1920"
    assert im.size == (1088, 1920) and (tmp_path / "a.png").is_file()
    g.generate("same lawyer", 1088, 1920, 7, references=[media["frame"], media["frame"]], out_path=tmp_path / "b.png")
    req = api["sent"][-1]
    assert str(req.url).endswith("/images/edits")
    assert req.content.count(b'name="image[]"') == 2 and b'name="input_fidelity"' in req.content


def test_openai_voice_writes_one_wav_per_line(api, media, tmp_path):
    api["routes"][("POST", "https://api.openai.com/v1/audio/speech")] = lambda r: httpx.Response(200, content=media["wav"])
    from ugc_studio.providers.openai import OpenAIVoice

    OpenAIVoice().synthesize([{"id": "a", "text": "Bonjour"}, {"id": "b", "text": "Salut"}], tmp_path, "French",
                             Voice(voice_id="marin"))
    body = _json(api["sent"][0])
    assert body["model"] == "gpt-4o-mini-tts" and body["voice"] == "marin" and "French" in body["instructions"]
    assert (tmp_path / "a.wav").is_file() and (tmp_path / "b.wav").is_file()


# ------------------------------------------------------------------ Gemini
def test_gemini_image_uses_interactions_with_references(api, media, tmp_path):
    b64 = base64.b64encode(media["png"]).decode()
    api["routes"][("POST", "https://generativelanguage.googleapis.com/v1beta/interactions")] = lambda r: httpx.Response(
        200, json={"steps": [{"type": "model_output", "content": [{"type": "image", "data": b64}]}]})
    from ugc_studio.providers.gemini import GeminiImage

    im = GeminiImage().generate("x", 1920, 1088, 1, references=[media["frame"]], out_path=tmp_path / "g.png")
    req = api["sent"][-1]
    body = _json(req)
    assert req.headers["x-goog-api-key"] == "gm-test" and body["model"] == "gemini-3.1-flash-image"
    assert body["response_format"]["aspect_ratio"] == "16:9" and body["input"][1]["type"] == "image"
    assert im.size == (1920, 1088)


def test_veo_first_last_frame_poll_download_and_conform(api, media, tmp_path):
    polls = {"n": 0}

    def op(r):
        polls["n"] += 1
        if polls["n"] < 2:
            return httpx.Response(200, json={"name": "models/veo/operations/42", "done": False})
        return httpx.Response(200, json={"done": True, "response": {"generateVideoResponse": {
            "generatedSamples": [{"video": {"uri": "https://generativelanguage.googleapis.com/v1beta/files/v:download"}}]}}})

    api["routes"][("POST", "https://generativelanguage.googleapis.com/v1beta/models/")] = lambda r: httpx.Response(
        200, json={"name": "models/veo/operations/42"})
    api["routes"][("GET", "https://generativelanguage.googleapis.com/v1beta/models/veo/operations/42")] = op
    api["routes"][("GET", "https://generativelanguage.googleapis.com/v1beta/files/")] = lambda r: httpx.Response(200, content=media["sound"])
    from ugc_studio.providers.gemini import VeoVideo

    conds = [ImageCondition(str(media["frame"]), 0), ImageCondition(str(media["frame"]), 10_000)]
    out = VeoVideo().render("a lawyer walks", tmp_path / "v.mp4", 1920, 1088, 121, 5, conds, 25)
    body = _json(api["sent"][0])
    inst, par = body["instances"][0], body["parameters"]
    assert str(api["sent"][0].url).endswith("veo-3.1-generate-preview:predictLongRunning")
    assert "image" in inst and "lastFrame" in inst
    assert par["durationSeconds"] == "8" and par["resolution"] == "1080p" and par["personGeneration"] == "allow_adult"
    assert api["sent"][-1].headers["x-goog-api-key"] == "gm-test"  # the video download needs the key too
    info = probe(out)
    assert (info["width"], info["height"], info["frames"], round(info["fps"])) == (1920, 1088, 121, 25) and info["audio"]


def test_gemini_voice_decodes_audio_block(api, media, tmp_path):
    b64 = base64.b64encode(media["wav"]).decode()
    api["routes"][("POST", "https://generativelanguage.googleapis.com/v1beta/interactions")] = lambda r: httpx.Response(
        200, json={"steps": [{"type": "model_output", "content": [{"type": "audio", "data": b64}]}]})
    from ugc_studio.providers.gemini import GeminiVoice

    GeminiVoice().synthesize([{"id": "a", "text": "مرحبا"}], tmp_path, "Arabic", Voice(voice_id="Kore"))
    body = _json(api["sent"][0])
    assert body["generation_config"]["speech_config"] == [{"voice": "Kore"}]
    assert sf.info(str(tmp_path / "a.wav")).samplerate == 24000


# ------------------------------------------------------------------ ElevenLabs
def test_elevenlabs_voice_needs_a_voice_id(api, tmp_path, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    from ugc_studio.providers.elevenlabs import ElevenLabsVoice

    with pytest.raises(ProviderError, match="voice_id"):
        ElevenLabsVoice().synthesize([{"id": "a", "text": "x"}], tmp_path, "French", Voice())


def test_elevenlabs_voice_and_music(api, media, tmp_path):
    api["routes"][("POST", "https://api.elevenlabs.io/v1/text-to-speech/")] = lambda r: httpx.Response(200, content=media["mp3"])
    api["routes"][("POST", "https://api.elevenlabs.io/v1/music")] = lambda r: httpx.Response(200, content=media["music"])
    from ugc_studio.providers.elevenlabs import ElevenLabsMusic, ElevenLabsVoice

    ElevenLabsVoice().synthesize([{"id": "a", "text": "Bonjour", "seed": 7}], tmp_path, "French", Voice(voice_id="VOICE1"))
    req = api["sent"][-1]
    assert "/text-to-speech/VOICE1" in str(req.url) and req.url.params["output_format"] == "mp3_44100_128"
    assert req.headers["xi-api-key"] == "el-test" and _json(req)["model_id"] == "eleven_multilingual_v2"
    assert sf.info(str(tmp_path / "a.wav")).channels == 1
    ElevenLabsMusic().generate("warm piano", 31.2, 100, 1, 2, tmp_path)
    body = _json(api["sent"][-1])
    assert body["music_length_ms"] == 31200 and body["force_instrumental"] is True and body["model_id"] == "music_v2"
    assert sf.info(str(tmp_path / "cand1.wav")).channels == 2


# ------------------------------------------------------------------ Kling / Seedance
def test_kling_image_to_video_with_last_frame(api, media, tmp_path):
    status = iter(["submitted", "processing", "succeeded"])

    def tasks(r):
        s = next(status)
        return httpx.Response(200, json={"data": [{"id": "t1", "status": s, "outputs": [
            {"type": "video", "url": "https://cdn.kling.test/v.mp4"}] if s == "succeeded" else []}]})

    api["routes"][("POST", "https://api-singapore.klingai.com/image-to-video/")] = lambda r: httpx.Response(
        200, json={"code": 0, "data": {"id": "t1", "status": "submitted"}})
    api["routes"][("GET", "https://api-singapore.klingai.com/tasks")] = tasks
    api["routes"][("GET", "https://cdn.kling.test/")] = lambda r: httpx.Response(200, content=media["silent"])
    from ugc_studio.providers.kling import KlingVideo

    conds = [ImageCondition(str(media["frame"]), 0), ImageCondition(str(media["frame"]), 120)]
    out = KlingVideo().render("scan the QR", tmp_path / "k.mp4", 1024, 576, 97, 3, conds, 24)
    req = api["sent"][0]
    body = _json(req)
    assert str(req.url).endswith("/image-to-video/kling-3.0") and req.headers["authorization"] == "Bearer kl-test"
    assert [c["type"] for c in body["contents"]] == ["prompt", "first_frame", "last_frame"]
    assert body["settings"]["multi_shot"] is False and body["settings"]["duration"] == 5
    info = probe(out)
    assert (info["width"], info["height"], info["frames"]) == (1024, 576, 97)
    assert info["audio"]  # silent provider clip gets a silent track the mixer can rely on


def test_seedance_roles_ratio_poll(api, media, tmp_path):
    seq = iter([{"status": "queued"}, {"status": "running"},
                {"status": "succeeded", "content": {"video_url": "https://cdn.ark.test/v.mp4"}}])
    api["routes"][("POST", "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks")] = \
        lambda r: httpx.Response(200, json={"id": "cgt-1"})
    api["routes"][("GET", "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks/cgt-1")] = \
        lambda r: httpx.Response(200, json=next(seq))
    api["routes"][("GET", "https://cdn.ark.test/")] = lambda r: httpx.Response(200, content=media["sound"])
    from ugc_studio.providers.seedance import SeedanceVideo

    conds = [ImageCondition(str(media["frame"]), 0), ImageCondition(str(media["frame"]), 120)]
    out = SeedanceVideo().render("files turn into light", tmp_path / "s.mp4", 1920, 1088, 125, 11, conds, 25)
    body = _json(api["sent"][0])
    assert [c.get("role") for c in body["content"]] == [None, "first_frame", "last_frame"]
    assert body["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert body["ratio"] == "adaptive" and body["resolution"] == "1080p" and body["duration"] == 5
    assert probe(out)["frames"] == 125


def test_seedance_failure_is_reported(api, media, tmp_path):
    api["routes"][("POST", "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks")] = \
        lambda r: httpx.Response(200, json={"id": "cgt-2"})
    api["routes"][("GET", "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks/cgt-2")] = \
        lambda r: httpx.Response(200, json={"status": "failed", "error": {"message": "content policy"}})
    from ugc_studio.providers.seedance import SeedanceVideo

    with pytest.raises(ProviderError, match="content policy"):
        SeedanceVideo().render("x", tmp_path / "f.mp4", 1024, 576, 97, 1, [], 24)


def test_http_errors_carry_the_provider_message(api, tmp_path):
    api["routes"][("POST", "https://api.openai.com/v1/images/")] = lambda r: httpx.Response(
        401, json={"error": {"message": "Incorrect API key"}})
    from ugc_studio.providers.openai import OpenAIImage

    with pytest.raises(ProviderError, match="401.*Incorrect API key"):
        OpenAIImage().generate("x", 512, 512, 1)


# ------------------------------------------------------------------ Hugging Face
def test_huggingface_hf_inference_returns_image_bytes(api, media, tmp_path):
    api["routes"][("POST", "https://router.huggingface.co/hf-inference/models/")] = lambda r: httpx.Response(200, content=media["png"])
    from ugc_studio.providers.huggingface import HFImage

    im = HFImage().generate("a scale of justice", 1024, 576, 3, out_path=tmp_path / "h.png")
    body = _json(api["sent"][0])
    assert body["parameters"] == {"width": 1024, "height": 576, "seed": 3} and im.size == (1024, 576)


# ------------------------------------------------------------------ engine integration
PROMO = textwrap.dedent("""
    title: Cloud video
    mode: faceless
    aspect: "16:9"
    quality: draft
    fps: 24
    music: {mode: none}
    voice: {enabled: false}
    captions: {enabled: false}
    providers: {video: kling}
    scenes:
      - {id: a, prompt: paper files dissolve into light, seconds: 4}
      - {id: b, prompt: a laptop glows, seconds: 3, transition: {type: dissolve, seconds: 0.4}}
""")


def test_a_project_renders_its_shots_with_the_cloud_provider(tmp_path, calls, api, media):
    from conftest import write_project
    from ugc_studio.engine import Studio

    def create(r):
        return httpx.Response(200, json={"code": 0, "data": {"id": f"t{len(api['sent'])}", "status": "submitted"}})

    api["routes"][("POST", "https://api-singapore.klingai.com/image-to-video/")] = create
    api["routes"][("GET", "https://api-singapore.klingai.com/tasks")] = lambda r: httpx.Response(200, json={"data": [
        {"id": "t", "status": "succeeded", "outputs": [{"type": "video", "url": "https://cdn.kling.test/v.mp4"}]}]})
    api["routes"][("GET", "https://cdn.kling.test/")] = lambda r: httpx.Response(200, content=media["sound"])
    folder = write_project(tmp_path / "p", PROMO)
    res = Studio(folder).build()
    kling_calls = [r for r in api["sent"] if "image-to-video" in str(r.url)]
    assert len(kling_calls) == 2 and calls.shots == []  # the local LTX stub was never used
    assert probe(res.deliveries["web"])["frames"] == round(res.timeline.total * 24)


def test_dialogue_with_a_silent_video_provider_fails_before_generating(tmp_path, calls, monkeypatch):
    from conftest import write_project
    from ugc_studio.engine import Studio
    from ugc_studio.providers.kling import KlingVideo

    monkeypatch.setattr(KlingVideo, "makes_audio", False)
    folder = write_project(tmp_path / "p", PROMO.replace("seconds: 4}", "seconds: 4, dialogue: Hello there}")
                           .replace("mode: faceless", "mode: ugc"))
    with pytest.raises(ValueError, match="makes no speech"):
        Studio(folder).build()
    assert calls.keyframes == []
