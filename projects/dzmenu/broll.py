"""AI live-action shots for the DZ-MeNU TV spot: FLUX.2 keyframe -> LTX-2.5 image-to-video (1920x1088, 25 fps).

Usage: python broll.py keyframes | render [shot ids...]
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
KF_DIR, CLIP_DIR = HERE / "broll" / "keyframes", HERE / "broll" / "clips"
W, H, FPS, FRAMES = 1920, 1088, 25, 121

LOOK = (
    "Premium TV commercial cinematography, shot on a cinema camera with a 35mm lens, shallow depth of field, "
    "natural warm color grade, crisp detail, realistic skin texture, no text, no logos, no watermark."
)

SHOTS = {
    "a_paper": dict(
        keyframe=(
            "Close-up of a printed café menu card in a clear plastic sleeve lying on a small white marble café table, "
            "the sleeve scratched and stained with coffee rings, a few printed prices crossed out with blue ballpoint "
            "pen and rewritten by hand, a small glass of espresso beside it, warm morning sunlight, busy modern café "
            "softly blurred in the background"
        ),
        video=(
            "Close-up, slow dolly-in on a printed café menu card in a scratched, coffee-stained plastic sleeve lying on a "
            "small white marble table in a café in Algiers. Several prices are crossed out with blue pen and rewritten "
            "by hand. A customer's hand rests on the table next to the menu, fingers drumming impatiently. Steam rises "
            "gently from the espresso. Warm morning sunlight, busy café softly blurred in the background. Sound of café "
            "chatter, cups clinking and fingers tapping on marble."
        ),
    ),
    "a_paper2": dict(
        keyframe="",  # reuses a_paper's keyframe
        video=(
            "Close-up, very slow smooth dolly-in on a printed café menu card in a scratched, coffee-stained plastic "
            "sleeve lying still on a small white marble table in a café in Algiers. Several prices are crossed out "
            "with blue pen and rewritten by hand. The menu does not move. Steam rises gently from the espresso glass. "
            "In the softly blurred background, customers wait and a waiter hurries past. Warm morning sunlight. "
            "Sound of café chatter and cups clinking."
        ),
    ),
    "b_terrace": dict(
        keyframe=(
            "Wide shot of a crowded café terrace in Algiers in the morning, white colonial buildings with blue "
            "shutters behind, a waiter in a white shirt and black apron carrying a stack of paper menus between busy "
            "tables, customers waiting, warm golden light"
        ),
        video=(
            "A crowded café terrace in Algiers in the morning, white colonial buildings with blue shutters behind. "
            "A waiter in a white shirt and black apron hurries between the busy tables carrying a stack of paper menus "
            "while customers wait and look around impatiently. Smooth tracking shot following the waiter, warm golden "
            "light. Lively street and café ambience."
        ),
    ),
    "d_scan": dict(
        keyframe=(
            "Side view medium close-up of a single young woman with long dark hair sitting alone at a wooden table in a "
            "stylish modern café in Algeria, holding her smartphone flat above a small white QR code table stand to scan "
            "it, we see the back of the phone only, the screen is not visible, soft window light, plants and warm wood "
            "interior"
        ),
        video=(
            "Side view medium close-up of a young woman with long dark hair sitting alone at a wooden table in a stylish "
            "modern café in Algeria. She holds her smartphone flat above a small white QR code table stand and scans it; "
            "only the back of the phone is visible. She lowers the phone slightly and smiles, pleased. Soft window light, "
            "gentle slow push-in. Quiet café ambience."
        ),
    ),
    "g_owner": dict(
        keyframe=(
            "A proud Algerian café owner in his forties with a short dark beard and a navy polo shirt stands behind "
            "the counter of his traditional café, looking down and holding his smartphone flat with both hands directly "
            "above a printed paper menu lying on the counter to take a photo of it, espresso machine and trays of "
            "pastries behind him, warm light"
        ),
        video=(
            "A proud Algerian café owner in his forties with a short dark beard and a navy polo shirt stands behind "
            "the counter of his traditional café, holding his smartphone flat above the printed paper menu lying on the "
            "counter and taking a photo of it, then he looks up at the camera and nods with a confident smile. Espresso machine and pastries behind him, warm "
            "light, slow push-in. The espresso machine hisses softly."
        ),
    ),
    "j_family": dict(
        keyframe=(
            "A joyful Algerian family of four sharing dinner in a warm, lively restaurant in the evening, grilled "
            "dishes, salads and mint tea on the table, the parents and two children laughing together, warm tungsten "
            "light, bokeh lights in the background"
        ),
        video=(
            "A joyful Algerian family of four shares dinner in a warm, lively restaurant in the evening, grilled "
            "dishes, salads and mint tea on the table. They laugh together and pass a plate across the table. Slow "
            "cinematic lateral dolly move, warm tungsten light, bokeh lights in the background. Warm restaurant "
            "ambience and soft laughter."
        ),
    ),
}


def keyframes(ids: list[str]) -> None:
    from ugc_studio.keyframes import KeyframeGenerator

    KF_DIR.mkdir(parents=True, exist_ok=True)
    g = KeyframeGenerator()
    try:
        for i, sid in enumerate(ids):
            out = KF_DIR / f"{sid}.png"
            if out.exists():
                continue
            g.generate(f"{SHOTS[sid]['keyframe']}. {LOOK}", W, H, seed=300 + list(SHOTS).index(sid), out_path=out)
            logging.info("keyframe %s", sid)
    finally:
        g.close()


def render(ids: list[str]) -> None:
    from ugc_studio.render import ImageCondition, ShotRenderer

    CLIP_DIR.mkdir(parents=True, exist_ok=True)
    r = ShotRenderer()
    try:
        for i, sid in enumerate(ids):
            out = CLIP_DIR / f"{sid}.mp4"
            if out.exists():
                continue
            t0 = time.time()
            r.render(
                f"{SHOTS[sid]['video']} {LOOK}",
                out,
                W,
                H,
                FRAMES,
                seed=200 + list(SHOTS).index(sid),
                images=[ImageCondition(str(KF_DIR / f"{sid.rstrip('0123456789') if sid.endswith('2') else sid}.png"))],
                fps=FPS,
            )
            (CLIP_DIR / f"{sid}.json").write_text(json.dumps({"seconds_to_render": round(time.time() - t0, 1)}))
    finally:
        r.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    cmd, ids = sys.argv[1], sys.argv[2:] or list(SHOTS)
    {"keyframes": keyframes, "render": render}[cmd](ids)
