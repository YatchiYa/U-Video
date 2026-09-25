"""Screen replacement: put the REAL app/website on phones filmed by the AI.

The shot is generated with the phone screen in flat chroma-key green. For every frame the green screen is keyed,
its four corners are estimated (perspective), smoothed over time, and a frame of the real screen recording is warped
onto it. Fingers and reflections over the screen are kept (only green pixels are replaced) and the original
shading is carried over, so the insert sits in the shot like a real display.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ugc_studio.media import probe, read_frames, write_video_with_audio

log = logging.getLogger(__name__)
GREEN_PROMPT = ("The phone's screen is turned on and displays a flat, uniform, bright chroma-key green color "
                "(pure #00FF00) filling the whole display, for screen replacement.")


def green_mask(rgb: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    r, g, b = (rgb[..., k].astype(int) for k in range(3))
    # Chroma-key green only: very saturated and bright (plants, walls, clothes are far less saturated).
    m = ((h >= 40) & (h <= 85) & (s >= 140) & (v >= 110) & (g > r + 60) & (g > b + 60)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    return m


def _largest(mask: np.ndarray, min_frac: float = 0.002) -> np.ndarray | None:
    """The screen: the largest green blob that is shaped like a display (rectangular, not a leafy blob)."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    best, best_area = None, 0
    for k in range(1, n):
        area = stats[k, cv2.CC_STAT_AREA]
        if area < min_frac * mask.size or area <= best_area:
            continue
        comp = (lab == k).astype(np.uint8) * 255
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        (_, _), (rw, rh), _ = cv2.minAreaRect(max(cnts, key=cv2.contourArea))
        if area / max(1.0, rw * rh) < 0.72:  # fingers over the screen still leave it > 0.72 rectangular
            continue
        best, best_area = comp, area
    return best


def _order(q: np.ndarray) -> np.ndarray:
    """Order corners TL, TR, BR, BL with the short edge on top (portrait screen)."""
    c = q.mean(0)
    q = q[np.argsort(np.arctan2(q[:, 1] - c[1], q[:, 0] - c[0]))]
    best = None
    for k in range(4):
        r = np.roll(q, -k, 0)
        top, side = np.linalg.norm(r[1] - r[0]), np.linalg.norm(r[2] - r[1])
        if top <= side * 1.05:
            ymean = (r[0, 1] + r[1, 1]) / 2
            if best is None or ymean < best[0]:
                best = (ymean, r)
    r = best[1] if best else q
    if r[1, 0] < r[0, 0]:
        r = r[[1, 0, 3, 2]]
    return r.astype(np.float32)


def _intersect(l1, l2) -> np.ndarray | None:
    (vx1, vy1, x1, y1), (vx2, vy2, x2, y2) = l1, l2
    den = vx1 * vy2 - vy1 * vx2
    if abs(den) < 1e-6:
        return None
    t = ((x2 - x1) * vy2 - (y2 - y1) * vx2) / den
    return np.array([x1 + t * vx1, y1 + t * vy1], np.float32)


