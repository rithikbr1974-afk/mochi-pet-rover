/* Mochi's eyes: two glowing eyes drawn on a canvas, driven by her emotion.
   Every value eases toward the emotion's target, so changes melt into each other. She blinks, glances around,
   and her glow pulses while she talks.  Eyes.set({label, talking, busy}) */
(function () {
  const C = {   // target shape per emotion
    neutral: { open: 1, inT: 0, outT: 0, smile: 0, heart: 0, star: 0, asym: 0, pupil: .40, bounce: 0, col: [72, 224, 192] },
    happy:   { open: 1, inT: 0, outT: 0, smile: 1, heart: 0, star: 0, asym: 0, pupil: .40, bounce: .4, col: [126, 234, 168] },
    excited: { open: 1.12, inT: 0, outT: 0, smile: 0, heart: 0, star: 1, asym: 0, pupil: .46, bounce: 1, col: [255, 209, 102] },
    angry:   { open: .78, inT: .6, outT: 0, smile: 0, heart: 0, star: 0, asym: 0, pupil: .34, bounce: 0, col: [255, 112, 96] },
    sad:     { open: .72, inT: 0, outT: .55, smile: 0, heart: 0, star: 0, asym: 0, pupil: .44, bounce: 0, col: [110, 172, 255], look: [0, .5] },
    curious: { open: 1.08, inT: 0, outT: 0, smile: 0, heart: 0, star: 0, asym: .3, pupil: .42, bounce: 0, col: [170, 150, 255] },
    sleepy:  { open: .26, inT: 0, outT: .1, smile: 0, heart: 0, star: 0, asym: 0, pupil: .40, bounce: 0, col: [155, 186, 178], look: [0, .3] },
    love:    { open: 1, inT: 0, outT: 0, smile: 0, heart: 1, star: 0, asym: 0, pupil: .40, bounce: .5, col: [255, 134, 166] },
    focused: { open: .86, inT: .12, outT: 0, smile: 0, heart: 0, star: 0, asym: 0, pupil: .34, bounce: 0, col: [90, 200, 250] },
    confused:{ open: .95, inT: 0, outT: 0, smile: 0, heart: 0, star: 0, asym: -.35, pupil: .40, bounce: 0, col: [255, 222, 120] },
  };
  const S = Object.assign({}, C.neutral, { col: C.neutral.col.slice(), lx: 0, ly: 0, blink: 0 });
  let target = C.neutral, talking = false, busy = false;
  let look = [0, 0], nextLook = 0, nextBlink = performance.now() + 2500, blinkStart = -1;
  let cv, ctx, W = 0, H = 0;
  let gaze = null, gazeUntil = 0;          // a point she was asked to look at (your finger)
  let gesture = null, gestureAt = 0;       // "no" = shake side to side, "yes" = happy squint and bob

  function resize() {
    const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    W = cv.width = Math.round(r.width * d); H = cv.height = Math.round(r.height * d);
  }
  const ease = (a, b, k) => a + (b - a) * k;

  function heart(x, y, s) {
    ctx.beginPath(); ctx.moveTo(x, y + s * .35);
    ctx.bezierCurveTo(x - s * 1.1, y - s * .35, x - s * .55, y - s * 1.1, x, y - s * .45);
    ctx.bezierCurveTo(x + s * .55, y - s * 1.1, x + s * 1.1, y - s * .35, x, y + s * .35);
    ctx.closePath(); ctx.fill();
  }
  function star(x, y, r) {
    ctx.beginPath();
    for (let i = 0; i < 8; i++) { const a = i * Math.PI / 4, rr = i % 2 ? r * .32 : r; ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr); }
    ctx.closePath(); ctx.fill();
  }

  function eye(cx, cy, w, h, side, t) {
    const [r, g, b] = S.col.map(Math.round), glow = `rgb(${r},${g},${b})`;
    const open = Math.max(0, Math.min(1.2, S.open * (1 - S.blink) * (1 + S.asym * side)));
    ctx.save();
    ctx.shadowColor = glow; ctx.shadowBlur = w * (talking ? .22 + .14 * Math.sin(t / 90) : .14);   // soft warmth, not neon
    ctx.fillStyle = glow; ctx.strokeStyle = glow;

    if (S.heart > .5) {                                     // love: hearts
      heart(cx, cy + h * .1, w * .62 * (1 + .06 * Math.sin(t / 160)));
    } else if (S.smile > .5) {                              // happy: ^ ^ arcs
      ctx.lineWidth = w * .2; ctx.lineCap = "round";
      ctx.beginPath(); ctx.arc(cx, cy + h * .25, w * .48, Math.PI * 1.12, Math.PI * 1.88); ctx.stroke();
    } else {
      const eh = h * open, rad = Math.min(w, eh) * .48;
      ctx.beginPath(); ctx.roundRect(cx - w / 2, cy - eh / 2, w, Math.max(2, eh), Math.max(1, rad)); ctx.fill();
      ctx.shadowBlur = 0;
      if (eh > h * .3) {                                    // pupil + highlights
        const px = cx + S.lx * w * .22, py = cy + S.ly * eh * .2, pr = w * S.pupil * .5;
        ctx.fillStyle = "rgba(8,30,27,.9)"; ctx.beginPath(); ctx.arc(px, py, pr, 0, 7); ctx.fill();
        ctx.fillStyle = "#f2faf7";
        if (S.star > .5) star(px - pr * .2, py - pr * .25, pr * .75);
        else { ctx.beginPath(); ctx.arc(px - pr * .38, py - pr * .4, pr * .3, 0, 7); ctx.fill(); }
        ctx.globalAlpha = .7; ctx.beginPath(); ctx.arc(px + pr * .35, py + pr * .35, pr * .13, 0, 7); ctx.fill(); ctx.globalAlpha = 1;
      }
      // eyelids: angry = inner corner down, sad = outer corner down; cut out of the eye only
      if (S.inT > .02 || S.outT > .02) {
        ctx.beginPath(); ctx.roundRect(cx - w / 2 - 1, cy - eh / 2 - 1, w + 2, Math.max(2, eh) + 2, Math.max(1, rad)); ctx.clip();
        ctx.globalCompositeOperation = "destination-out";
        const top = cy - eh / 2 - 2, inner = side < 0 ? 1 : -1;
        const dropIn = S.inT * eh * .7, dropOut = S.outT * eh * .7;
        const xi = cx + inner * w * .6, xo = cx - inner * w * .6;
        ctx.beginPath(); ctx.moveTo(xo, top - 4); ctx.lineTo(xi, top - 4);
        ctx.lineTo(xi, top + dropIn); ctx.lineTo(xo, top + dropOut); ctx.closePath(); ctx.fill();
        ctx.globalCompositeOperation = "source-over";
      }
    }
    ctx.restore();
  }

  function frame(t) {
    if (W === 0) resize();
    // ease toward target
    for (const k of ["open", "inT", "outT", "smile", "heart", "star", "asym", "pupil", "bounce"]) S[k] = ease(S[k], target[k], .12);
    S.col = S.col.map((v, i) => ease(v, target.col[i], .08));
    // glances
    if (gaze && t < gazeUntil) { look = gaze; nextLook = gazeUntil; }
    else if (t > nextLook) {
      look = busy || talking ? [0, 0] : [Math.random() * 1.6 - .8, Math.random() * .9 - .45];
      if (target.look) look = target.look.slice();
      nextLook = t + 1200 + Math.random() * 2600;
    }
    S.lx = ease(S.lx, look[0], .15); S.ly = ease(S.ly, look[1], .15);
    // blinks (sleepy blinks slowly)
    if (t > nextBlink && blinkStart < 0) blinkStart = t;
    if (blinkStart >= 0) {
      const dur = target === C.sleepy ? 600 : 170, p = (t - blinkStart) / dur;
      S.blink = p < .5 ? p * 2 : Math.max(0, 2 - p * 2);
      if (p >= 1) { blinkStart = -1; S.blink = 0; nextBlink = t + 1800 + Math.random() * 3500 * (Math.random() < .15 ? .1 : 1); }
    }
    ctx.clearRect(0, 0, W, H);
    let bob = Math.sin(t / 260) * H * .025 * S.bounce + Math.sin(t / 1400) * H * .01, gx = 0, squint = 0;
    if (gesture) {
      const g = (t - gestureAt) / (gesture === "no" ? 600 : 700);
      if (g >= 1) gesture = null;
      else if (gesture === "no") gx = Math.sin(g * Math.PI * 4) * (1 - g) * W * .05;
      else { bob += Math.sin(g * Math.PI * 2) * H * .05; squint = Math.sin(g * Math.PI); }
    }
    const smile0 = S.smile; S.smile = Math.max(S.smile, squint);
    const w = W * .19, h = H * .5, gap = W * .17;
    eye(W / 2 - gap + gx, H * .47 + bob + S.ly * H * .03, w, h, -1, t);
    eye(W / 2 + gap + gx, H * .47 + bob + S.ly * H * .03, w, h, 1, t);
    S.smile = smile0;
    if (target === C.sleepy) {                            // little z's
      ctx.fillStyle = "rgba(155,186,178,.75)"; ctx.font = `${Math.round(H * .09)}px sans-serif`;
      const z = (t / 1200) % 1; ctx.globalAlpha = 1 - z; ctx.fillText("z", W * .78 + z * W * .05, H * .3 - z * H * .15); ctx.globalAlpha = 1;
    }
    if (S.outT > .3 && target === C.sad) {                // a tear
      ctx.fillStyle = "rgba(106,155,204,.9)"; const ty = H * .62 + ((t / 18) % (H * .3));
      ctx.beginPath(); ctx.arc(W / 2 + gap + w * .45, ty, H * .025, 0, 7); ctx.fill();
    }
    requestAnimationFrame(frame);
  }

  if (!CanvasRenderingContext2D.prototype.roundRect) {
    CanvasRenderingContext2D.prototype.roundRect = function (x, y, w, h, r) {
      this.moveTo(x + r, y); this.arcTo(x + w, y, x + w, y + h, r); this.arcTo(x + w, y + h, x, y + h, r);
      this.arcTo(x, y + h, x, y, r); this.arcTo(x, y, x + w, y, r); this.closePath();
    };
  }
  window.Eyes = {
    start(canvas) {
      cv = canvas; ctx = cv.getContext("2d");
      if (window.ResizeObserver) new ResizeObserver(resize).observe(cv); else window.addEventListener("resize", resize);
      requestAnimationFrame(frame);
    },
    lookAt(nx, ny) {                       // -1..1 from the centre of her face
      gaze = [Math.max(-1, Math.min(1, nx)), Math.max(-.6, Math.min(.7, ny))];
      gazeUntil = performance.now() + 1300;
    },
    react(kind) { gesture = kind; gestureAt = performance.now(); },
    set(o) { target = C[o.label] || C.neutral; talking = !!o.talking; busy = !!o.busy; },
  };
})();
