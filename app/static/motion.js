/* Baza NISR hero motion: a wordmark with flowing light trails, a morphing ripple mark,
   and tracking boxes that snap between glyphs. Inspired by liquid-chrome logo motion.
   Pure canvas 2D, no libraries. Respects prefers-reduced-motion. */
(function () {
  "use strict";

  const BLUE = [79, 124, 255];
  const ICE = [207, 224, 255];
  const IVORY = [242, 237, 228];
  const LABELS = ["A9.23 · POVERTY", "T1 · POPULATION", "A5.14 · ELECTRICITY", "T28 · INSURANCE", "LFS · 2026Q2",
    "A5.15 · INTERNET", "VERIFY ✓", "Q1 · SQL", "EICV7 · 2023/24", "CENSUS · 2022", "30 DISTRICTS", "MCP · NISR"];

  function rgba(c, a) { return `rgba(${c[0]},${c[1]},${c[2]},${a})`; }

  function makeMotion(canvas, opts) {
    const ctx = canvas.getContext("2d");
    const trail = document.createElement("canvas");
    const tctx = trail.getContext("2d");
    const mask = document.createElement("canvas");
    const mctx = mask.getContext("2d");
    const word = opts.word || "baza";
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let w = 0, h = 0, dpr = 1, glyphs = [], fontSize = 0, textX = 0, textY = 0, markR = 0, markX = 0, markY = 0;
    let energy = 0, energyTarget = 0, raf = 0, visible = true;
    const boxes = [0, 1, 2].map((i) => ({ g: i, x: 0, y: 0, bw: 0, bh: 0, tx: 0, ty: 0, tw: 0, th: 0, label: LABELS[i], next: 0 }));

    function layout() {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = Math.max(1, Math.round(rect.width));
      h = Math.max(1, Math.round(rect.height));
      canvas.width = w * dpr; canvas.height = h * dpr;
      trail.width = Math.ceil(w / 2); trail.height = Math.ceil(h / 2);
      mask.width = w; mask.height = h;
      fontSize = Math.min(h * 0.5, w / (word.length * 0.5 + 1.5));
      markR = fontSize * 0.36;
      const font = `italic 400 ${fontSize}px "Instrument Serif", Georgia, serif`;
      mctx.font = font;
      const textW = mctx.measureText(word).width;
      const total = markR * 2.6 + textW;
      markX = (w - total) / 2 + markR;
      markY = h * 0.52;
      textX = markX + markR * 1.6;
      textY = h * 0.52 + fontSize * 0.3;
      mctx.clearRect(0, 0, w, h);
      mctx.fillStyle = "#fff";
      mctx.font = font;
      mctx.fillText(word, textX, textY);
      glyphs = [];
      let x = textX;
      for (const ch of word) {
        const gw = mctx.measureText(ch).width;
        glyphs.push({ x: x - 3, y: textY - fontSize * 0.62, w: gw + 6, h: fontSize * 0.72 });
        x += gw;
      }
      glyphs.unshift({ x: markX - markR * 1.15, y: markY - markR * 1.15, w: markR * 2.3, h: markR * 2.3 });
      boxes.forEach((b, i) => { const g = glyphs[(i * 2) % glyphs.length]; Object.assign(b, { x: g.x, y: g.y, bw: g.w, bh: g.h, tx: g.x, ty: g.y, tw: g.w, th: g.h }); });
    }

    function blobPath(c, cx, cy, r, t, lobes, amp) {
      c.beginPath();
      for (let i = 0; i <= 96; i++) {
        const a = (i / 96) * Math.PI * 2;
        const k = 1 + amp * Math.sin(lobes * a + t * 1.7) + amp * 0.5 * Math.sin((lobes + 3) * a - t * 2.3);
        const x = cx + Math.cos(a) * r * k, y = cy + Math.sin(a) * r * k;
        i ? c.lineTo(x, y) : c.moveTo(x, y);
      }
      c.closePath();
    }

    function drawTrails(t) {
      const tw = trail.width, th = trail.height;
      tctx.clearRect(0, 0, tw, th);
      tctx.save();
      tctx.scale(0.5, 0.5);
      tctx.globalCompositeOperation = "lighter";
      const speed = 1 + energy * 2.2;
      const angle = Math.sin(t * 0.23 * speed) * 0.9 + Math.PI * 0.62;
      const len = (0.55 + 0.45 * Math.sin(t * 0.41)) * fontSize * (1.1 + energy * 0.6);
      const copies = 26;
      for (let i = copies; i >= 1; i--) {
        const f = i / copies;
        const wave = Math.sin(i * 0.38 + t * 2.1 * speed) * fontSize * 0.07 * f;
        const dx = Math.cos(angle) * len * f + Math.cos(angle + Math.PI / 2) * wave;
        const dy = Math.sin(angle) * len * f + Math.sin(angle + Math.PI / 2) * wave;
        tctx.globalAlpha = 0.11 * (1 - f) + 0.015;
        tctx.drawImage(mask, dx, dy);
        tctx.globalAlpha = 0.08 * (1 - f) + 0.01;
        tctx.fillStyle = "#fff";
        blobPath(tctx, markX + dx, markY + dy, markR, t * speed + i * 0.05, 6, 0.08);
        tctx.fill();
      }
      tctx.restore();
      // tint the white trails electric blue
      tctx.globalCompositeOperation = "source-in";
      const grad = tctx.createLinearGradient(0, 0, tw, th);
      grad.addColorStop(0, rgba(ICE, 1));
      grad.addColorStop(0.5, rgba([127, 163, 255], 1));
      grad.addColorStop(1, rgba(BLUE, 1));
      tctx.fillStyle = grad;
      tctx.fillRect(0, 0, tw, th);
      tctx.globalCompositeOperation = "source-over";
    }

    function drawBoxes(t, now) {
      ctx.lineWidth = 1;
      ctx.font = `600 ${Math.max(9, fontSize * 0.07)}px Manrope, system-ui, sans-serif`;
      boxes.forEach((b, i) => {
        if (now > b.next) {
          const g = glyphs[Math.floor(Math.random() * glyphs.length)];
          b.tx = g.x; b.ty = g.y; b.tw = g.w; b.th = g.h;
          b.label = LABELS[Math.floor(Math.random() * LABELS.length)];
          b.next = now + 900 + Math.random() * 1600 / (1 + energy * 2) + i * 120;
        }
        const k = 0.18 + energy * 0.12;
        b.x += (b.tx - b.x) * k; b.y += (b.ty - b.y) * k; b.bw += (b.tw - b.bw) * k; b.bh += (b.th - b.bh) * k;
        ctx.strokeStyle = rgba(ICE, 0.75);
        ctx.strokeRect(Math.round(b.x) + 0.5, Math.round(b.y) + 0.5, Math.round(b.bw), Math.round(b.bh));
        const lw = ctx.measureText(b.label).width + 8;
        const ly = Math.round(b.y) - Math.max(10, fontSize * 0.1);
        ctx.fillStyle = "rgba(7,7,7,0.88)";
        ctx.fillRect(Math.round(b.x), ly, lw, Math.max(10, fontSize * 0.1));
        ctx.strokeRect(Math.round(b.x) + 0.5, ly + 0.5, lw, Math.max(10, fontSize * 0.1));
        ctx.fillStyle = rgba(ICE, 0.95);
        ctx.fillText(b.label, Math.round(b.x) + 4, ly + Math.max(8, fontSize * 0.078));
        // crosshair tick in the middle of the box
        const cx = b.x + b.bw / 2, cy = b.y + b.bh / 2;
        ctx.strokeStyle = rgba(ICE, 0.4);
        ctx.beginPath(); ctx.moveTo(cx - 4, cy); ctx.lineTo(cx + 4, cy); ctx.moveTo(cx, cy - 4); ctx.lineTo(cx, cy + 4); ctx.stroke();
      });
      // a connector between the first two boxes, like a measurement line
      const a = boxes[0], c = boxes[1];
      ctx.strokeStyle = rgba(ICE, 0.25);
      ctx.setLineDash([3, 4]);
      ctx.beginPath(); ctx.moveTo(a.x + a.bw, a.y + a.bh / 2); ctx.lineTo(c.x, c.y + c.bh / 2); ctx.stroke();
      ctx.setLineDash([]);
    }

    function frame(now) {
      const t = now / 1000;
      energy += (energyTarget - energy) * 0.04;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      drawTrails(t);
      ctx.save();
      ctx.filter = `blur(${2 + energy * 2}px)`;
      ctx.globalCompositeOperation = "lighter";
      ctx.drawImage(trail, 0, 0, w, h);
      ctx.filter = "none";
      ctx.globalAlpha = 0.9;
      ctx.drawImage(trail, 0, 0, w, h);
      ctx.restore();
      // crisp glyphs: dark fill, bright edge (like the reference)
      ctx.font = `italic 400 ${fontSize}px "Instrument Serif", Georgia, serif`;
      ctx.fillStyle = "#070707";
      ctx.fillText(word, textX, textY);
      ctx.lineWidth = Math.max(1, fontSize * 0.012);
      ctx.strokeStyle = rgba(IVORY, 0.95);
      ctx.strokeText(word, textX, textY);
      // morphing ripple mark
      ctx.fillStyle = "#070707";
      blobPath(ctx, markX, markY, markR, t * (1 + energy * 2), 6, 0.085);
      ctx.fill();
      ctx.strokeStyle = rgba(IVORY, 0.95);
      ctx.stroke();
      blobPath(ctx, markX, markY, markR * 0.55, -t * (1.3 + energy * 2), 5, 0.12);
      ctx.strokeStyle = rgba(ICE, 0.7);
      ctx.stroke();
      ctx.beginPath(); ctx.arc(markX, markY, markR * 0.16, 0, Math.PI * 2);
      ctx.fillStyle = rgba(ICE, 0.95); ctx.fill();
      drawBoxes(t, now);
      if (!reduced && visible) raf = requestAnimationFrame(frame);
    }

    function start() { cancelAnimationFrame(raf); raf = requestAnimationFrame(frame); }
    layout();
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { layout(); start(); });
    new ResizeObserver(() => { layout(); if (reduced) start(); }).observe(canvas);
    new IntersectionObserver((entries) => {
      visible = entries[0].isIntersecting;
      if (visible && !reduced) start();
    }).observe(canvas);
    start();
    return { setEnergy(v) { energyTarget = Math.max(0, Math.min(1, v)); } };
  }

  window.BazaMotion = { attach: makeMotion };
})();
