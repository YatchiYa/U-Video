"""Manual timeline edits (edit.voice / edit.audio / edit.music): placement math, validation, and the real mix."""

from __future__ import annotations

import textwrap

import numpy as np
import pytest
import soundfile as sf

from ugc_studio import service, timeline
from ugc_studio.media import ffmpeg
from ugc_studio.schema import Project
from ugc_studio.timeline import VoiceLine


def _proj(**edit) -> Project:
    return Project.model_validate({
        "title": "t", "mode": "promo", "fps": 25, "voice": {"tempo": 1.0},
        "scenes": [{"id": "a", "kind": "title", "seconds": 4, "voiceover": "one"},
                   {"id": "b", "kind": "title", "seconds": 4, "voiceover": "two"},
                   {"id": "c", "kind": "title", "seconds": 3}],
        "edit": edit})


VO = {"a": VoiceLine("a.wav", 0.1, 2.1), "b": VoiceLine("b.wav", 0.2, 3.2)}


def test_pinned_line_lands_exactly_and_does_not_stretch_its_scene():
    auto = timeline.build(_proj(), VO)
    pinned = timeline.build(_proj(voice={"b": {"at": 7.5, "gain_db": -3}}), VO)
    b = next(s for s in pinned.slots if s.id == "b")
    assert b.vo_manual and b.vo_gain_db == -3
    assert b.vo_at + 0.2 == pytest.approx(7.5)          # first word at 7.5 s
    assert b.dur == 4                                   # scene keeps its own length (no voice-driven growth)
    assert next(s for s in auto.slots if s.id == "b").vo_at != b.vo_at


def test_line_pinned_past_the_end_is_refused():
    with pytest.raises(ValueError, match="after the end of the video"):
        timeline.build(_proj(voice={"a": {"at": 10.0}}), VO)


def test_pin_on_a_scene_without_narration_is_refused():
    with pytest.raises(ValueError, match="no voice-over line"):
        timeline.build(_proj(voice={"c": {"at": 1.0}}), VO)


def test_overlapping_lines_are_reported():
    tl = timeline.build(_proj(voice={"b": {"at": 1.0}}), VO)
    assert any("overlaps" in w for s in tl.slots for w in s.warnings)


def test_tracks_view_has_every_track():
    tl = timeline.build(_proj(voice={"b": {"at": 6.0}}), VO)
    v = timeline.tracks(_proj(voice={"b": {"at": 6.0}}), tl, VO)
    ids = [t["id"] for t in v["tracks"]]
    assert ids == ["video", "voice", "music", "audio"]
    voice = v["tracks"][1]["clips"]
    assert [c["id"] for c in voice] == ["a", "b"] and voice[1]["manual"] and voice[1]["start"] == pytest.approx(6.0)
    assert [c["id"] for c in v["tracks"][0]["clips"]] == ["a", "b", "c"]


# ------------------------------------------------------------------ service + real mix
def _tone(path, freq, seconds, rate=48000, stereo=False):
    t = np.arange(int(seconds * rate)) / rate
    y = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.stack([y, y], 1) if stereo else y, rate)
    return path


def _band_energy(y, rate, freq, t0, t1):
    seg = y[int(t0 * rate):int(t1 * rate)]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    f = np.fft.rfftfreq(len(seg), 1 / rate)
    return spec[(f > freq - 40) & (f < freq + 40)].sum() / (spec.sum() + 1e-9)


PROMO = textwrap.dedent("""
    title: Mix
    mode: promo
    aspect: "16:9"
    quality: draft
    fps: 25
    voice: {enabled: false}
    captions: {enabled: false}
    music: {mode: file, file: music.wav, volume: 1.0}
    scenes:
      - {id: t1, kind: title, seconds: 3, headline: One}
      - {id: t2, kind: title, seconds: 3, headline: Two}
""")


def test_placed_sound_and_music_are_heard_exactly_where_placed(tmp_path, calls):
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "project.yaml").write_text(PROMO)
    _tone(folder / "music.wav", 1500, 10, stereo=True)
    beep = _tone(tmp_path / "beep.wav", 3000, 1.0)
    clip = service.add_audio(folder, beep, at=1.0, fade_in=0.0)
    assert (folder / "media" / "beep.wav").is_file() and clip.id == "beep"
    assert service.add_audio(folder, beep, at=4.0).id == "beep_2"  # ids stay unique
    service.set_music(folder, start=2.0, fade_in=0.0)
    from ugc_studio.engine import Studio

    res = Studio(folder).build()
    wav = tmp_path / "mix.wav"
    ffmpeg(["-i", str(res.master), "-vn", "-ac", "1", "-ar", "48000", str(wav)])
    y, rate = sf.read(wav)
    assert _band_energy(y, rate, 3000, 0.1, 0.9) < 0.01   # before the beep
    assert _band_energy(y, rate, 3000, 1.1, 1.9) > 0.3    # beep at 1.0-2.0 s
    assert _band_energy(y, rate, 1500, 0.2, 1.8) < 0.01   # music not yet
    assert _band_energy(y, rate, 1500, 2.3, 3.8) > 0.3    # music from 2.0 s
    view = service.timeline_view(folder)
    assert [c["id"] for c in view["tracks"][3]["clips"]] == ["beep", "beep_2"]


def test_invalid_move_leaves_the_project_untouched(tmp_path, calls, monkeypatch):
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "project.yaml").write_text(PROMO.replace("headline: One}", "headline: One, voiceover: hello}"))
    _tone(folder / "music.wav", 1500, 10, stereo=True)
    monkeypatch.setattr(service, "current_voice", lambda st: {"t1": VoiceLine("x.wav", 0.1, 2.0)})
    before = (folder / "project.yaml").read_text()
    with pytest.raises(service.ServiceError, match="after the end"):
        service.move_voice(folder, "t1", 5.5)
    assert (folder / "project.yaml").read_text() == before
    service.move_voice(folder, "t1", 3.2)
    assert service.load(folder).edit.voice["t1"].at == 3.2
    service.move_voice(folder, "t1", None)
    assert "t1" not in service.load(folder).edit.voice
