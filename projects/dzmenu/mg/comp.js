/* DZ-MeNU TV spot - motion design. Deterministic: the renderer calls window.seek(t) per frame. */
(() => {
  const TL = window.TL;
  const S = TL.scenes;
  const $ = (q, r = document) => r.querySelector(q);
  const $$ = (q, r = document) => [...r.querySelectorAll(q)];
  gsap.registerPlugin(CustomEase);
  CustomEase.create("snap", "0.16, 1, 0.3, 1");      // fast-out, long settle: premium UI motion
  CustomEase.create("swoop", "0.7, 0, 0.2, 1");
  const master = gsap.timeline({ paused: true });
  const at = (id, off = 0) => S[id].start + off;
  const endOf = (id) => S[id].start + S[id].dur;

  function show(id, pre = 0, post = 0) {
    const el = document.getElementById(id);
    master.set(el, { visibility: "visible" }, Math.max(0, at(id) - pre));
    master.set(el, { visibility: "hidden" }, endOf(id) + post);
    return el;
  }
  function wipe(t) { // diagonal brand wipe, fully covering the frame at time t
    master.fromTo("#wipe .b2", { left: "-150%" }, { left: "130%", duration: 0.8, ease: "swoop" }, t - 0.42);
    master.fromTo("#wipe .b1", { left: "-150%" }, { left: "120%", duration: 0.8, ease: "swoop" }, t - 0.36);
  }
  function lines(sel, t, stagger = 0.22) {
    master.fromTo($$(sel + " .line > span"), { yPercent: 110 }, { yPercent: 0, duration: 0.7, ease: "snap", stagger }, t);
  }
  function linesOut(sel, t) {
    master.to($$(sel + " .line > span"), { yPercent: -110, duration: 0.45, ease: "power3.in", stagger: 0.05 }, t);
  }
  function kenBurnsNone() {}

  // ---------------- 1. paper (live action) ----------------
  show("s_paper");
  master.fromTo("#s_paper .shade-bottom", { opacity: 0 }, { opacity: 1, duration: 0.6 }, at("s_paper", 0.1));
  (() => { // one phrase per beat of the voice-over
    const spans = $$("#s_paper .line > span");
    const beats = S.s_paper.beats || [0.35, 1.35, 2.4];
    spans.forEach((s, i) => master.fromTo(s, { yPercent: 110 }, { yPercent: 0, duration: 0.6, ease: "snap" }, at("s_paper", beats[i])));
  })();

  // ---------------- 2. terrace (live action) ----------------
  show("s_terrace");
  master.fromTo("#s_terrace .shade-full", { opacity: 0 }, { opacity: 1, duration: 0.5 }, at("s_terrace", 0.0));
  lines("#s_terrace", at("s_terrace", 0.3), 0.18);
  master.fromTo("#s_terrace .pill-hl", { scale: 0.6, rotate: -4 }, { scale: 1, rotate: -2, duration: 0.7, ease: "back.out(2.2)" }, at("s_terrace", 0.62));
  master.to("#s_terrace .kinetic", { scale: 1.06, duration: S.s_terrace.dur, ease: "none" }, at("s_terrace"));

  // ---------------- 3. logo ----------------
  wipe(at("s_logo"));
  show("s_logo");
  master.fromTo("#s_logo .glow.g1", { scale: 0.6, opacity: 0 }, { scale: 1.1, opacity: 1, duration: 2.5, ease: "power2.out" }, at("s_logo"));
  master.fromTo("#s_logo .logo-icon", { scale: 0.2, rotate: -90, opacity: 0 }, { scale: 1, rotate: 0, opacity: 1, duration: 1.0, ease: "back.out(1.6)" }, at("s_logo", 0.15));
  master.fromTo("#s_logo .spark", { scale: 0, transformOrigin: "50% 50%" }, { scale: 1, duration: 0.7, ease: "back.out(3)" }, at("s_logo", 0.55));
  master.fromTo("#s_logo .wordmark span", { yPercent: 120, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.7, ease: "snap", stagger: 0.05 }, at("s_logo", 0.55));
  master.fromTo("#s_logo .logo-tagline", { y: 30, opacity: 0 }, { y: 0, opacity: 1, duration: 0.8, ease: "snap" }, at("s_logo", 1.3));
  master.to("#s_logo .logo-lockup, #s_logo .logo-tagline", { scale: 1.6, opacity: 0, duration: 0.45, ease: "power3.in" }, endOf("s_logo") - 0.4);

  // Logo bug on all live-action scenes after the logo reveal.
  ["s_scan", "s_owner", "s_family"].forEach((id) => {
    master.fromTo("#bug", { opacity: 0, y: -10 }, { opacity: 1, y: 0, duration: 0.4 }, at(id, 0.2));
    master.to("#bug", { opacity: 0, duration: 0.2 }, endOf(id) - 0.3);
  });

  // ---------------- 4. scan (live action) ----------------
  show("s_scan");
  master.fromTo("#s_scan .scan-badge", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6, ease: "snap" }, at("s_scan", 0.3));
  lines("#s_scan", at("s_scan", 0.9), 0.35);

  // ---------------- 5. phone scroll ----------------
  wipe(at("s_phone"));
  show("s_phone", 0, 0.75);   // stays under the s_tri circle reveal
  master.fromTo("#phone1 .phone", { y: 700, rotateY: -28, rotateX: 8, rotateZ: -6 }, { y: 0, rotateY: -12, rotateX: 4, rotateZ: -2, duration: 1.2, ease: "snap" }, at("s_phone", 0.05));
  master.to("#phone1 .phone", { rotateY: 8, rotateX: 0, rotateZ: 1, duration: S.s_phone.dur - 1.2, ease: "sine.inOut" }, at("s_phone", 1.25));
  master.fromTo("#s_phone .eyebrow", { x: 60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.7, ease: "snap" }, at("s_phone", 0.35));
  master.fromTo("#s_phone .h1 .w", { yPercent: 60, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.8, ease: "snap", stagger: 0.15 }, at("s_phone", 0.45));
  master.fromTo("#s_phone .chip", { x: 80, opacity: 0 }, { x: 0, opacity: 1, duration: 0.7, ease: "snap", stagger: 0.28 }, at("s_phone", 1.3));
  master.fromTo("#s_phone .real-note", { opacity: 0 }, { opacity: 1, duration: 0.6 }, at("s_phone", 2.3));
  master.fromTo("#s_phone .blob.b1", { x: 0 }, { x: -120, duration: S.s_phone.dur, ease: "none" }, at("s_phone"));

  // ---------------- 6. trilingual ----------------
  show("s_tri", 0.1);
  master.fromTo("#s_tri", { clipPath: "circle(0% at 50% 50%)" }, { clipPath: "circle(75% at 50% 50%)", duration: 0.7, ease: "power3.inOut" }, at("s_tri", -0.1));
  master.fromTo("#s_tri .tri-title .big", { yPercent: 80, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.7, ease: "snap", stagger: 0.18 }, at("s_tri", 0.25));
  master.fromTo("#s_tri .tri-col", { y: 900 }, { y: 0, duration: 1.0, ease: "snap", stagger: 0.14 }, at("s_tri", 0.1));
  // Highlight each language as the voice names it.
  const tb = S.s_tri.beats || [0.35, 1.05, 1.85];
  ["#tri_fr", "#tri_ar", "#tri_en"].forEach((c, i) => {
    master.to(c, { scale: 1.07, duration: 0.45, ease: "back.out(2)" }, at("s_tri", tb[i]));
    master.fromTo(c + " .lang-pill", { scale: 1 }, { scale: 1.15, duration: 0.3, yoyo: true, repeat: 1, ease: "power2.out" }, at("s_tri", tb[i]));
    master.to(c, { scale: 1, duration: 0.5, ease: "power2.inOut" }, at("s_tri", tb[i] + 0.7));
  });

  // ---------------- 7. owner (live action) ----------------
  wipe(at("s_owner"));
  show("s_owner");
  master.fromTo("#s_owner .flash", { opacity: 0 }, { opacity: 0.85, duration: 0.06, yoyo: true, repeat: 1 }, at("s_owner", S.s_owner.flash || 1.6));
  lines("#s_owner", at("s_owner", 0.35), 0.3);

  // ---------------- 8. paper -> digital ----------------
  wipe(at("s_digit"));
  show("s_digit", 0, 0.5);    // stays under the s_service push
  const d = S.s_digit.dur;
  master.fromTo("#s_digit .digit-title", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.7, ease: "snap" }, at("s_digit", 0.1));
  master.fromTo("#s_digit .paper", { x: -700, rotate: -14 }, { x: 0, rotate: -4, duration: 0.9, ease: "snap" }, at("s_digit", 0.0));
  master.set("#s_digit .scanline", { opacity: 1 }, at("s_digit", 0.8));
  master.fromTo("#s_digit .scanline", { top: 0 }, { top: 636, duration: 1.4, ease: "sine.inOut" }, at("s_digit", 0.8));
  master.fromTo("#s_digit .scan-glow", { height: 0 }, { height: 640, duration: 1.4, ease: "sine.inOut" }, at("s_digit", 0.8));
  master.to("#s_digit .scanline", { opacity: 0, duration: 0.2 }, at("s_digit", 2.2));
  master.fromTo("#s_digit .p-row", { backgroundColor: "rgba(161,99,255,0)" }, { backgroundColor: "rgba(161,99,255,.16)", duration: 0.2, stagger: 0.25 }, at("s_digit", 1.05));
  master.fromTo("#s_digit .arrow-flow", { scale: 0, rotate: -120 }, { scale: 1, rotate: 0, duration: 0.6, ease: "back.out(2)" }, at("s_digit", 1.5));
  master.fromTo("#card_fr", { x: -260, opacity: 0, scale: 0.85 }, { x: 0, opacity: 1, scale: 1, duration: 0.8, ease: "snap" }, at("s_digit", 1.8));
  master.fromTo("#card_fr .dc-row", { x: -30, opacity: 0 }, { x: 0, opacity: 1, duration: 0.45, ease: "snap", stagger: 0.12 }, at("s_digit", 2.0));
  master.fromTo("#card_ar", { rotateY: 90, opacity: 0, transformPerspective: 1400 }, { rotateY: 0, opacity: 1, duration: 0.9, ease: "snap" }, at("s_digit", 2.7));
  master.fromTo("#card_ar .dc-row", { x: 30, opacity: 0 }, { x: 0, opacity: 1, duration: 0.45, ease: "snap", stagger: 0.12 }, at("s_digit", 2.9));
  master.fromTo("#s_digit .timer-badge", { y: -30, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6, ease: "snap" }, at("s_digit", 0.5));
  (() => { // 0:00 -> 2:00 counter, finishing as the voice says "deux minutes"
    const o = { v: 0 }, el = $("#s_digit .tnum");
    const t0 = 0.7, t1 = Math.max(2.5, (S.s_digit.twoMin || d - 0.9));
    master.fromTo(o, { v: 0 }, { v: 120, duration: t1 - t0, ease: "power1.inOut", onUpdate: () => {
      const s = Math.round(o.v); el.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    } }, at("s_digit", t0));
    master.fromTo("#s_digit .timer-badge", { backgroundColor: "#161320" }, { backgroundColor: "#1f8a4c", duration: 0.3 }, at("s_digit", t1));
  })();

  // ---------------- 9. 24h service ----------------
  show("s_service", 0.35, 0.7); // stays under the s_features reveal
  master.fromTo("#s_service", { xPercent: 100 }, { xPercent: 0, duration: 0.7, ease: "swoop" }, at("s_service", -0.35));
  master.to("#s_digit", { xPercent: -30, duration: 0.7, ease: "swoop" }, at("s_service", -0.35));
  master.fromTo("#s_service .service-copy > *", { y: 50, opacity: 0 }, { y: 0, opacity: 1, duration: 0.7, ease: "snap", stagger: 0.14 }, at("s_service", 0.2));
  master.fromTo("#s_service .chat", { y: 120, opacity: 0, rotate: 3 }, { y: 0, opacity: 1, rotate: 0, duration: 0.9, ease: "snap" }, at("s_service", 0.1));
  master.fromTo("#s_service .cursor", { x: -300, y: 120, opacity: 0 }, { x: -260, y: -10, opacity: 1, duration: 0.7, ease: "power2.out" }, at("s_service", 0.5));
  master.to("#s_service .cursor", { scale: 0.75, duration: 0.1, yoyo: true, repeat: 1 }, at("s_service", 1.2));
  master.to("#s_service .wa-btn", { scale: 0.94, duration: 0.1, yoyo: true, repeat: 1 }, at("s_service", 1.2));
  master.to("#s_service .cursor", { opacity: 0, duration: 0.3 }, at("s_service", 1.6));
  master.fromTo("#s_service .bubble.photo", { scale: 0.6, opacity: 0, transformOrigin: "100% 0%" }, { scale: 1, opacity: 1, duration: 0.5, ease: "back.out(1.8)" }, at("s_service", 1.35));
  master.fromTo("#s_service .bubble.me:not(.photo)", { scale: 0.6, opacity: 0, transformOrigin: "100% 0%" }, { scale: 1, opacity: 1, duration: 0.5, ease: "back.out(1.8)" }, at("s_service", 1.75));
  master.fromTo("#s_service .typing", { opacity: 0 }, { opacity: 1, duration: 0.2 }, at("s_service", 2.2));
  master.fromTo("#s_service .typing i", { y: 0 }, { y: -8, duration: 0.25, yoyo: true, repeat: 5, stagger: 0.1, ease: "sine.inOut" }, at("s_service", 2.2));
  master.to("#s_service .typing", { opacity: 0, height: 0, padding: 0, duration: 0.2 }, at("s_service", 3.0));
  master.fromTo("#s_service .bubble.them", { scale: 0.6, opacity: 0, transformOrigin: "0% 0%" }, { scale: 1, opacity: 1, duration: 0.55, ease: "back.out(1.8)" }, at("s_service", 3.05));
  master.fromTo("#s_service .big24 .n", { textContent: 0 }, { textContent: 24, duration: 1.2, ease: "power2.out", snap: { textContent: 1 } }, at("s_service", 0.5));

  // ---------------- 10. features ----------------
  show("s_features", 0.2);
  master.fromTo("#s_features", { clipPath: "inset(50% 50% 50% 50% round 60px)" }, { clipPath: "inset(0% 0% 0% 0% round 0px)", duration: 0.8, ease: "power3.inOut" }, at("s_features", -0.2));
  master.fromTo("#s_features .feat-title", { y: -40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.7, ease: "snap" }, at("s_features", 0.2));
  master.fromTo("#s_features .laptop", { y: 500, scale: 0.9 }, { y: 0, scale: 1, duration: 1.0, ease: "snap" }, at("s_features", 0.05));
  master.fromTo("#s_features .fcard", { scale: 0.5, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.6, ease: "back.out(1.7)", stagger: { each: 0.22, from: "start" } }, at("s_features", 0.8));
  master.to("#s_features .fcard", { y: (i) => (i % 2 ? -10 : 10), duration: S.s_features.dur, ease: "sine.inOut" }, at("s_features", 1.2));

  // ---------------- 11. family (live action) ----------------
  wipe(at("s_family"));
  show("s_family");
  lines("#s_family", at("s_family", 0.35), 0.45);

  // ---------------- 12. end card ----------------
  wipe(at("s_end"));
  show("s_end", 0, 5);
  master.fromTo("#s_end .end-left > *", { x: -80, opacity: 0 }, { x: 0, opacity: 1, duration: 0.8, ease: "snap", stagger: 0.16 }, at("s_end", 0.15));
  master.fromTo("#s_end .end-phone", { y: 900, rotate: 16 }, { y: 0, rotate: 6, duration: 1.1, ease: "snap" }, at("s_end", 0.2));
  master.fromTo("#s_end .qr-card", { scale: 0, rotate: -30 }, { scale: 1, rotate: -5, duration: 0.8, ease: "back.out(1.8)" }, at("s_end", 0.9));
  master.fromTo("#s_end .offer", { scale: 1 }, { scale: 1.06, duration: 0.35, yoyo: true, repeat: 1, ease: "power2.inOut" }, at("s_end", S.s_end.offerBeat || 1.6));
  master.fromTo("#s_end .end-foot", { opacity: 0 }, { opacity: 1, duration: 0.8 }, at("s_end", 1.2));

  // ---------------- camera drift: no dead frames on holds ----------------
  const drift = { s_phone: 1.035, s_tri: 1.035, s_digit: 1.035, s_service: 1.03, s_features: 1.035 };
  Object.entries(drift).forEach(([id, sc]) => {
    master.fromTo("#" + id, { scale: 1 }, { scale: sc, duration: S[id].dur + 0.8, ease: "none", transformOrigin: "50% 50%" }, at(id, -0.2));
  });
  master.fromTo("#s_logo .logo-lockup", { scale: 1 }, { scale: 1.09, duration: S.s_logo.dur - 0.4, ease: "none" }, at("s_logo"));  // ends where the exit zoom starts
  master.fromTo("#s_logo .glow.g2", { x: 0, y: 0 }, { x: -260, y: -120, duration: S.s_logo.dur, ease: "sine.inOut" }, at("s_logo"));
  master.fromTo("#s_logo .logo-tagline", { letterSpacing: "0em" }, { letterSpacing: "0.02em", duration: S.s_logo.dur, ease: "none" }, at("s_logo"));
  master.fromTo("#s_end .end-grid", { scale: 1 }, { scale: 1.04, duration: S.s_end.dur, ease: "none" }, at("s_end"));
  master.to("#s_end .end-phone", { y: -18, duration: 1.6, ease: "sine.inOut", yoyo: true, repeat: 5 }, at("s_end", 1.3));
  master.to("#s_end .qr-card", { rotate: -2, y: 8, duration: 1.9, ease: "sine.inOut", yoyo: true, repeat: 3 }, at("s_end", 1.7));
  master.fromTo("#s_end .end-rays", { rotate: 0 }, { rotate: 45, duration: S.s_end.dur, ease: "none" }, at("s_end"));

  master.set({}, {}, TL.total);

  // ---------------- screen-recording sequences ----------------
  const seqEls = $$("img.seq").map((el) => ({ el, cfg: TL.seqs[el.dataset.seq], cur: -1 }));

  window.seek = async (t) => {
    master.seek(t, false);
    const waits = [];
    for (const s of seqEls) {
      if (!s.cfg) continue;
      const f = Math.min(s.cfg.frames - 1, Math.max(0, Math.floor((t - s.cfg.start) * TL.fps + 1e-6)));
      if (f !== s.cur) {
        s.cur = f;
        s.el.src = `${s.cfg.dir}/${String(f).padStart(4, "0")}.jpg`;
        waits.push(s.el.decode().catch(() => {}));
      }
    }
    await Promise.all(waits);
    return true;
  };
  window.compReady = (async () => {
    await document.fonts.ready;
    await Promise.all($$("img:not(.seq)").map((i) => i.decode().catch(() => {})));
    await window.seek(0);
    return true;
  })();
})();