def quad_from_mask(mask: np.ndarray) -> np.ndarray | None:
    """Sub-pixel screen corners, ordered TL, TR, BR, BL.

    Each of the 4 edges is fitted independently with a robust line through the screen's boundary points
    (the middle part of each side only: rounded corners, the notch and occluding fingers/particles are ignored),
    and the corners are the intersections of adjacent edge lines. Correct under perspective; the quad is then
    validated against the screen area (coverage) and falls back to the bounding rectangle if implausible."""
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    pts = np.concatenate(cnts).reshape(-1, 2).astype(np.float32)
    hull = cv2.convexHull(pts)
    rect = _order(cv2.boxPoints(cv2.minAreaRect(hull)))
    hull_pts = hull.reshape(-1, 2)
    # dense boundary of the convex hull (the notch is a concavity: the hull bridges it)
    dense = []
    for a, b in zip(hull_pts, np.roll(hull_pts, -1, 0)):
        n = max(2, int(np.linalg.norm(b - a)))
        dense.append(np.linspace(a, b, n, endpoint=False))
    dense = np.concatenate(dense)
    lines = []
    for k in range(4):
        a, b = rect[k], rect[(k + 1) % 4]
        d = b - a
        L = np.linalg.norm(d) + 1e-6
        u = d / L
        nrm = np.array([-u[1], u[0]])
        rel = dense - a
        along = rel @ u / L
        dist = np.abs(rel @ nrm)
        sel = dense[(along > 0.2) & (along < 0.8) & (dist < 0.06 * L + 3)]
        if len(sel) < 10:
            return rect  # not enough edge evidence: safe fallback
        lines.append(cv2.fitLine(sel.reshape(-1, 1, 2), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel())
    corners = [_intersect(lines[k - 1], lines[k]) for k in range(4)]
    if any(c is None for c in corners):
        return rect
    q = _order(np.array(corners, np.float32))
    sides = [np.linalg.norm(q[k] - q[(k + 1) % 4]) for k in range(4)]
    area = cv2.contourArea(q)
    hull_area = max(cv2.contourArea(hull), 1.0)
    if not (0.9 * hull_area <= area <= 1.12 * hull_area) or min(sides) / max(sides) < 0.2:
        return rect
    return q


STATUS_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def screen_content(page: np.ndarray, aspect_hw: float) -> np.ndarray:
    """What a real phone shows: an iOS-style status bar (time, signal, wifi, battery) above the page, cropped
    to the screen's exact aspect (height/width) so the page is never stretched."""
    from PIL import Image, ImageDraw, ImageFont

    w = page.shape[1]
    h = int(round(w * aspect_hw))
    bar = max(8, int(0.056 * h))
    body = page[: max(1, h - bar)]
    if body.shape[0] < h - bar:  # page shorter than the screen: extend with its bottom color
        pad = np.repeat(body[-1:], h - bar - body.shape[0], 0)
        body = np.concatenate([body, pad])
    bg = np.median(page[:6].reshape(-1, 3), 0).astype(np.uint8)
    fg = (0, 0, 0) if bg.astype(int).sum() > 380 else (255, 255, 255)
    im = Image.new("RGB", (w, bar), tuple(int(x) for x in bg))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype(STATUS_FONT, int(bar * 0.42))
    except OSError:
        font = ImageFont.load_default()
    y = bar * 0.58
    d.text((w * 0.13, y), "9:41", fill=fg, font=font, anchor="lm")
    x = w * 0.70  # signal bars, wifi, battery on the right (outside the notch)
    u = bar * 0.1
    for k in range(4):
        hh = u * (1.2 + 0.7 * k)
        d.rectangle([x + k * 1.6 * u, y + u * 1.6 - hh, x + k * 1.6 * u + u, y + u * 1.6], fill=fg)
    cx = x + 8.5 * u
    for r_ in (3.2, 2.2, 1.2):
        d.arc([cx - r_ * u, y + 1.8 * u - r_ * u, cx + r_ * u, y + 1.8 * u + r_ * u], 225, 315, fill=fg, width=max(1, int(u * 0.6)))
    bx = cx + 4.5 * u
    d.rounded_rectangle([bx, y - 1.2 * u, bx + 5.5 * u, y + 1.4 * u], radius=u * 0.6, outline=fg, width=max(1, int(u * 0.35)))
    d.rectangle([bx + 0.6 * u, y - 0.6 * u, bx + 4.2 * u, y + 0.8 * u], fill=fg)
    return np.concatenate([np.asarray(im), body])


def key_color(frames: list[np.ndarray]) -> np.ndarray:
    """The clip's actual screen green (median of confidently green pixels over the whole clip)."""
    px = []
    for f in frames[:: max(1, len(frames) // 24)]:
        m = green_mask(f) > 0
        if m.any():
            px.append(f[m][:: max(1, int(m.sum()) // 400)])
    return np.median(np.concatenate(px), 0) if px else np.array([0, 255, 0], np.float32)


def soft_green(rgb: np.ndarray, key: np.ndarray, tol: float = 30.0) -> np.ndarray:
    """Chroma-distance key around the clip's own green: catches dark, blurred and angled screen pixels."""
    ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb).astype(np.float32)
    k = cv2.cvtColor(key.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2YCrCb).astype(np.float32)[0, 0]
    dist = np.hypot(ycc[..., 1] - k[1], ycc[..., 2] - k[2])
    r, g, b = (rgb[..., c].astype(int) for c in range(3))
    m = ((dist < tol) & (ycc[..., 0] > 25) & (g > r + 18) & (g > b + 18)).astype(np.uint8) * 255
    m |= green_mask(rgb)  # lit / tinted screen (glow, colored light) drifts from the learned key: strict green too
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))


def spill(rgb: np.ndarray, screen: np.ndarray, key: np.ndarray, reach: float = 0.12) -> np.ndarray:
    """Reflections / glow spill of the screen: green blobs of the SAME hue as the key, close to the screen
    (within `reach` x frame height). Plants and other scene greens differ in hue or are far away: untouched."""
    if not screen.any():
        return np.zeros_like(screen)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    kh = int(cv2.cvtColor(key.reshape(1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2HSV)[0, 0, 0])
    r_, g_, b_ = (rgb[..., c].astype(int) for c in range(3))
    dark_green = (hsv[..., 1] >= 90) & (hsv[..., 2] >= 18) & (g_ > r_ + 8) & (g_ > b_ + 8)  # dim reflections
    cand = ((broad_green(rgb) > 0) | dark_green) & (np.abs(hsv[..., 0].astype(int) - kh) <= 12)
    r = max(9, int(reach * rgb.shape[0]))
    near = cv2.dilate(screen, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8))
    out = np.zeros(screen.shape, np.uint8)
    for k in range(1, n):
        comp = lab == k
        if stats[k, cv2.CC_STAT_AREA] > 40 and (comp & near).any():
            out[comp] = 255
    return out


def _track(mask: np.ndarray, prev: np.ndarray | None, min_frac: float = 0.0008) -> np.ndarray | None:
    """The screen blob: the one overlapping the previous screen position, else the largest sizeable blob."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return None
    ok = [k for k in range(1, n) if stats[k, cv2.CC_STAT_AREA] >= min_frac * mask.size]
    if not ok:
        return None
    if prev is not None:
        pm = np.zeros_like(mask)
        cv2.fillConvexPoly(pm, prev.astype(np.int32), 255)
        pm = cv2.dilate(pm, np.ones((41, 41), np.uint8))
        near = [k for k in ok if ((lab == k) & (pm > 0)).any()]
        if near:
            ok = near
    k = max(ok, key=lambda k: stats[k, cv2.CC_STAT_AREA])
    return (lab == k).astype(np.uint8) * 255


def broad_green(rgb: np.ndarray, sensitive: bool = False) -> np.ndarray:
    """Any greenish pixel (dark, blurred, pale motion-smeared, grazing-angle screen). Only ever used INSIDE the
    tracked phone zone, so real green things elsewhere in the shot (plants, clothes) are never touched."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    r, g, b = (rgb[..., c].astype(int) for c in range(3))
    if sensitive:  # inside the phone zone only: include pale mint / cyan-green smears of a moving screen
        m = ((hsv[..., 0] >= 30) & (hsv[..., 0] <= 105) & (hsv[..., 1] >= 24) & (hsv[..., 2] >= 35)
             & (g > r + 6) & (g >= b - 4)).astype(np.uint8) * 255
    else:
        m = ((hsv[..., 0] >= 30) & (hsv[..., 0] <= 95) & (hsv[..., 1] >= 80) & (hsv[..., 2] >= 35)
             & (g > r + 12) & (g > b + 12)).astype(np.uint8) * 255
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))


def skin_mask(rgb: np.ndarray) -> np.ndarray:
    """Skin tones (YCrCb box, robust across complexions); used to keep fingers in front of the screen."""
    ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    m = ((ycc[..., 1] >= 135) & (ycc[..., 1] <= 180) & (ycc[..., 2] >= 80) & (ycc[..., 2] <= 130)
         & (ycc[..., 0] >= 50)).astype(np.uint8) * 255
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))


