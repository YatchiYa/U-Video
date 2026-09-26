"""Kling AI video (Kling 3.0 API): image-to-video with first + last frame, text-to-video, native audio.

Auth: KLING_API_KEY (Bearer), created in the Kling developer console. Docs: kling.ai/document-api (checked
2026-09-25). Base URL: api-singapore.klingai.com (override with KLING_BASE_URL).
"""

from __future__ import annotations

import os
from pathlib import Path

from ugc_studio.providers.base import (VideoBackend, aspect_of, check, client, conform_clip, download, image_b64,
                                       need_key, poll)


def _api() -> str:
    return os.environ.get("KLING_BASE_URL", "").strip() or "https://api-singapore.klingai.com"


def _auth() -> dict:
    return {"Authorization": f"Bearer {need_key('KLING_API_KEY', 'Kling')}"}


class KlingVideo(VideoBackend):
    name = "kling"
    makes_audio = True       # audio: native
    supports_end_frame = True

    def __init__(self, model: str | None = None):
        self.model = model or "kling-3.0"

    def render(self, prompt, out_path, width, height, num_frames, seed, images=None, fps=24):
        out_path = Path(out_path)
        seconds = num_frames / fps
        duration = min(15, max(3, int(-(-seconds // 1))))  # whole seconds, 3-15
        settings = {"resolution": "1080p" if max(width, height) >= 1920 else "720p", "duration": duration,
                    "audio": "native", "multi_shot": False}  # multi_shot defaults to true: one continuous shot
        start = [c for c in images or [] if c.frame_idx == 0]
        end = [c for c in images or [] if c.frame_idx > 0]
        if start:  # aspect ratio follows the first frame
            contents = [{"type": "prompt", "text": prompt[:3000]},
                        {"type": "first_frame", "url": image_b64(start[0].path)}]
            if end:
                contents.append({"type": "last_frame", "url": image_b64(end[0].path)})
            path, body = f"/image-to-video/{self.model}", {"contents": contents, "settings": settings}
        else:
            settings["aspect_ratio"] = aspect_of(width, height, ["16:9", "9:16", "1:1"])
            path, body = f"/text-to-video/{self.model}", {"prompt": prompt[:3000], "settings": settings}
        with client(timeout=120) as c:
            task = check(c.post(_api() + path, headers=_auth(), json=body), "Kling").json()
            if task.get("code", 0) != 0:
                raise RuntimeError(f"Kling: {task.get('message')}")
            tid = task["data"]["id"]

            def fetch() -> dict:
                return check(c.get(f"{_api()}/tasks", params={"task_ids": tid}, headers=_auth()), "Kling").json()["data"][0]

            done = poll(fetch, lambda d: d["status"] == "succeeded",
                        lambda d: (d.get("message") or "failed") if d["status"] == "failed" else None,
                        "Kling", timeout=1200, every=10)
        url = next(o["url"] for o in done["outputs"] if o.get("type") == "video")
        raw = download(url, out_path.with_suffix(".kling.mp4"), provider="Kling")
        conform_clip(raw, out_path, width, height, num_frames, fps)
        raw.unlink(missing_ok=True)
        return out_path
