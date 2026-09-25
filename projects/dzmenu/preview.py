"""Render still previews of the composition at given times (overlays composited on b-roll keyframes)."""

import asyncio
import io
import json
import sys
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

HERE = Path(__file__).parent
TL = json.loads((HERE / "timeline.json").read_text())


def scene_at(t):
    for sid, s in TL["scenes"].items():
        if s["start"] <= t < s["start"] + s["dur"]:
            return sid, s
    return None, None


async def main(times, out):
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--allow-file-access-from-files"])
        page = await b.new_page(viewport={"width": 1920, "height": 1080})
        msgs = []
        page.on("console", lambda m: msgs.append(m.text))
        page.on("pageerror", lambda e: msgs.append("PAGEERROR " + str(e)))
        await page.goto((HERE / "mg" / "index.html").as_uri())
        await page.evaluate("window.compReady")
        tiles = []
        for t in times:
            await page.evaluate(f"window.seek({t})")
            png = await page.screenshot(type="png", omit_background=True)
            ov = Image.open(io.BytesIO(png)).convert("RGBA")
            sid, s = scene_at(t)
            if s and s["kind"] == "ai":
                bg = Image.open(HERE / "broll" / "keyframes" / f"{s['clip']}.png").convert("RGBA").crop((0, 4, 1920, 1084))
            else:
                bg = Image.new("RGBA", (1920, 1080), (0, 0, 0, 255))
            tiles.append(Image.alpha_composite(bg, ov).convert("RGB"))
        await b.close()
        for m in msgs:
            print("console:", m)
    cols = 2
    w, h = 960, 540
    sheet = Image.new("RGB", (cols * w, -(-len(tiles) // cols) * h))
    for i, im in enumerate(tiles):
        sheet.paste(im.resize((w, h)), ((i % cols) * w, (i // cols) * h))
    sheet.save(out)


if __name__ == "__main__":
    asyncio.run(main([float(x) for x in sys.argv[2:]], sys.argv[1]))
