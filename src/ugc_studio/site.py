"""Website intelligence for promo mode: content, brand identity, screenshots and frame-exact scroll recordings."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/18.0 Mobile/15E148 Safari/604.1")

EXTRACT_JS = r"""() => {
  const txt = e => (e?.innerText || e?.content || '').replace(/\s+/g, ' ').trim();
  const uniq = a => [...new Set(a.filter(Boolean))];
  const colors = {};
  for (const el of document.querySelectorAll('a,button,h1,h2,h3,header,nav,section,span,div')) {
    const s = getComputedStyle(el);
    for (const c of [s.backgroundColor, s.color]) if (c && !c.includes('rgba(0, 0, 0, 0)')) colors[c] = (colors[c] || 0) + 1;
  }
  const icons = [...document.querySelectorAll('link[rel*=icon],link[rel=apple-touch-icon]')].map(l => l.href);
  const logoImg = [...document.querySelectorAll('header img, nav img, img[alt*=logo i], img[src*=logo i]')].map(i => i.src);
  return {
    title: document.title,
    description: txt(document.querySelector('meta[name=description]')) || txt(document.querySelector('meta[property="og:description"]')),
    og_image: document.querySelector('meta[property="og:image"]')?.content || null,
    lang: document.documentElement.lang || '',
    h1: uniq([...document.querySelectorAll('h1')].map(txt)).slice(0, 5),
    h2: uniq([...document.querySelectorAll('h2')].map(txt)).slice(0, 14),
    h3: uniq([...document.querySelectorAll('h3')].map(txt)).slice(0, 24),
    paragraphs: uniq([...document.querySelectorAll('p,li')].map(txt).filter(t => t.length > 25 && t.length < 260)).slice(0, 30),
    ctas: uniq([...document.querySelectorAll('a,button')].map(txt).filter(t => t.length > 2 && t.length < 40)).slice(0, 30),
    prices: uniq((document.body.innerText.match(/(?:\d[\d\s.,]*\s?(?:€|\$|DA|DZD|MAD|TND|£|USD|EUR)|(?:€|\$|£)\s?\d[\d.,]*)/g) || [])).slice(0, 12),
    phones: uniq(document.body.innerText.match(/\+?\d[\d\s().-]{8,}\d/g) || []).slice(0, 4),
    font_body: getComputedStyle(document.body).fontFamily,
    font_heading: getComputedStyle(document.querySelector('h1') || document.body).fontFamily,
    colors: Object.entries(colors).sort((a, b) => b[1] - a[1]).slice(0, 16),
    icons: uniq(icons), logos: uniq(logoImg).slice(0, 4),
    links: uniq([...document.querySelectorAll('a[href]')].map(a => a.href).filter(h => h.startsWith(location.origin))).slice(0, 40),
  };
}"""


def _rgb_to_hex(c: str) -> str | None:
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", c)
    return "#{:02x}{:02x}{:02x}".format(*map(int, m.groups())) if m else None


def brand_palette(colors: list[list]) -> dict[str, str]:
    """Pick dark/light neutrals and the most used saturated color as primary."""
    import colorsys

    hexes = [(h, n) for c, n in colors if (h := _rgb_to_hex(c))]
    info = []
    for h, n in hexes:
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
        info.append((h, n, ll, ss))
    sat = [x for x in info if x[3] > 0.35 and 0.2 < x[2] < 0.75]
    out = {}
    if sat:
        out["primary"] = sat[0][0]
        if len(sat) > 1:
            out["secondary"] = sat[1][0]
    darks = [x for x in info if x[2] < 0.2]
    lights = [x for x in info if x[2] > 0.93]
    if darks:
        out["dark"] = darks[0][0]
    if lights:
        out["light"] = lights[0][0]
    return out


def _svg_colors(files: list[str]) -> list[str]:
    """Saturated colors used in SVG icons/logos, in order of appearance."""
    import colorsys

    out = []
    for f in files:
        if not f.endswith(".svg"):
            continue
        for h in re.findall(r"#[0-9a-fA-F]{6}\b", Path(f).read_text(errors="ignore")):
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
            _, light, sat = colorsys.rgb_to_hls(r, g, b)
            if sat > 0.35 and 0.2 < light < 0.8 and h.lower() not in out:
                out.append(h.lower())
    return out


async def _analyze(url: str, out_dir: Path) -> dict:
    from playwright.async_api import async_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        desk = await b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page = await desk.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await _warm(page)
        info = await page.evaluate(EXTRACT_JS)
        await page.screenshot(path=out_dir / "desktop_fold.png")
        await page.screenshot(path=out_dir / "desktop_full.png", full_page=True)
        mob = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True,
                                  has_touch=True, user_agent=MOBILE_UA)
        mp = await mob.new_page()
        await mp.goto(url, wait_until="networkidle", timeout=60000)
        await _warm(mp)
        await mp.screenshot(path=out_dir / "mobile_fold.png")
        await mp.screenshot(path=out_dir / "mobile_full.png", full_page=True)
        for i, icon in enumerate(info["icons"][:3]):
            try:
                r = await desk.request.get(icon)
                ext = ".svg" if "svg" in (r.headers.get("content-type") or icon) else ".png"
                (out_dir / f"icon{i}{ext}").write_bytes(await r.body())
            except Exception as e:  # noqa: BLE001 - an icon is optional
                log.debug("icon %s: %s", icon, e)
        await b.close()
    info["url"] = url
    info["icon_files"] = sorted(str(p) for p in out_dir.glob("icon*"))
    info["palette"] = brand_palette(info["colors"])
    logo_colors = _svg_colors(info["icon_files"])
    if logo_colors:  # the logo is the most reliable signal of the brand color
        info["palette"]["primary"] = logo_colors[0]
        if len(logo_colors) > 1:
            info["palette"]["secondary"] = logo_colors[1]
    (out_dir / "site.json").write_text(json.dumps(info, indent=1, ensure_ascii=False))
    return info


async def _warm(page) -> None:
    """Scroll through the page so lazy images load, then return to the top."""
    h = await page.evaluate("document.body.scrollHeight")
    for y in range(0, min(h, 30000), 500):
        await page.evaluate(f"window.scrollTo(0,{y})")
        await page.wait_for_timeout(80)
    await page.evaluate("window.scrollTo(0,0)")
    await page.wait_for_timeout(800)


def analyze(url: str, out_dir: str | Path) -> dict:
    return asyncio.run(_analyze(url, Path(out_dir)))


# ---------------------------------------------------------------- scroll recordings
def _ease(x: float) -> float:
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def scroll_plan(frames: int, distance: float) -> list[float]:
    """Hold, smooth scroll, short hold, second scroll: reads like a real person browsing."""
    segs = [(0.18, 0.55, distance * 0.55), (0.65, 0.95, distance * 0.45)]
    ys = []
    for i in range(frames):
        x, y = i / max(1, frames - 1), 0.0
        for a, bnd, px in segs:
            y += px * (0 if x <= a else 1 if x >= bnd else _ease((x - a) / (bnd - a)))
        ys.append(round(y, 2))
    return ys


async def _record(url: str, out: Path, frames: int, device: str, distance: float | None) -> int:
    from playwright.async_api import async_playwright

    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        if device == "laptop":
            ctx = await b.new_context(viewport={"width": 1440, "height": 834}, device_scale_factor=1.0)
        elif device == "phone_sm":  # the small phones of a `devices` scene (334 x 688 screen)
            ctx = await b.new_context(viewport={"width": 334, "height": 688}, device_scale_factor=2.5, is_mobile=True,
                                      has_touch=True, user_agent=MOBILE_UA)
        else:
            ctx = await b.new_context(viewport={"width": 408, "height": 842}, device_scale_factor=2.5, is_mobile=True,
                                      has_touch=True, user_agent=MOBILE_UA)
        page = await ctx.new_page()
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await _warm(page)
        await page.add_style_tag(content="html{scroll-behavior:auto!important}*{caret-color:transparent!important}")
        page_h = await page.evaluate("document.body.scrollHeight - window.innerHeight")
        dist = min(distance or (1500 if device == "phone" else 1400), max(0, page_h))
        for i, y in enumerate(scroll_plan(frames, dist)):
            await page.evaluate(f"window.scrollTo(0,{y})")
            await page.wait_for_timeout(50)
            await page.screenshot(path=out / f"{i:04d}.jpg", type="jpeg", quality=93)
        await b.close()
    return frames


def record(url: str, out: str | Path, frames: int, device: str = "phone", distance: float | None = None) -> int:
    return asyncio.run(_record(url, Path(out), frames, device, distance))
