"""Capture dz-menu.com screens (mobile + desktop, FR/AR/EN) and brand info for the promo."""
import asyncio, json
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).parent / "capture"
BASE = "https://dz-menu.com"
MOBILE = [("home_fr", "/fr"), ("menu_fr", "/fr/menu/baraka-glace"), ("menu_ar", "/ar/menu/baraka-glace"),
          ("menu_en", "/en/menu/baraka-glace"), ("landing_fr_m", "/fr/landing"), ("shops_fr_m", "/fr/explore/shops"),
          ("items_fr_m", "/fr/explore/items")]
DESKTOP = [("landing_fr", "/fr/landing"), ("home_fr_d", "/fr"), ("shops_fr", "/fr/explore/shops"), ("menu_fr_d", "/fr/menu/baraka-glace")]

BRAND_JS = """() => {
  const cs = e => e ? getComputedStyle(e) : null;
  const colors = {};
  for (const el of document.querySelectorAll('a,button,h1,h2,h3,header,nav,span,div')) {
    const s = getComputedStyle(el);
    for (const c of [s.backgroundColor, s.color]) if (c && !c.includes('rgba(0, 0, 0, 0)')) colors[c] = (colors[c]||0)+1;
  }
  const logo = [...document.querySelectorAll('img,svg')].slice(0,5).map(e => ({tag:e.tagName, src:e.src||null, alt:e.alt||null, w:e.width, h:e.height}));
  return {title: document.title, font: cs(document.body).fontFamily, h1font: cs(document.querySelector('h1'))?.fontFamily,
          colors: Object.entries(colors).sort((a,b)=>b[1]-a[1]).slice(0,15), logo,
          metaTheme: document.querySelector('meta[name=theme-color]')?.content, icons: [...document.querySelectorAll('link[rel*=icon]')].map(l=>l.href)};
}"""

async def shoot(ctx, name, path):
    page = await ctx.new_page()
    await page.goto(BASE + path, wait_until="networkidle", timeout=60000)
    # Trigger lazy images by scrolling through the page, then return to the top.
    h = await page.evaluate("document.body.scrollHeight")
    for y in range(0, h, 400):
        await page.evaluate(f"window.scrollTo(0,{y})"); await page.wait_for_timeout(120)
    await page.evaluate("window.scrollTo(0,0)"); await page.wait_for_timeout(1500)
    await page.screenshot(path=OUT / f"{name}.png", full_page=True)
    await page.screenshot(path=OUT / f"{name}_fold.png")
    info = await page.evaluate(BRAND_JS)
    await page.close()
    return info

async def main():
    OUT.mkdir(exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        mob = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True,
                                  user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")
        desk = await b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        brand = {}
        for n, pth in MOBILE: brand[n] = await shoot(mob, n, pth); print("ok", n)
        for n, pth in DESKTOP: brand[n] = await shoot(desk, n, pth); print("ok", n)
        (OUT / "brand.json").write_text(json.dumps(brand, indent=1))
        await b.close()

asyncio.run(main())