def _hull(mask: np.ndarray) -> np.ndarray:
    """Convex hull of each blob, enlarged: covers motion-blur trails and rounded screen corners."""
    out = np.zeros_like(mask)
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        if cv2.contourArea(c) > 12:
            cv2.fillConvexPoly(out, cv2.convexHull(c), 255)
    return cv2.dilate(out, np.ones((15, 15), np.uint8))


def phone_zones(frames: list[np.ndarray], key: np.ndarray, forget: int = 10) -> list[np.ndarray]:
    """Where the phone screen is in every frame, even when keying fails: detections are propagated forward and
    backward with dense optical flow, then unioned. Returns one uint8 mask per frame."""
    h, w = frames[0].shape[:2]
    sh, sw = h // 2, w // 2
    small = [cv2.cvtColor(cv2.resize(f, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY) for f in frames]
    det = []
    for f in frames:
        sg = soft_green(f, key)
        det.append(cv2.resize(sg | spill(f, sg, key), (sw, sh), interpolation=cv2.INTER_NEAREST))
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    gx, gy = np.meshgrid(np.arange(sw, dtype=np.float32), np.arange(sh, dtype=np.float32))

    def sweep(order: list[int]) -> dict[int, np.ndarray]:
        zones, zone, idle, prev_i = {}, None, 0, None
        for i in order:
            if zone is not None and prev_i is not None:
                flow = dis.calc(small[i], small[prev_i], None)  # where each pixel of frame i came from
                zone = cv2.remap(zone, gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_NEAREST)
            if det[i].any():
                zone = det[i].copy() if zone is None else cv2.bitwise_or(zone, det[i])
                idle = 0
            elif zone is not None:
                idle += 1
                # keep the zone only while there is still greenish material inside it
                if idle > forget or not (broad_green(cv2.resize(frames[i], (sw, sh))) & (zone > 0)).any():
                    zone, idle = None, 0
            zones[i] = None if zone is None else _hull(zone)
            prev_i = i
        return zones

    fwd, bwd = sweep(list(range(len(frames)))), sweep(list(range(len(frames) - 1, -1, -1)))
    out = []
    for i in range(len(frames)):
        z = np.zeros((sh, sw), np.uint8)
        for m in (fwd[i], bwd[i]):
            if m is not None:
                z = cv2.bitwise_or(z, m)
        out.append(cv2.resize(z, (w, h), interpolation=cv2.INTER_NEAREST))
    return out


def insert_screen(clip: str | Path, screens: list[Path], out: str | Path, smooth: float = 0.5) -> dict:
    """Composite the real screen recording onto the green phone screen of `clip`.

    The phone is tracked through the whole shot (chroma key + optical-flow propagation). Inside its zone every
    greenish pixel is replaced: by the perspective-warped app frame when the screen's corners are visible, else
    (edge-on, flipping, motion blur) by a dark display tone. Guarantee, measured on every frame with the broad
    detector: no green left on the phone. Returns stats incl. the worst residual, which the caller gates on."""
    frames = read_frames(clip)
    fps = probe(clip)["fps"]
    h, w = frames[0].shape[:2]
    key = key_color(frames)
    zones = phone_zones(frames, key)
    # Pass 1: per-frame screen corners (no smoothing here: exponential smoothing lags behind a moving phone).
    quads: list[np.ndarray | None] = [None] * len(frames)
    softs: list[np.ndarray | None] = [None] * len(frames)
    prev_q = None
    for i, f in enumerate(frames):
        if not (zones[i] > 0).any():
            prev_q = None
            continue
        softs[i] = soft_green(f, key)
        m = _track(softs[i], prev_q)
        if m is not None and (m > 0).sum() > 0.002 * m.size:
            quads[i] = quad_from_mask(m)
        prev_q = quads[i]
    # Pass 2: centered (zero-lag) smoothing of the corners over +-1 frame, only across small motions.
    diag = float(np.hypot(w, h))
    smooth_q = list(quads)
    for i, q in enumerate(quads):
        if q is None:
            continue
        group = [q] + [quads[j] for j in (i - 1, i + 1) if 0 <= j < len(quads) and quads[j] is not None
                       and np.abs(quads[j] - q).max() < 0.02 * diag]
        smooth_q[i] = np.mean(group, 0).astype(np.float32)
    keyed, residual_max, dark = 0, 0.0, np.array([18, 18, 24], np.float32)
    prev = None
    for i, f in enumerate(frames):
        zone = zones[i] > 0
        if not zone.any():
            continue
        soft = softs[i] if softs[i] is not None else soft_green(f, key)
        warped = None
        prev = smooth_q[i]
        if prev is not None:
            q = prev
            page = cv2.cvtColor(cv2.imread(str(screens[min(len(screens) - 1, int(i * len(screens) / len(frames)))])),
                                cv2.COLOR_BGR2RGB)
            side = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
            top = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
            src = screen_content(page, side / max(top, 1))  # status bar + page at the screen's exact aspect
            sh_, sw_ = src.shape[:2]
            M = cv2.getPerspectiveTransform(np.float32([[0, 0], [sw_, 0], [sw_, sh_], [0, sh_]]), q)
            warped = cv2.warpPerspective(src, M, (w, h), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)
            keyed += 1
        green = ((soft > 0) | (broad_green(f, sensitive=True) > 0)) & zone
        # The screen is ONE surface: its whole shape is replaced (highlights and smears included), except skin,
        # so fingers crossing the display stay in front of it.
        surface = np.zeros(green.shape, np.uint8)
        if warped is not None and prev is not None:
            cv2.fillConvexPoly(surface, prev.astype(np.int32), 255)
        if green.any():
            surface |= _hull(green.astype(np.uint8) * 255) & (cv2.dilate(green.astype(np.uint8) * 255,
                                                                            np.ones((25, 25), np.uint8)))
        surface = (surface > 0) & zone & ~(skin_mask(f) > 0)
        green = green | surface
        g8 = green.astype(np.uint8) * 255
        feather = (5, 5) if warped is not None else (11, 11)  # softer edge when the screen is a blur/edge-on
        alpha = cv2.GaussianBlur(cv2.dilate(g8, np.ones((3, 3), np.uint8)), feather, 0).astype(np.float32)[..., None] / 255
        alpha *= zone[..., None]
        v = cv2.cvtColor(f, cv2.COLOR_RGB2HSV)[..., 2].astype(np.float32)
        ref = np.median(v[green]) + 1e-3 if green.any() else 255.0
        shade = np.clip(v / ref, 0.55, 1.15)[..., None]  # keep the shot's shading on the display
        if warped is not None:
            fill = warped.astype(np.float32) * shade
            # Green OUTSIDE the screen quad = reflection / glow spill on a glossy surface: re-light it with the
            # app's own average color (keeps the reflection's luminance), never smear app pixels onto it.
            quad_m = np.zeros(green.shape, np.uint8)
            cv2.fillConvexPoly(quad_m, prev.astype(np.int32), 255)
            outside = cv2.erode(quad_m, np.ones((3, 3), np.uint8)) == 0
            if (green & outside).any():
                app_col = warped[quad_m > 0].reshape(-1, 3).mean(0).astype(np.float32)
                lum = cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype(np.float32)[..., None] / 255
                glow = np.clip(lum * app_col * 1.1, 0, 255)
                fill = np.where(outside[..., None], glow, fill)
        else:
            # No readable screen (flipping, edge-on, heavy blur): a dark glass display. Keep the blur's own
            # luminance structure, drop its color: reads as a real phone turning, never as blotches.
            lum = cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype(np.float32)[..., None]
            fill = np.clip(lum * 0.28 + dark * 0.6, 0, 255) * np.ones((1, 1, 3), np.float32)
        out_f = f.astype(np.float32) * (1 - alpha) + fill * alpha
        ring = (cv2.dilate(g8, np.ones((9, 9), np.uint8)) > 0) & (alpha[..., 0] < 0.98) & zone
        gch = out_f[..., 1]
        gch[ring] = np.minimum(gch[ring], np.maximum(out_f[..., 0][ring], out_f[..., 2][ring]))  # despill
        # Continuous despill over the phone zone outside the display (reflections, glow, blur trails):
        # G' = min(G, max(R, B)) with a feathered zone -> no thresholds, no edges, works on the darkest pixels.
        # The app picture inside the screen quad is excluded so its own greens (food, icons) stay intact.
        dz = zone.astype(np.uint8) * 255
        if warped is not None and prev is not None:
            inner = np.zeros_like(dz)
            cv2.fillConvexPoly(inner, prev.astype(np.int32), 255)
            dz = cv2.bitwise_and(dz, cv2.bitwise_not(cv2.erode(inner, np.ones((5, 5), np.uint8))))
        wz = cv2.GaussianBlur(cv2.dilate(dz, np.ones((9, 9), np.uint8)), (21, 21), 0).astype(np.float32) / 255
        gmax = np.maximum(out_f[..., 0], out_f[..., 2])
        out_f[..., 1] = out_f[..., 1] * (1 - wz) + np.minimum(out_f[..., 1], gmax) * wz
        res = np.clip(out_f, 0, 255).astype(np.uint8)
        left = (broad_green(res, sensitive=True) > 0) & zone
        if left.any():  # final guarantee on the phone
            res[left] = np.clip(fill[left] * 0.95, 0, 255).astype(np.uint8)
        residual_max = max(residual_max, float(((broad_green(res, sensitive=True) > 0) & zone).mean()))
        frames[i] = res
    # global safety net: saturated chroma green must not exist anywhere in the output
    strict_left = max(float((green_mask(f) > 0).mean()) for f in frames)
    write_video_with_audio(frames, fps, clip, out)
    stats = {"frames": len(frames), "keyed": keyed, "residual_max": round(max(residual_max, strict_left), 6),
             "key_color": [int(x) for x in key]}
    log.info("screen insert %s: %d/%d frames with app, residual %.5f", Path(clip).name, keyed, len(frames),
             stats["residual_max"])
    return stats


def count_screens(rgb: np.ndarray, min_frac: float = 0.002) -> int:
    """Number of display-shaped chroma-green regions in an image (keyframe validation)."""
    mask = green_mask(rgb)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    count = 0
    for k in range(1, n):
        area = stats[k, cv2.CC_STAT_AREA]
        if area < min_frac * mask.size:
            continue
        comp = (lab == k).astype(np.uint8) * 255
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # validation counts every sizeable green area (a phone seen in perspective is not rectangular)
        count += 1
    return count
