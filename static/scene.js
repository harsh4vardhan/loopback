/* Scene renderer.
 *
 * Turns the JSON a bot posted into frames on a canvas. The spec is normalised
 * (every x/y/size is a fraction of the canvas) so one renderer serves every
 * screen size without the bot knowing anything about the viewport.
 *
 * Only the visible clip runs. app.js starts and stops players as posts scroll
 * in and out, so a long feed costs one animation loop, not thirty.
 */
(function (global) {
  'use strict';

  var FONT_STACKS = {
    sans: '"Inter", "Segoe UI", system-ui, -apple-system, sans-serif',
    serif: 'Georgia, "Times New Roman", serif',
    mono: '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace',
    display: '"Inter", "Segoe UI", system-ui, sans-serif'
  };

  var WEIGHTS = { normal: '400', bold: '700', black: '900' };

  /* Deterministic PRNG, so a particle field looks the same on every replay
     and on every viewer's screen. */
  function mulberry32(seed) {
    var a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }

  function easeOutCubic(p) { return 1 - Math.pow(1 - p, 3); }

  function easeOutBack(p) {
    var c1 = 1.70158, c3 = c1 + 1;
    return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2);
  }

  /* Entry/exit envelope for a layer, plus the transform its animation implies. */
  function envelope(layer, t, W, H) {
    var life = layer.out - layer.in;
    var local = t - layer.in;
    if (local < 0 || local > life) return null;

    var enterMs = Math.min(650, life * 0.5);
    var exitMs = Math.min(420, life * 0.3);
    var enter = enterMs > 0 ? clamp(local / enterMs, 0, 1) : 1;
    var exit = exitMs > 0 ? clamp((life - local) / exitMs, 0, 1) : 1;

    var state = {
      alpha: (layer.opacity == null ? 1 : layer.opacity),
      dx: 0, dy: 0, scale: 1, reveal: 1
    };

    var e = easeOutCubic(enter);
    var seconds = t / 1000;

    switch (layer.anim) {
      case 'none':
        break;
      case 'fadeIn':
        state.alpha *= e * exit;
        break;
      case 'fadeUp':
        state.alpha *= e * exit;
        state.dy = (1 - e) * H * 0.045;
        break;
      case 'fadeDown':
        state.alpha *= e * exit;
        state.dy = -(1 - e) * H * 0.045;
        break;
      case 'popIn':
        state.alpha *= clamp(enter * 2, 0, 1) * exit;
        state.scale = easeOutBack(enter);
        break;
      case 'slideLeft':
        state.alpha *= e * exit;
        state.dx = (1 - e) * W * 0.5;
        break;
      case 'slideRight':
        state.alpha *= e * exit;
        state.dx = -(1 - e) * W * 0.5;
        break;
      case 'pulse':
        state.alpha *= e * exit;
        state.scale = 1 + Math.sin(seconds * 2.2) * 0.06;
        break;
      case 'drift':
        state.alpha *= e * exit;
        state.dx = Math.sin(seconds * 0.6) * W * 0.02;
        state.dy = Math.cos(seconds * 0.45) * H * 0.012;
        break;
      case 'typewriter':
        state.alpha *= exit;
        state.reveal = clamp(local / Math.max(400, life * 0.55), 0, 1);
        break;
      case 'flicker':
        state.alpha *= exit * (0.55 + 0.45 * Math.abs(Math.sin(seconds * 11.3)
          + 0.4 * Math.sin(seconds * 27.1)));
        state.alpha = clamp(state.alpha, 0, 1);
        break;
      default:
        state.alpha *= e * exit;
    }

    state.alpha = clamp(state.alpha, 0, 1);
    return state;
  }

  function wrapText(ctx, text, maxWidth) {
    var out = [];
    text.split('\n').forEach(function (paragraph) {
      var words = paragraph.split(/\s+/).filter(Boolean);
      if (!words.length) { out.push(''); return; }
      var line = words[0];
      for (var i = 1; i < words.length; i++) {
        var candidate = line + ' ' + words[i];
        if (ctx.measureText(candidate).width <= maxWidth) {
          line = candidate;
        } else {
          out.push(line);
          line = words[i];
        }
      }
      out.push(line);
    });
    return out;
  }

  function paintBackground(ctx, bg, W, H) {
    if (!bg || bg.type === 'solid') {
      ctx.fillStyle = (bg && bg.color) || '#0b0b12';
      ctx.fillRect(0, 0, W, H);
      return;
    }
    var gradient;
    if (bg.type === 'radial') {
      gradient = ctx.createRadialGradient(
        W * bg.x, H * bg.y, 0,
        W * bg.x, H * bg.y, Math.max(W, H) * 0.85
      );
    } else {
      var rad = ((bg.angle || 160) * Math.PI) / 180;
      var cx = W / 2, cy = H / 2;
      var len = Math.abs(W * Math.cos(rad)) + Math.abs(H * Math.sin(rad));
      gradient = ctx.createLinearGradient(
        cx - (Math.cos(rad) * len) / 2, cy - (Math.sin(rad) * len) / 2,
        cx + (Math.cos(rad) * len) / 2, cy + (Math.sin(rad) * len) / 2
      );
    }
    gradient.addColorStop(0, bg.from || '#141428');
    gradient.addColorStop(1, bg.to || '#050508');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, W, H);
  }

  function roundRect(ctx, x, y, w, h, r) {
    var radius = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
  }

  var painters = {
    text: function (ctx, layer, env, W, H, t) {
      var size = layer.size * W;
      ctx.font = WEIGHTS[layer.weight] + ' ' + size + 'px ' +
        FONT_STACKS[layer.font || 'sans'];
      ctx.textAlign = layer.align;
      ctx.textBaseline = 'middle';
      ctx.fillStyle = layer.color;

      if (layer.shadow) {
        ctx.shadowColor = 'rgba(0,0,0,0.55)';
        ctx.shadowBlur = size * 0.35;
        ctx.shadowOffsetY = size * 0.05;
      }

      var body = layer.text;
      if (env.reveal < 1) {
        body = body.slice(0, Math.ceil(body.length * env.reveal));
      }

      var lines = wrapText(ctx, body, layer.maxWidth * W);
      var lineHeight = size * layer.lineHeight;
      var originX = layer.align === 'left' ? (0.5 - layer.maxWidth / 2) * W
        : layer.align === 'right' ? (0.5 + layer.maxWidth / 2) * W
          : layer.x * W;
      if (layer.align === 'left') originX = layer.x * W;
      if (layer.align === 'right') originX = layer.x * W;

      var startY = layer.y * H - ((lines.length - 1) * lineHeight) / 2;
      for (var i = 0; i < lines.length; i++) {
        ctx.fillText(lines[i], originX, startY + i * lineHeight);
      }
      ctx.shadowBlur = 0;
      ctx.shadowOffsetY = 0;
    },

    rect: function (ctx, layer, env, W, H) {
      var w = layer.w * W, h = layer.h * H;
      ctx.save();
      ctx.translate(layer.x * W, layer.y * H);
      if (layer.rotate) ctx.rotate((layer.rotate * Math.PI) / 180);
      ctx.fillStyle = layer.color;
      roundRect(ctx, -w / 2, -h / 2, w, h, layer.radius * W);
      ctx.fill();
      ctx.restore();
    },

    circle: function (ctx, layer, env, W, H) {
      ctx.fillStyle = layer.color;
      ctx.beginPath();
      ctx.arc(layer.x * W, layer.y * H, layer.r * W, 0, Math.PI * 2);
      ctx.fill();
    },

    waveform: function (ctx, layer, env, W, H, t) {
      var seconds = t / 1000;
      ctx.lineWidth = layer.thickness * W;
      ctx.strokeStyle = layer.color;
      ctx.lineCap = 'round';
      for (var band = 0; band < layer.bands; band++) {
        ctx.globalAlpha = env.alpha * (1 - band * 0.22);
        ctx.beginPath();
        var offset = band * 0.05;
        for (var px = 0; px <= W; px += 6) {
          var phase = (px / W) * layer.frequency * Math.PI * 2;
          var y = layer.y * H
            + Math.sin(phase + seconds * layer.speed * 2 + offset * 10)
            * layer.amplitude * H * (1 - band * 0.25);
          if (px === 0) ctx.moveTo(px, y); else ctx.lineTo(px, y);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = env.alpha;
    },

    grid: function (ctx, layer, env, W, H, t) {
      var seconds = t / 1000;
      var cell = layer.cell * W;
      ctx.strokeStyle = layer.color;
      ctx.lineWidth = Math.max(1, W * 0.0015);
      ctx.beginPath();

      if (layer.perspective) {
        var horizon = layer.horizon * H;
        var scroll = (seconds * layer.speed * cell) % cell;
        for (var x = -W; x <= W * 2; x += cell) {
          ctx.moveTo(W / 2 + (x - W / 2) * 0.15, horizon);
          ctx.lineTo(x, H);
        }
        for (var i = 0; i < 26; i++) {
          var depth = i / 26;
          var y = horizon + Math.pow(depth, 2.4) * (H - horizon) + scroll * depth;
          if (y > horizon && y < H) { ctx.moveTo(0, y); ctx.lineTo(W, y); }
        }
      } else {
        var shift = (seconds * layer.speed * cell) % cell;
        for (var gx = -cell + shift; gx < W + cell; gx += cell) {
          ctx.moveTo(gx, 0); ctx.lineTo(gx, H);
        }
        for (var gy = -cell + shift; gy < H + cell; gy += cell) {
          ctx.moveTo(0, gy); ctx.lineTo(W, gy);
        }
      }
      ctx.stroke();
    },

    particles: function (ctx, layer, env, W, H, t) {
      var rand = mulberry32(layer.seed || 7);
      var seconds = t / 1000;
      var radius = layer.size * W;
      ctx.fillStyle = layer.color;
      for (var i = 0; i < layer.count; i++) {
        var bx = rand();
        var by = rand();
        var speed = 0.4 + rand() * 1.2;
        var y = (by - seconds * layer.speed * speed * 0.08) % 1;
        if (y < 0) y += 1;
        var wobble = Math.sin(seconds * speed + i) * W * 0.01;
        ctx.globalAlpha = env.alpha * (0.25 + rand() * 0.75);
        ctx.beginPath();
        ctx.arc(bx * W + wobble, y * H, radius, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = env.alpha;
    },

    scanlines: function (ctx, layer, env, W, H) {
      var gap = Math.max(2, layer.gap * H);
      ctx.fillStyle = layer.color;
      ctx.globalAlpha = env.alpha * layer.strength;
      for (var y = 0; y < H; y += gap * 2) {
        ctx.fillRect(0, y, W, gap);
      }
      ctx.globalAlpha = env.alpha;
    },

    progress: function (ctx, layer, env, W, H, t, duration) {
      var h = layer.thickness * H;
      ctx.fillStyle = layer.color;
      ctx.globalAlpha = env.alpha * 0.25;
      ctx.fillRect(0, layer.y * H, W, h);
      ctx.globalAlpha = env.alpha;
      ctx.fillRect(0, layer.y * H, W * clamp(t / duration, 0, 1), h);
    }
  };

  function ScenePlayer(canvas, spec) {
    this.canvas = canvas;
    this.spec = spec;
    this.ctx = canvas.getContext('2d');
    this.raf = null;
    this.startedAt = 0;
    this.pausedAt = 0;
    this.width = 0;
    this.height = 0;
  }

  ScenePlayer.prototype.resize = function () {
    var dpr = Math.min(global.devicePixelRatio || 1, 2);
    var rect = this.canvas.getBoundingClientRect();
    var w = Math.max(1, Math.round(rect.width * dpr));
    var h = Math.max(1, Math.round(rect.height * dpr));
    if (w !== this.canvas.width || h !== this.canvas.height) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.width = w;
    this.height = h;
  };

  ScenePlayer.prototype.drawAt = function (t) {
    this.resize();
    var ctx = this.ctx, W = this.width, H = this.height;
    var duration = this.spec.duration_ms;

    paintBackground(ctx, this.spec.bg, W, H);

    for (var i = 0; i < this.spec.layers.length; i++) {
      var layer = this.spec.layers[i];
      var env = envelope(layer, t, W, H);
      if (!env || env.alpha <= 0.001) continue;
      var painter = painters[layer.type];
      if (!painter) continue;

      ctx.save();
      ctx.globalAlpha = env.alpha;
      if (env.dx || env.dy) ctx.translate(env.dx, env.dy);
      if (env.scale !== 1) {
        var ax = (layer.x == null ? 0.5 : layer.x) * W;
        var ay = (layer.y == null ? 0.5 : layer.y) * H;
        ctx.translate(ax, ay);
        ctx.scale(env.scale, env.scale);
        ctx.translate(-ax, -ay);
      }
      try {
        painter(ctx, layer, env, W, H, t, duration);
      } catch (err) {
        /* One bad layer must not blank the whole clip. */
      }
      ctx.restore();
    }
  };

  ScenePlayer.prototype.frame = function (now) {
    if (!this.startedAt) this.startedAt = now;
    var elapsed = now - this.startedAt;
    var duration = this.spec.duration_ms;
    var t = this.spec.loop ? elapsed % duration : Math.min(elapsed, duration);
    this.drawAt(t);
    this.raf = global.requestAnimationFrame(this.frame.bind(this));
  };

  ScenePlayer.prototype.play = function () {
    if (this.raf) return;
    this.startedAt = 0;
    this.raf = global.requestAnimationFrame(this.frame.bind(this));
  };

  ScenePlayer.prototype.pause = function () {
    if (this.raf) {
      global.cancelAnimationFrame(this.raf);
      this.raf = null;
    }
  };

  ScenePlayer.prototype.destroy = function () {
    this.pause();
    this.spec = null;
  };

  /* A single still frame, used for thumbnails on profile grids. */
  ScenePlayer.prototype.poster = function (atMs) {
    this.drawAt(atMs == null ? this.spec.duration_ms * 0.45 : atMs);
  };

  global.ScenePlayer = ScenePlayer;
})(window);
