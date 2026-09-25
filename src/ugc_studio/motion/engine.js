/* UGC Studio motion engine: builds every scene from window.COMP and exposes a deterministic window.seek(t).
   Opaque scenes (title, screen, image, features, endcard) cover the live-action base layer; shot scenes are
   transparent overlays (kinetic captions, logo bug). Word captions run on top of everything. */
(() => {
  const C = window.COMP;
  const stage = document.getElementById("stage");
  const portrait = C.height > C.width;
  const U = Math.min(C.width, C.height) / 1080;
  stage.style.width = C.width + "px";
  stage.style.height = C.height + "px";
  document.body.style.width = C.width + "px";
  document.body.style.height = C.height + "px";
  stage.className = (portrait ? "portrait" : "landscape") + (C.captions.enabled && C.captions.style !== "none" ? " has-captions" : "");
  const root = document.documentElement.style;
  root.setProperty("--u", U + "px");
  for (const k of ["primary", "secondary", "dark", "light", "accent"]) root.setProperty("--" + k, C.brand[k]);
  root.setProperty("--head", `"${C.brand.font_heading}", "Bricolage Grotesque Variable", "Cairo", sans-serif`);
  root.setProperty("--body", `"${C.brand.font_body}", "Inter Variable", "Cairo", sans-serif`);

  gsap.registerPlugin(CustomEase);
  CustomEase.create("snap", "0.16, 1, 0.3, 1");
  CustomEase.create("swoop", "0.7, 0, 0.2, 1");
  const tl = gsap.timeline({ paused: true });
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  // Thousands groups ("28 751") are joined with a narrow no-break space: one number, never split into two words
  // that right-to-left text would reorder ("751 28").
  const esc = (s) => String(s ?? "").replace(/(\d) (?=\d{3}(?!\d))/g, "$1\u202F")
    .replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const isRTL = (s) => /[֐-ࣿ]/.test(s || "");
  const icon = (name) => `url(node_modules/lucide-static/icons/${name}.svg)`;
  const words = (s) => esc(s).split(/[ \t\n]+/).map((w) => `<span class="w">${w}</span>`).join(" ");
  const logoHTML = (cls = "") => C.brand.logo
    ? `<div class="logo ${cls}"><img src="${C.brand.logo}"></div>`
    : `<div class="logo ${cls}">${esc((C.brand.name || "•").trim()[0] || "•")}</div>`;
  const beatAt = (sc, text, fallback) => {
    const w = (text || "").toLowerCase().replace(/[^\p{L}\p{N}' ]/gu, " ").split(/\s+/).filter(Boolean)[0];
    return w && sc.beats && sc.beats[w] != null ? sc.beats[w] : fallback;
  };

  // ------------------------------------------------------------------ scene builders
  const B = {};

  B.shot = (sc, s) => {
    s.classList.add("overlay");
    if (sc.caption.length) {
      s.append(el("div", "shade"));
      const k = el("div", "kinetic");
      sc.caption.forEach((line) => { const l = el("div", "line"); l.append(el("span", isRTL(line) ? "rtl" : "", esc(line))); k.append(l); });
      s.append(k);
      const prevCap = C.scenes[sc.index - 1] && ["shot", "clip"].includes(C.scenes[sc.index - 1].kind) && C.scenes[sc.index - 1].caption.length;
      const nextCap = C.scenes[sc.index + 1] && ["shot", "clip"].includes(C.scenes[sc.index + 1].kind) && C.scenes[sc.index + 1].caption.length;
      const shade = s.querySelector(".shade");
      // The shade carries across a cut between captioned shots (no brightness pop at a seamless seam).
      if (!prevCap && sc.index > 0) tl.fromTo(shade, { opacity: 0 }, { opacity: 1, duration: 0.5 }, sc.start + 0.05);
      if (!nextCap) tl.to(shade, { opacity: 0, duration: 0.4 }, sc.start + sc.dur - 0.45);
      const spans = [...k.querySelectorAll(".line > span")];
      const step = Math.min(0.9, Math.max(0.3, (sc.dur - 1.0) / Math.max(1, spans.length)));
      spans.forEach((sp, i) => {
        // The opening hook is on screen from frame 0 (it is also the thumbnail on TikTok/Reels).
        if (sc.index === 0 && i === 0) { tl.set(sp, { yPercent: 0 }, 0); tl.set(shade, { opacity: 1 }, 0); return; }
        // Never inside the incoming transition: two captions must not cross-fade over each other.
        const at = Math.max(beatAt(sc, sc.caption[i], 0.3 + i * step), (sc.transition_s || 0) + 0.1 + i * 0.15);
        tl.fromTo(sp, { yPercent: 110 }, { yPercent: 0, duration: 0.6, ease: "snap" }, sc.start + at);
      });
      const nextTs = C.scenes[sc.index + 1] ? C.scenes[sc.index + 1].transition_s || 0 : 0;
      tl.to(spans, { yPercent: -110, duration: 0.35, ease: "power3.in", stagger: 0.04 }, sc.start + sc.dur - nextTs - 0.4);
    }
    if (C.logo_bug) {
      const bug = el("div", "bug", `${logoHTML()}${esc(C.brand.name)}`);
      bug.querySelector(".logo").style.cssText = `width:${40 * U}px;height:${40 * U}px;font-size:${22 * U}px`;
      s.append(bug);
      tl.fromTo(bug, { opacity: 0 }, { opacity: 1, duration: 0.4 }, sc.start + 0.2);
      tl.to(bug, { opacity: 0, duration: 0.2 }, sc.start + sc.dur - 0.3);
    }
  };

  B.image = (sc, s) => {
    const kb = el("div", "kb");
    kb.style.backgroundImage = `url("${sc.image}")`;
    s.append(kb);
    const dir = sc.index % 2 ? 1 : -1;
    tl.fromTo(kb, { scale: 1.0, xPercent: 0 }, { scale: 1.12, xPercent: 2.5 * dir, duration: sc.dur + 1, ease: "none" }, sc.start - 0.3);
    B.shot(sc, s);
  };

  B.title = (sc, s) => {
    s.classList.add(themeClass(sc, sc.index % 2 ? "bg-brand" : "bg-dark"));
    const w = el("div", "title-wrap");
    if (sc.show_logo) w.append(el("div", "", logoHTML()));
    if (sc.eyebrow) w.append(el("div", "eyebrow", esc(sc.eyebrow)));
    const h = el("div", "headline" + (isRTL(sc.headline) ? " rtl" : ""), words(sc.headline || C.brand.name));
    w.append(h);
    if (sc.caption[0]) w.append(el("div", "sub", esc(sc.caption[0])));
    s.append(w);
    if (sc.show_logo) tl.fromTo(w.querySelector(".logo"), { scale: 0.2, rotate: -90, opacity: 0 }, { scale: 1, rotate: 0, opacity: 1, duration: 0.9, ease: "back.out(1.6)" }, sc.start + 0.1);
    tl.fromTo(h.querySelectorAll(".w"), { yPercent: 110, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.7, ease: "snap", stagger: 0.08 }, sc.start + 0.3);
    const rest = [...w.children].filter((c) => c !== h && !c.querySelector(".logo"));
    tl.fromTo(rest, { y: 30 * U, opacity: 0 }, { y: 0, opacity: 1, duration: 0.7, ease: "snap", stagger: 0.12 }, sc.start + 0.6);
    tl.fromTo(w, { scale: 1 }, { scale: 1.06, duration: sc.dur, ease: "none" }, sc.start);
  };

  function phoneDevice(sc) {
    const d = el("div", "device phone-d");
    d.innerHTML = `<div class="phone"><div class="island"></div><div class="screen"><div class="statusbar"><b>9:41</b><span class="sb"><i></i><i></i><i></i></span></div><img alt=""></div></div>`;
    return d;
  }
  function laptopDevice() {
    const d = el("div", "device laptop-d");
    d.innerHTML = `<div class="laptop"><div class="lid"><div class="lscreen"><img alt=""></div></div><div class="base"></div></div>`;
    return d;
  }

  // Light burst + sparkles radiating from a point: the "wow" beat of a 3D reveal.
  function burst(s, at, cx, cy) {
    const glow = el("div", "burst");
    glow.style.left = cx + "px"; glow.style.top = cy + "px";
    s.append(glow);
    tl.fromTo(glow, { scale: 0.1, opacity: 0 }, { scale: 3.2, opacity: 0.95, duration: 0.35, ease: "power2.out" }, at);
    tl.to(glow, { opacity: 0, scale: 4.2, duration: 0.9, ease: "power2.in" }, at + 0.35);
    for (let k = 0; k < 26; k++) {
      const sp = el("div", "spark");
      sp.style.left = cx + "px"; sp.style.top = cy + "px";
      s.append(sp);
      const ang = (k / 26) * Math.PI * 2 + (k % 3) * 0.2, dist = (260 + (k * 53) % 320) * U;
      tl.fromTo(sp, { x: 0, y: 0, scale: 0.4 + (k % 4) * 0.25, opacity: 0 },
        { x: Math.cos(ang) * dist, y: Math.sin(ang) * dist, opacity: 1, duration: 0.55, ease: "power3.out" }, at + 0.02 * (k % 5));
      tl.to(sp, { opacity: 0, scale: 0, duration: 0.6, ease: "power2.in" }, at + 0.5 + 0.02 * (k % 5));
    }
  }
  const themeClass = (sc, dflt) => (sc.theme === "dark" ? "bg-dark" : sc.theme === "light" ? "bg-light" : dflt);

  B.screen = (sc, s) => {
    const dark = themeClass(sc, "bg-light") === "bg-dark";
    s.classList.add(themeClass(sc, "bg-light"), "screen-scene");
    const c1 = dark ? "color-mix(in srgb, var(--secondary) 45%, transparent)" : "color-mix(in srgb, var(--secondary) 30%, #fff)";
    const c2 = dark ? "color-mix(in srgb, var(--primary) 40%, transparent)" : "#ffe3cf";
    s.append(Object.assign(el("div", "blob"), { style: `width:${900 * U}px;height:${900 * U}px;right:${-220 * U}px;top:${-320 * U}px;background:radial-gradient(circle, ${c1}, transparent 70%)` }));
    s.append(Object.assign(el("div", "blob"), { style: `width:${800 * U}px;height:${800 * U}px;left:${-300 * U}px;bottom:${-380 * U}px;background:radial-gradient(circle, ${c2}, transparent 70%)` }));
    const laptop = sc.device === "laptop";
    if (laptop) s.classList.add("has-laptop");
    const dev = laptop ? laptopDevice() : phoneDevice(sc);
    s.append(dev);
    const img = dev.querySelector("img");
    if (sc.seq) { img.classList.add("seq"); img.dataset.seq = sc.id; }
    else if (sc.image) {
      img.src = sc.image;
      // Scroll only what overflows the screen (a screenshot that fits must not scroll into blank space);
      // layout sizes (offset*) ignore the device's 3D transforms. Evaluated at first render, after images decode.
      const scroll = () => {
        const over = img.offsetTop + img.offsetHeight - img.parentElement.clientHeight;
        return -Math.min(35, Math.max(0, over) / Math.max(1, img.offsetHeight) * 100);
      };
      tl.fromTo(img, { yPercent: 0 }, { yPercent: scroll, duration: sc.dur * 0.8, ease: "sine.inOut" }, sc.start + sc.dur * 0.15);
    }
    const copy = el("div", "copy");
    if (sc.eyebrow) copy.append(el("div", "eyebrow", esc(sc.eyebrow)));
    const h = el("div", "headline" + (isRTL(sc.headline) ? " rtl" : ""), words(sc.headline || ""));
    copy.append(h);
    if (sc.bullets.length) {
      const chips = el("div", "chips");
      sc.bullets.forEach((b) => chips.append(el("div", "chip", `<span class="dot"></span>${esc(b)}`)));
      copy.append(chips);
    }
    s.append(copy);
    const inner = dev.firstElementChild;
    if (sc.reveal === "spin") {
      // 3D spin from deep space: 1.5 turns, landing face-on, with a light burst at the landing.
      tl.fromTo(inner, { rotateY: 540 + (laptop ? 0 : -12), rotateX: 18, scale: 0.25, z: -900 * U, opacity: 0 },
        { rotateY: laptop ? 0 : -12, rotateX: 3, scale: 1, z: 0, opacity: 1, duration: 1.35, ease: "power3.out" }, sc.start + 0.05);
      const r = dev.getBoundingClientRect();
      burst(s, sc.start + 1.0, r.left + r.width / 2, r.top + r.height / 2);
    } else if (sc.reveal === "flip") {
      tl.fromTo(inner, { rotateX: -95, y: 200 * U, opacity: 0 }, { rotateX: 3, y: 0, opacity: 1, duration: 1.0, ease: "back.out(1.4)" }, sc.start + 0.05);
    } else {
      tl.fromTo(inner, { y: 700 * U, rotateY: laptop ? 0 : -28, rotateX: 8 }, { y: 0, rotateY: laptop ? 0 : -12, rotateX: 3, duration: 1.1, ease: "snap" }, sc.start + 0.05);
    }
    if (!laptop) tl.to(inner, { rotateY: 8, rotateX: 0, duration: Math.max(0.5, sc.dur - 1.4), ease: "sine.inOut" }, sc.start + 1.4);
    tl.fromTo(copy.querySelectorAll(".eyebrow"), { opacity: 0, y: 20 * U }, { opacity: 1, y: 0, duration: 0.6, ease: "snap" }, sc.start + 0.3);
    tl.fromTo(h.querySelectorAll(".w"), { yPercent: 60, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.75, ease: "snap", stagger: 0.1 }, sc.start + 0.4);
    tl.fromTo(copy.querySelectorAll(".chip"), { x: 80 * U, opacity: 0 }, { x: 0, opacity: 1, duration: 0.6, ease: "snap", stagger: 0.25 }, sc.start + 1.2);
  };

  B.devices = (sc, s) => {
    s.classList.add(themeClass(sc, "bg-dark"), "devices-scene");
    const t = el("div", "dev-title");
    if (sc.eyebrow) t.append(el("div", "eyebrow", esc(sc.eyebrow)));
    const h = el("div", "headline", words(sc.headline || ""));
    t.append(h);
    s.append(t);
    const stageEl = el("div", "fan");
    s.append(stageEl);
    const n = sc.devices.length;
    const cols = sc.devices.map((dv, k) => {
      const col = el("div", "fan-col");
      col.innerHTML = `<div class="phone sm"><div class="island"></div><div class="screen"><div class="statusbar"><b>9:41</b><span class="sb"><i></i><i></i><i></i></span></div><img alt=""></div></div>${dv.label ? `<div class="lang-pill${isRTL(dv.label) ? " rtl" : ""}">${esc(dv.label)}</div>` : ""}`;
      const img = col.querySelector("img");
      if (dv.seq) { img.classList.add("seq"); img.dataset.seq = `${sc.id}__${k}`; } else if (dv.image) img.src = dv.image;
      stageEl.append(col);
      return col;
    });
    tl.fromTo(t.children, { y: -40 * U, opacity: 0 }, { y: 0, opacity: 1, duration: 0.7, ease: "snap", stagger: 0.12 }, sc.start + 0.2);
    // Stacked deep in space, then fanned out like cards in 3D.
    const spread = (portrait ? 330 : 420) * U;
    cols.forEach((c, k) => {
      const off = k - (n - 1) / 2;
      tl.fromTo(c, { x: 0, z: -1100 * U, rotateY: 0, rotateZ: 0, opacity: 0, scale: 0.6 },
        { opacity: 1, scale: 0.85, z: -500 * U, duration: 0.45, ease: "power2.out" }, sc.start + 0.05);
      tl.to(c, { x: off * spread, z: -Math.abs(off) * 180 * U, rotateY: -off * 24, rotateZ: off * 3, scale: portrait ? 0.92 : 1, duration: 0.95, ease: "back.out(1.3)" }, sc.start + 0.5 + 0.05 * k);
      tl.to(c, { rotateY: -off * 16, y: (k % 2 ? -14 : 14) * U, duration: Math.max(0.6, sc.dur - 1.5), ease: "sine.inOut" }, sc.start + 1.5);
      const pill = c.querySelector(".lang-pill");
      if (pill) tl.fromTo(pill, { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.45, ease: "back.out(2)" }, sc.start + 1.0 + 0.15 * k);
    });
    burst(s, sc.start + 0.55, C.width / 2, C.height * (portrait ? 0.58 : 0.56));
  };

  B.features = (sc, s) => {
    s.classList.add(themeClass(sc, "bg-light"));
    s.append(Object.assign(el("div", "blob"), { style: `width:${900 * U}px;height:${900 * U}px;right:${-220 * U}px;top:${-320 * U}px;background:radial-gradient(circle, color-mix(in srgb, var(--secondary) 30%, #fff), transparent 70%)` }));
    const t = el("div", "feat-title");
    if (sc.eyebrow) t.append(el("div", "eyebrow", esc(sc.eyebrow)));
    const h = el("div", "headline", words(sc.headline || ""));
    t.append(h);
    s.append(t);
    const list = sc.features.slice(0, portrait ? 5 : 6);
    // columns follow the card count (4 -> 2x2, never 3+1); Arabic cards read from the right
    const g = el("div", `grid n${list.length}`);
    if (list.some((f) => isRTL(f.title))) g.dir = "rtl";
    list.forEach((f) => {
      const card = el("div", "fcard" + (isRTL(f.title) ? " rtl" : ""), `<i class="ic" style="--i:${icon(f.icon)}"></i><div><b>${esc(f.title)}</b>${f.subtitle ? `<span>${esc(f.subtitle)}</span>` : ""}</div>`);
      g.append(card);
    });
    s.append(g);
    tl.fromTo(t.children, { y: -30 * U, opacity: 0 }, { y: 0, opacity: 1, duration: 0.7, ease: "snap", stagger: 0.1 }, sc.start + 0.15);
    const cards = [...g.children];
    const each = Math.min(0.3, Math.max(0.12, (sc.dur - 1.6) / Math.max(1, cards.length)));
    tl.fromTo(cards, { scale: 0.6, opacity: 0, y: 30 * U }, { scale: 1, opacity: 1, y: 0, duration: 0.6, ease: "back.out(1.6)", stagger: each }, sc.start + 0.6);
  };

  B.endcard = (sc, s) => {
    s.classList.add(themeClass(sc, "bg-brand"));
    if (sc.theme === "dark") s.classList.add("end-dark");
    // Arabic/Hebrew endcard: the whole layout mirrors (text column starts on the right, QR on the left).
    if (isRTL(sc.headline || C.brand.tagline)) s.classList.add("rtl-end");
    s.append(el("div", "rays"));
    const e = el("div", "end");
    e.append(el("div", "brandline", `${logoHTML()}<span>${esc(C.brand.name)}</span>`));
    const tag = sc.headline || C.brand.tagline;
    if (tag) e.append(el("div", "tag" + (isRTL(tag) ? " rtl" : ""), esc(tag)));
    const offer = sc.offer || C.brand.offer;
    if (offer) e.append(el("div", "offer", esc(offer)));
    if (C.brand.url) e.append(el("div", "url", esc(C.brand.url.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0])));
    if (C.brand.phone) e.append(el("div", "contact", esc(C.brand.phone)));
    s.append(e);
    if (sc.qr) {
      const q = el("div", "qr-card", `<img src="${sc.qr}"><span>${esc(sc.qr_label || "Scan me")}</span>`);
      s.append(q);
      tl.fromTo(q, { scale: 0, rotate: -25 }, { scale: 1, rotate: -4, duration: 0.8, ease: "back.out(1.8)" }, sc.start + 0.9);
      tl.to(q, { rotate: -1, y: 8 * U, duration: 1.8, ease: "sine.inOut", yoyo: true, repeat: Math.max(0, Math.floor(sc.dur / 1.8) - 1) }, sc.start + 1.7);
    }
    tl.fromTo(s.querySelector(".rays"), { rotate: 0 }, { rotate: 40, duration: sc.dur, ease: "none" }, sc.start);
    tl.fromTo(e.children, { x: portrait ? 0 : -80 * U, y: portrait ? 40 * U : 0, opacity: 0 }, { x: 0, y: 0, opacity: 1, duration: 0.8, ease: "snap", stagger: 0.14 }, sc.start + 0.15);
    tl.fromTo(e, { scale: 1 }, { scale: 1.04, duration: sc.dur, ease: "none", transformOrigin: "50% 50%" }, sc.start);
    const ob = e.querySelector(".offer");
    if (ob) tl.fromTo(ob, { scale: 1 }, { scale: 1.07, duration: 0.3, yoyo: true, repeat: 1, ease: "power2.inOut" }, sc.start + beatAt(sc, offer, 1.6));
  };

  // ------------------------------------------------------------------ transitions
  const wipe = el("div", "", "");
  wipe.id = "wipe";
  wipe.innerHTML = `<div class="band b1"></div><div class="band b2"></div>`;
  const flash = el("div");
  flash.id = "flash";

  // Band geometry from the frame: a skewed band must be wide enough to cover a tall (9:16) frame completely.
  const SKEW = Math.tan((18 * Math.PI) / 180) * C.height * 1.4;
  const BAND = C.width + SKEW + 40 * U;
  wipe.querySelectorAll(".band").forEach((b, i) => {
    b.style.width = (i === 0 ? BAND : BAND * 0.25) + "px";
    b.style.left = "0px";
  });
  const FROM = -(BAND + SKEW), TO = C.width + SKEW;
  // Park the bands off-screen: a video without any brand/wipe transition must never show them.
  gsap.set(wipe.querySelectorAll(".band"), { x: FROM });
  function brandWipe(t) {
    tl.fromTo(wipe.querySelector(".b2"), { x: FROM }, { x: TO + BAND * 0.2, duration: 0.8, ease: "swoop" }, t - 0.42);
    tl.fromTo(wipe.querySelector(".b1"), { x: FROM }, { x: TO, duration: 0.8, ease: "swoop" }, t - 0.36);
  }
  function whiteFlash(t, d) {
    tl.fromTo(flash, { opacity: 0 }, { opacity: 1, duration: d / 2, ease: "power2.in" }, t - d / 2);
    tl.to(flash, { opacity: 0, duration: d / 2, ease: "power2.out" }, t);
  }

  const scenesEl = [];
  C.scenes.forEach((sc, i) => {
    sc.index = i;
    const s = el("div", "scene");
    s.id = "sc_" + sc.id;
    stage.append(s);
    scenesEl.push(s);
    (B[sc.kind] || B.shot)(sc, s);
  });
  // Right-to-left scripts everywhere: any text element whose content is Arabic/Hebrew gets dir=rtl + the Arabic
  // font, whatever the scene type (headlines, offers, chips, cards, captions, labels...).
  stage.querySelectorAll(".headline,.eyebrow,.sub,.chip,.offer,.tag,.url,.contact,.kinetic .line,.fcard,.lang-pill,.qr-card span,.feat-title,.dev-title")
    .forEach((n) => { if (isRTL(n.textContent)) { n.setAttribute("dir", "rtl"); n.classList.add("rtl"); } });
  stage.append(wipe, flash);
  const capBox = el("div", C.captions.position || "bottom");
  capBox.id = "captions";
  stage.append(capBox);

  // Visibility windows + entrance/exit transitions.
  C.scenes.forEach((sc, i) => {
    const s = scenesEl[i];
    const prev = C.scenes[i - 1], next = C.scenes[i + 1];
    const d = sc.transition_s || 0;
    const live = (k) => k === "shot" || k === "clip";
    const opaque = !live(sc.kind);
    const mid = sc.start + d / 2;
    const T = sc.transition;
    let showAt = sc.start;
    if (["brand", "wipe", "fadewhite", "cut"].includes(T)) showAt = T === "cut" ? sc.start : mid;
    const nextD = next ? next.transition_s || 0 : 0;
    let hideAt = sc.start + sc.dur;
    if (next) {
      const nT = next.transition;
      hideAt = ["brand", "wipe", "fadewhite"].includes(nT) ? next.start + nextD / 2 : nT === "cut" ? next.start : next.start + nextD;
    }
    tl.set(s, { visibility: "visible" }, Math.max(0, showAt));
    tl.set(s, { visibility: "hidden" }, hideAt);

    if (T === "brand" || T === "wipe") brandWipe(mid);
    if (T === "fadewhite") whiteFlash(mid, Math.max(0.2, d));
    if (!opaque) {
      // Revealing live action: the previous opaque scene animates out over the base layer.
      if (prev && !live(prev.kind) && d > 0) {
        const ps = scenesEl[i - 1];
        if (T === "fade" || T === "dissolve") tl.fromTo(ps, { opacity: 1 }, { opacity: 0, duration: d, ease: "none" }, sc.start);
        if (T === "circle") tl.fromTo(ps, { clipPath: "circle(80% at 50% 50%)" }, { clipPath: "circle(0% at 50% 50%)", duration: d, ease: "power3.inOut" }, sc.start);
        if (T === "slide" || T === "whip") tl.fromTo(ps, { xPercent: 0 }, { xPercent: -100, duration: d, ease: "swoop" }, sc.start);
        if (T === "zoom") tl.fromTo(ps, { scale: 1, opacity: 1 }, { scale: 1.35, opacity: 0, duration: d, ease: "power2.in" }, sc.start);
      }
      return;
    }
    if (d > 0) {
      if (T === "fade" || T === "dissolve") tl.fromTo(s, { opacity: 0 }, { opacity: 1, duration: d, ease: "none" }, sc.start);
      if (T === "circle") tl.fromTo(s, { clipPath: "circle(0% at 50% 50%)" }, { clipPath: "circle(80% at 50% 50%)", duration: d, ease: "power3.inOut" }, sc.start);
      if (T === "slide") tl.fromTo(s, { xPercent: 100 }, { xPercent: 0, duration: d, ease: "swoop" }, sc.start);
      if (T === "whip") tl.fromTo(s, { xPercent: 100, filter: `blur(${24 * U}px)` }, { xPercent: 0, filter: "blur(0px)", duration: d, ease: "swoop" }, sc.start);
      if (T === "zoom") tl.fromTo(s, { scale: 1.3, opacity: 0 }, { scale: 1, opacity: 1, duration: d, ease: "power3.out" }, sc.start);
      if (prev && !live(prev.kind) && (T === "slide" || T === "whip")) tl.fromTo(scenesEl[i - 1], { xPercent: 0 }, { xPercent: -30, duration: d, ease: "swoop" }, sc.start);
    }
    // Gentle camera drift so holds are never dead frames.
    if (["screen", "features", "devices"].includes(sc.kind)) tl.fromTo(s, { scale: 1 }, { scale: 1.03, duration: sc.dur + nextD, ease: "none", immediateRender: false }, sc.start + d);
  });
  tl.set({}, {}, C.total);

  // ------------------------------------------------------------------ word captions (computed per frame)
  const chunks = [];
  if (C.captions.enabled && C.captions.style !== "none") {
    let cur = [];
    // The endcard already shows the brand, offer and QR: word captions there would repeat it and cover the QR.
    const onEndcard = (w) => C.scenes.some((sc) => sc.kind === "endcard" && w.t0 >= sc.start + (sc.transition_s || 0) / 2 && w.t0 < sc.start + sc.dur);
    C.captions.words.filter((w) => !onEndcard(w)).forEach((w, i, words) => {
      const prev = words[i - 1];
      const gap = prev ? w.t0 - prev.t1 : 0;
      if (cur.length && (cur.length >= (portrait ? 3 : 5) || gap > 0.35 || /[.!?,;:]$/.test(prev.w))) { chunks.push(cur); cur = []; }
      cur.push(w);
    });
    if (cur.length) chunks.push(cur);
  }
  let capKey = null;
  function drawCaptions(t) {
    const ch = chunks.find((c) => t >= c[0].t0 - 0.05 && t <= c[c.length - 1].t1 + 0.12);
    const key = ch ? chunks.indexOf(ch) : -1;
    if (key !== capKey) {
      capBox.innerHTML = ch ? `<div class="cap ${C.captions.style}" dir="auto">${ch.map((w) => `<span class="cw">${esc(w.w)}</span>`).join("")}</div>` : "";
      capKey = key;
    }
    if (!ch) return;
    const box = capBox.firstElementChild;
    const k = Math.min(1, (t - ch[0].t0 + 0.05) / 0.12);
    box.style.transform = `scale(${0.82 + 0.18 * (1 - Math.pow(1 - k, 3))})`;
    [...box.children].forEach((sp, i) => sp.classList.toggle("on", t >= ch[i].t0 - 0.02 && t < (ch[i + 1] ? ch[i + 1].t0 : ch[i].t1 + 0.12)));
  }

  // ------------------------------------------------------------------ seek
  const SEQ = {};
  C.scenes.forEach((sc) => {
    if (sc.seq) SEQ[sc.id] = { cfg: sc.seq, start: sc.start };
    (sc.devices || []).forEach((dv, k) => { if (dv.seq) SEQ[`${sc.id}__${k}`] = { cfg: dv.seq, start: sc.start }; });
  });
  const seqs = [...document.querySelectorAll("img.seq")].map((img) => ({ img, ...SEQ[img.dataset.seq], cur: -1 })).filter((q) => q.cfg);
  window.seek = async (t) => {
    // GSAP skips zero-duration sets placed exactly at the playhead's start: nudge t=0 so frame 0 is complete.
    tl.seek(Math.max(t, 1e-5), false);
    drawCaptions(t);
    const waits = [];
    for (const s of seqs) {
      const f = Math.min(s.cfg.frames - 1, Math.max(0, Math.floor((t - s.start) * C.fps + 1e-6)));
      if (f !== s.cur) {
        s.cur = f;
        s.img.src = `${s.cfg.dir}/${String(f).padStart(4, "0")}.jpg`;
        waits.push(s.img.decode().catch(() => {}));
      }
    }
    await Promise.all(waits);
    return true;
  };
  window.compReady = (async () => {
    await document.fonts.ready;
    await Promise.all([...document.querySelectorAll("img:not(.seq)")].map((i) => (i.complete ? Promise.resolve() : i.decode().catch(() => {}))));
    await window.seek(0);
    return true;
  })();
})();
