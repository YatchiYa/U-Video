"""ByteDance Seedance video via BytePlus ModelArk (international) or Volcengine Ark (China).

Auth: ARK_API_KEY (Bearer). Base URL: ARK_BASE_URL, default https://ark.ap-southeast.bytepluses.com/api/v3
(China: https://ark.cn-beijing.volces.com/api/v3). Docs: docs.byteplus.com/en/docs/ModelArk/1520757 (checked
2026-09-25). First + last frame, native audio (Seedance 1.5 pro and 2.x).
"""

from __future__ import annotations

import os
from pathlib import Path

from ugc_studio.providers.base import (VideoBackend, aspect_of, check, client, conform_clip, download,
                                       image_data_uri, need_key, poll)


def _api() -> str:
    return os.environ.get("ARK_BASE_URL", "").strip() or "https://ark.ap-southeast.bytepluses.com/api/v3"


def _auth() -> dict:
    return {"Authorization": f"Bearer {need_key('ARK_API_KEY', 'Seedance')}"}


class SeedanceVideo(VideoBackend):
    name = "seedance"
    makes_audio = True
    supports_end_frame = True

    def __init__(self, model: str | None = None):
        self.model = model or "dreamina-seedance-2-5-260628"

    def render(self, prompt, out_path, width, height, num_frames, seed, images=None, fps=24):
        out_path = Path(out_path)
        seconds = num_frames / fps
        start = [c for c in images or [] if c.frame_idx == 0]
        end = [c for c in images or [] if c.frame_idx > 0]
        content = [{"type": "text", "text": prompt}]
        if start:
            content.append({"type": "image_url", "image_url": {"url": image_data_uri(start[0].path)},
                            "role": "first_frame"})
            if end:  # both roles are required when two frames are given
                content.append({"type": "image_url", "image_url": {"url": image_data_uri(end[0].path)},
                                "role": "last_frame"})
        body = {"model": self.model, "content": content,
                "resolution": "1080p" if max(width, height) >= 1920 else "720p",
                # image-to-video keeps the frame's own ratio ("adaptive" is the only value 2.5 accepts there)
                "ratio": "adaptive" if start else aspect_of(width, height, ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9"]),
                "duration": max(4, int(-(-seconds // 1))), "generate_audio": True, "watermark": False,
                "seed": seed % 2**31}
        with client(timeout=120) as c:
            tid = check(c.post(f"{_api()}/contents/generations/tasks", headers=_auth(), json=body), "Seedance").json()["id"]
            done = poll(lambda: check(c.get(f"{_api()}/contents/generations/tasks/{tid}", headers=_auth()),
                                      "Seedance").json(),
                        lambda d: d.get("status") == "succeeded",
                        lambda d: str((d.get("error") or {}).get("message") or d["status"])
                        if d.get("status") in ("failed", "cancelled", "expired") else None,
                        "Seedance", timeout=1800, every=10)
        raw = download(done["content"]["video_url"], out_path.with_suffix(".seedance.mp4"), provider="Seedance")
        conform_clip(raw, out_path, width, height, num_frames, fps)
        raw.unlink(missing_ok=True)
        return out_path
