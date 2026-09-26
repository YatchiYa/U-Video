"""HTTP API: projects, voice/timeline/fix editing, file serving, and real jobs (subprocess worker, SSE progress).

The render test is real (no stubs): a graphics-only project is rendered by the job subprocess with Chromium + ffmpeg.
"""

from __future__ import annotations

import json
import threading
import time

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from ugc_studio import config, jobs

PROJECT = {
    "title": "API test", "mode": "promo", "aspect": "16:9", "quality": "draft", "fps": 25,
    "voice": {"enabled": False}, "music": {"mode": "none"}, "captions": {"enabled": False},
    "brand": {"name": "Acme", "tagline": "Hello", "url": "https://acme.test"},
    "scenes": [{"id": "t1", "kind": "title", "seconds": 2, "headline": "Acme"},
               {"id": "end", "kind": "endcard", "seconds": 2, "headline": "Hello"}],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setenv("UGC_OUTPUTS", str(tmp_path))  # the job subprocess reads it
    monkeypatch.delenv("REDIS_URL", raising=False)
    store = jobs.MemoryStore()
    jobs.set_store(store)
    stop = threading.Event()
    t = threading.Thread(target=jobs.work, kwargs={"stop": stop}, daemon=True)
    t.start()
    from ugc_studio.api import app

    yield TestClient(app)
    stop.set()
    jobs.set_store(None)


def _wait(c, jid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in jobs.TERMINAL:
            return j
        time.sleep(0.5)
    raise TimeoutError(jid)


def test_system_endpoints(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["store"] == "MemoryStore" and h["worker"]
    cat = client.get("/api/catalog").json()
    assert "promo" in [m["id"] for m in cat["modes"]] and "16:9" in cat["aspects"] and "Arabic" in cat["languages"]
    assert {r["kind"] for r in client.get("/api/providers").json()} == {"image", "video", "voice", "music"}


def test_project_lifecycle_and_security(client, tmp_path):
    r = client.post("/api/projects/import", json={"name": "my video!", "project": PROJECT})
    assert r.status_code == 201 and r.json()["id"] == "my_video"
    assert client.post("/api/projects/import", json={"name": "my video", "project": PROJECT}).status_code == 409
    assert [p["id"] for p in client.get("/api/projects").json()] == ["my_video"]
    got = client.get("/api/projects/my_video").json()
    assert got["project"]["title"] == "API test" and [s["id"] for s in got["status"]["scenes"]] == ["t1", "end"]
    # edit through PUT (what the editor does), invalid edits are refused with the reason
    proj = got["project"]
    proj["scenes"][0]["headline"] = "Acme 2"
    assert client.put("/api/projects/my_video", json=proj).status_code == 200
    bad = dict(proj, aspect="7:3")
    r = client.put("/api/projects/my_video", json=bad)
    assert r.status_code == 400 and "aspect" in r.json()["detail"]
    assert client.get("/api/projects/my_video").json()["project"]["scenes"][0]["headline"] == "Acme 2"
    plan = client.get("/api/projects/my_video/plan").json()
    assert plan["items"][-1]["stage"] == "edit"
    # path traversal and bad ids
    assert client.get("/api/projects/my_video/files/../../etc/passwd").status_code == 404
    assert client.get("/api/projects/..%2Fx").status_code in (400, 404)
    assert client.get("/api/projects/nope").status_code == 404
    # graphics scene: a fix is not a render, the API says what to do instead
    r = client.post("/api/projects/my_video/fixes", json={"scene": "t1", "mode": "reshoot"}).json()
    assert r["action"] == "none" and "graphics" in r["message"]
    # delete = move to trash
    assert client.delete("/api/projects/my_video").status_code == 200
    assert client.get("/api/projects").json() == [] and any((tmp_path / "_trash").iterdir())


def test_uploads_are_checked(client):
    r = client.post("/api/uploads", files={"file": ("evil.sh", b"#!/bin/sh", "text/x-sh")})
    assert r.status_code == 400
    r = client.post("/api/uploads", files={"file": ("face.png", b"\x89PNG....", "image/png")})
    assert r.status_code == 200 and r.json()["ref"].endswith("face.png")
    r = client.post("/api/projects", json={"name": "x", "mode": "ugc", "brief": "hello", "face_uploads": ["/etc/passwd"]})
    assert r.status_code == 400 and "upload" in r.json()["detail"]


def test_real_render_job_with_live_events_then_timeline_audio_and_mix(client, tmp_path):
    client.post("/api/projects/import", json={"name": "demo", "project": PROJECT})
    job = client.post("/api/projects/demo/render", json={"deliveries": ["web"], "qa": False}).json()
    assert job["status"] == "queued" and job["queue"] == "gpu"
    # stream the progress (SSE) until the end event
    events = []
    with client.stream("GET", f"/api/jobs/{job['id']}/events") as s:
        for line in s.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if events and events[-1] == "end":
                break
    done = client.get(f"/api/jobs/{job['id']}").json()
    assert done["status"] == "done", done.get("error")
    assert "started" in events and "progress" in events and events[-1] == "end"
    assert abs(done["result"]["total"] - 4.0) < 0.05
    media = client.get("/api/projects/demo/media").json()
    video = next(o for o in media["outputs"] if o["name"].endswith("_web.mp4"))
    r = client.get(video["url"], headers={"Range": "bytes=0-99"})  # the browser player seeks with ranges
    assert r.status_code == 206 and len(r.content) == 100
    assert set(media["thumbnails"]) == {"t1", "end"}
    # add a sound on the timeline, then rebuild only the mix
    wav = tmp_path / "ding.wav"
    sf.write(wav, (0.2 * np.sin(np.arange(24000) / 24000 * 2 * np.pi * 880)).astype(np.float32), 24000)
    r = client.post("/api/projects/demo/timeline/audio", files={"file": ("ding.wav", wav.read_bytes(), "audio/wav")},
                    data={"at": "1.5", "gain_db": "-3"})
    assert r.status_code == 201 and r.json()["id"] == "ding"
    tl = client.get("/api/projects/demo/timeline").json()
    audio = next(t for t in tl["tracks"] if t["id"] == "audio")["clips"]
    assert audio[0]["start"] == 1.5 and audio[0]["gain_db"] == -3
    r = client.patch("/api/projects/demo/timeline/audio/ding", json={"at": 2.0}).json()
    assert next(t for t in r["tracks"] if t["id"] == "audio")["clips"][0]["start"] == 2.0
    mix = _wait(client, client.post("/api/projects/demo/mix").json()["id"])
    assert mix["status"] == "done", mix.get("error")
    cover = _wait(client, client.post("/api/projects/demo/export", json={"format": "cover", "at": 1}).json()["id"])
    assert cover["status"] == "done" and cover["result"]["file"].endswith("cover.jpg")


def test_failures_and_cancel_are_reported(client):
    client.post("/api/projects/import", json={"name": "demo", "project": PROJECT})
    j = _wait(client, client.post("/api/projects/demo/export", json={"format": "tv"}).json()["id"])
    assert j["status"] == "failed" and "render the project first" in j["error"]
    # a queued job can be cancelled before it starts
    jobs.store().push("gpu", "blocker")  # the gpu loop is busy with nothing: fill the queue with an unknown id
    a = client.post("/api/projects/demo/render").json()
    c = client.post(f"/api/jobs/{a['id']}/cancel").json()
    assert c["status"] in ("cancelled", "running", "queued")
    final = _wait(client, a["id"])
    assert final["status"] in ("cancelled", "done")
    assert json.dumps(client.get("/api/jobs", params={"project": "demo"}).json())


def test_gaps_found_by_the_web_app(client, tmp_path):
    from ugc_studio.schema import Style

    assert set(client.get("/api/catalog").json()["styles"]) == set(Style.__args__)
    shot = dict(PROJECT, scenes=PROJECT["scenes"] + [{"id": "s1", "prompt": "a scale of justice", "seconds": 2}])
    client.post("/api/projects/import", json={"name": "gaps", "project": shot})
    folder = tmp_path / "gaps"
    # a reshoot can be undone (the take goes back); with nothing to undo the API says so
    client.post("/api/projects/gaps/fixes", json={"scene": "s1", "mode": "reshoot"})
    assert client.get("/api/projects/gaps").json()["project"]["scenes"][2]["take"] == 1
    r = client.delete("/api/projects/gaps/fixes/s1").json()
    assert r["kind"] == "reshoot" and client.get("/api/projects/gaps").json()["project"]["scenes"][2]["take"] == 0
    assert client.delete("/api/projects/gaps/fixes/s1").json()["removed"] is None
    # timeline sounds: playable url + real file length; duration can be reset to "whole file" with null
    wav = tmp_path / "tick.wav"
    sf.write(wav, np.zeros(12000, np.float32), 24000)
    client.post("/api/projects/gaps/timeline/audio", files={"file": ("tick.wav", wav.read_bytes(), "audio/wav")},
                data={"at": "0.5"})
    clip = client.patch("/api/projects/gaps/timeline/audio/tick", json={"duration": 0.3}).json()["tracks"][3]["clips"][0]
    assert clip["dur"] == 0.3 and clip["url"].startswith("/api/projects/gaps/files/") and clip["file_seconds"] == 0.5
    assert client.get(clip["url"]).status_code == 200
    clip = client.patch("/api/projects/gaps/timeline/audio/tick", json={"duration": None}).json()["tracks"][3]["clips"][0]
    assert clip["dur"] is None and clip["start"] == 0.5  # untouched fields stay
    # the home card shows the main render, never an extra export
    (folder / "out").mkdir(exist_ok=True)
    (folder / "out" / "api_test_web.mp4").write_bytes(b"x")
    (folder / "out" / "export_square.mp4").write_bytes(b"x")
    card = next(p for p in client.get("/api/projects").json() if p["id"] == "gaps")
    assert card["video"].endswith("api_test_web.mp4")


def test_event_stream_resumes_after_last_event_id(client):
    client.post("/api/projects/import", json={"name": "sse", "project": PROJECT})
    jid = client.post("/api/projects/sse/export", json={"format": "tv"}).json()["id"]
    _wait(client, jid)
    def ids(headers):
        with client.stream("GET", f"/api/jobs/{jid}/events", headers=headers) as s:
            return [int(line[4:]) for line in s.iter_lines() if line.startswith("id: ")]
    everything = ids({})
    assert len(everything) >= 3 and ids({"Last-Event-ID": str(everything[1])}) == everything[2:]


def test_persona_images_are_served(client, monkeypatch, tmp_path):
    from ugc_studio import personas

    monkeypatch.setattr(personas, "PERSONAS_DIR", tmp_path / "personas")
    p = personas.Persona(name="nora", description="a 30-year-old woman", images=["ref_00.png"])
    p.folder.mkdir(parents=True)
    (p.folder / "ref_00.png").write_bytes(b"\x89PNG")
    personas.save(p)
    got = client.get("/api/personas").json()[0]
    assert got["image_urls"] == ["/api/personas/nora/files/ref_00.png"]
    assert client.get(got["image_urls"][0]).status_code == 200
    assert client.get("/api/personas/nora/files/persona.yaml").status_code == 404
