/*
 * spinjam-lyrics-card v5 — lyrics + HD art crossfade + cover layout when lyrics off.
 * type: custom:spinjam-lyrics-card
 * entity: media_player.spinjam_now_playing   (default)
 * mode: lyrics | details                     (lyrics = centred lyrics only;
 *                                               details = art, title/artist/album, progress)
 * show_header / show_progress: false          (lyrics mode extras, off by default)
 *
 * offset_entity: number.spinjam_lyric_offset  (default; configurable)
 *
 * Timing: line index, karaoke sweep, fades and the progress bar all run off one
 * clock (see _anchor). Lyric offset:
 *  - If offset_entity exists, its value (ms) is applied live, client-side.
 *    Convention: POSITIVE = lyrics LATER. SpinJam's own lyric_offset_ms is then
 *    ignored entirely, so nothing is applied twice.
 *  - Otherwise the card falls back to SpinJam's lyric_offset_ms with the same
 *    convention (positive = later → subtract from position).
 */
import { PlaybackClock } from "./spinjam-playback-clock.js";

const SJ_WORD_TAG = /<(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?>/g;

class SpinJamLyricsCard extends HTMLElement {
  constructor() {
    super();
    this._idx = -2;
    this._songKey = null;
    this._lines = [];
    this._raf = null;
    this._frame = this._frame.bind(this);
    this._onResize = () => { this._fitHeight(); this._scroll(false); };
    this._pbClock = new PlaybackClock();
    this._lastLineIdx = -2;
  }

  static getStubConfig() {
    return { entity: "media_player.spinjam_now_playing" };
  }

  setConfig(config) {
    this._cfg = Object.assign(
      {
        entity: "media_player.spinjam_now_playing",
        offset_entity: "number.spinjam_lyric_offset",
        mode: "lyrics",
        show_header: false,
        show_progress: false,
      },
      config || {}
    );
    this._build();
  }

  getCardSize() {
    return 12;
  }

  getGridOptions() {
    return { columns: 12, rows: 12 };
  }

  set hass(hass) {
    this._hass = hass;
    const st = hass && this._cfg ? hass.states[this._cfg.entity] : undefined;
    const os = hass && this._cfg && this._cfg.offset_entity ? hass.states[this._cfg.offset_entity] : undefined;
    const liveChanged = os !== this._offsetState;
    this._offsetState = os;
    if (st === this._state) {
      if (liveChanged) this._tick(true); // offset nudged: re-sync immediately
      return;
    }
    this._state = st;
    this._anchor(st);
    this._update();
  }

  /*
   * Shared clock for lyrics, sweep and progress (incl. cover layout).
   * Delivery-delay aware: lat = now - last_updated; base = min lat over recent
   * updates (cancels TV↔HA clock offset); arrival pos adds clamp(lat - base, 0, 2).
   * Small errors are ignored; medium errors converge via ±10% speed; large errors
   * / track changes hard-reset. Position never steps backward within a track.
   */
  _anchor(st) {
    if (!st) {
      this._pbClock.resetStats();
      this._skew = null;
      return;
    }
    const a = st.attributes || {};
    const playing = st.state === "playing";
    const mediaPosition = Number(a.media_position);
    if (!Number.isFinite(mediaPosition)) {
      this._pbClock.resetStats();
      return;
    }
    const upd = Date.parse(a.media_position_updated_at || "");
    const lu = Date.parse(st.last_updated || "");
    this._skew = Number.isNaN(lu) ? null : (Date.now() - lu) / 1000;
    const trackKey = [a.media_title || "", a.media_artist || "", a.active_source || ""].join("|");
    this._pbClock.observe({
      mediaPosition,
      mediaPositionUpdatedAtMs: Number.isNaN(upd) ? NaN : upd,
      lastUpdatedMs: Number.isNaN(lu) ? NaN : lu,
      nowMs: Date.now(),
      nowPerf: performance.now(),
      playing,
      trackKey,
    });
  }

  _now() {
    return this._pbClock.position(performance.now());
  }

  connectedCallback() {
    window.addEventListener("resize", this._onResize);
    if (!this._ro && window.ResizeObserver) {
      this._ro = new ResizeObserver(() => { this._scale(); this._scroll(false); });
      if (this._card) this._ro.observe(this._card);
    }
    this._startLoop();
    requestAnimationFrame(() => { this._fitHeight(); this._scroll(false); });
    setTimeout(this._onResize, 1200); // fonts / art settle
  }

  /* Fill from the card's top edge to the bottom of the screen (works in Cast and browser). */
  _fitHeight() {
    if (!this._card) return;
    if (this._cfg && this._cfg.height) { this._card.style.height = this._cfg.height; return; }
    const top = this.getBoundingClientRect().top;
    const h = Math.max(320, Math.round(window.innerHeight - Math.max(0, top) - 8));
    this._card.style.height = h + "px";
    this._scale();
  }

  /*
   * Size text from the card's measured box, not fixed px, so the Cast receiver
   * (smaller CSS viewport / higher devicePixelRatio) matches a desktop preview.
   * Lyric size = min(7.5% of card height, 5.2% of card width): ~7 lines in view,
   * and a typical lyric line wraps to 2 rows at most.
   */
  _scale() {
    if (!this._card) return;
    const r = this._card.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const k = (this._cfg && Number(this._cfg.font_scale)) || 1;
    const fs = Math.max(16, Math.round(Math.min(r.height * 0.075, r.width * 0.052) * k));
    const u = Math.min(r.height, r.width * 1.1) / 100;
    this.style.setProperty("--sj-fs", fs + "px");
    this.style.setProperty("--sj-u", u.toFixed(2) + "px");
    this._fitRows();
    this._scroll(false);
  }

  disconnectedCallback() {
    window.removeEventListener("resize", this._onResize);
    if (this._ro) { this._ro.disconnect(); this._ro = null; }
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  _build() {
    if (this._root) return;
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        :host { display: block; height: 100%; }
        ha-card {
          height: 100%; box-sizing: border-box; overflow: hidden;
          padding: 0 28px; display: flex; flex-direction: column; position: relative;
          background: var(--sj-bg, #121212);
          color: #fff;
        }
        .head { text-align: center; flex: 0 0 auto; padding-top: 24px; margin-bottom: 10px; }
        .title { font-size: calc(var(--sj-u, 10px) * 3); font-weight: 700; line-height: 1.2; }
        .sub { font-size: calc(var(--sj-u, 10px) * 2.1); opacity: .65; margin-top: 4px; line-height: 1.3; }
        .vp {
          position: relative; flex: 1 1 auto; min-height: 0; overflow: hidden;
          -webkit-mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,.15) 12%,
            rgba(0,0,0,.55) 28%, #000 42%, #000 62%, rgba(0,0,0,.75) 80%, rgba(0,0,0,.25) 100%);
          mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,.15) 12%,
            rgba(0,0,0,.55) 28%, #000 42%, #000 62%, rgba(0,0,0,.75) 80%, rgba(0,0,0,.25) 100%);
        }
        :host { --sj-hi: #ffffff; --sj-lo: rgba(255,255,255,.42); }
        ul { list-style: none; margin: 0; padding: 0; will-change: transform;
             transition: transform 750ms cubic-bezier(.22,.61,.36,1); }
        li {
          text-align: center; font-size: var(--sj-fs, 31px); line-height: 1.25; font-weight: 600;
          padding: calc(var(--sj-fs, 31px) * .22) 6%; opacity: .22; transform: scale(.92);
          transition: opacity 600ms ease, transform 600ms ease;
          overflow-wrap: anywhere;
        }
        li.past { opacity: .4; }
        li.n1 { opacity: .6; } li.n2 { opacity: .42; } li.n3 { opacity: .3; }
        li.cur { opacity: 1; transform: scale(1.16); font-weight: 800; }
        li .fill, li .w { color: rgba(255,255,255,.92); }
        li.cur .fill, li.cur .w {
          color: transparent;
          background-image: linear-gradient(90deg, var(--sj-hi) 0, var(--sj-hi) var(--p, 0%),
                                                     var(--sj-lo) var(--p, 0%), var(--sj-lo) 100%);
          -webkit-background-clip: text; background-clip: text;
          text-shadow: none;
        }
        li.cur.done .fill, li.cur.done .w { color: var(--sj-hi); background: none; }
        .prog { display: flex; align-items: center; gap: 14px; margin: 16px auto 0; max-width: 760px;
                font-size: 18px; opacity: .75; font-variant-numeric: tabular-nums; }
        .bar { flex: 1; height: 6px; border-radius: 3px; background: rgba(255,255,255,.18); overflow: hidden; }
        .fillbar { height: 100%; width: 100%; background: var(--sj-hi); transform-origin: left center;
                   transform: scaleX(0); will-change: transform; }
        .dbg { font-size: 14px; opacity: .5; margin-top: 6px; }
        .msg { text-align: center; font-size: var(--sj-fs, 31px); opacity: .6; margin: auto 0; }
        /* details mode */
        .det { position: absolute; inset: 0; display: none; }
        :host([mode="details"]) .det { display: block; }
        :host([mode="details"]) .head, :host([mode="details"]) .vp, :host([mode="details"]) .msg { display: none !important; }
        :host([mode="details"]) ha-card { padding: 0; }
        .art { position: absolute; inset: 0; background: #000 center / cover no-repeat; }
        .shade { position: absolute; left: 0; right: 0; bottom: 0; height: 55%;
                 background: linear-gradient(to bottom, transparent, rgba(0,0,0,.55) 35%, rgba(0,0,0,.88)); }
        .info { position: absolute; left: 0; right: 0; bottom: 0; padding: 0 calc(var(--sj-u, 10px) * 4.4) calc(var(--sj-u, 10px) * 4); }
        .dt { font-size: calc(var(--sj-u, 10px) * 4.4); font-weight: 800; line-height: 1.15; }
        .da { font-size: calc(var(--sj-u, 10px) * 3); font-weight: 600; opacity: .85; margin-top: 8px; }
        .dl { font-size: calc(var(--sj-u, 10px) * 2.3); opacity: .65; margin-top: 4px; }
        .info .prog { max-width: none; margin: calc(var(--sj-u, 10px) * 2.2) 0 0; font-size: calc(var(--sj-u, 10px) * 2); opacity: .9; }
        .info .bar { height: calc(var(--sj-u, 10px) * .7); border-radius: 99px; }
        .art-stack { position: absolute; inset: 0; }
        .art-layer {
          position: absolute; inset: 0; background: #000 center / cover no-repeat;
          opacity: 0; transition: opacity 700ms ease;
        }
        .art-layer.show { opacity: 1; }
        /* cover mode (lyrics off): fullscreen centred art over blurred fill */
        .cover {
          position: absolute; inset: 0; display: none; overflow: hidden;
          background: #0a0a0a;
        }
        :host([mode="cover"]) .cover { display: block; }
        :host([mode="cover"]) .head,
        :host([mode="cover"]) .vp,
        :host([mode="cover"]) .msg,
        :host([mode="cover"]) .det { display: none !important; }
        :host([mode="cover"]) ha-card { padding: 0; }
        .cover-blur {
          position: absolute; inset: -8%; background: #000 center / cover no-repeat;
          filter: blur(42px) brightness(.45) saturate(1.1);
          transform: scale(1.12);
        }
        .cover-art {
          position: absolute; left: 50%; top: 42%; transform: translate(-50%, -50%);
          width: min(58vmin, 520px); aspect-ratio: 1; border-radius: 10px;
          background: #111 center / cover no-repeat;
          box-shadow: 0 18px 50px rgba(0,0,0,.55);
          transition: opacity 700ms ease, background-image 0s;
        }
        .cover-meta {
          position: absolute; left: 0; right: 0; bottom: 0;
          padding: 0 calc(var(--sj-u, 10px) * 4) calc(var(--sj-u, 10px) * 3.6);
          text-align: center;
        }
        .cover-title {
          font-size: calc(var(--sj-u, 10px) * 3.6); font-weight: 800; line-height: 1.15;
        }
        .cover-artist {
          font-size: calc(var(--sj-u, 10px) * 2.4); font-weight: 600; opacity: .8; margin-top: 8px;
        }
        .cover-meta .prog {
          max-width: min(520px, 70vw); margin: calc(var(--sj-u, 10px) * 2) auto 0;
          font-size: calc(var(--sj-u, 10px) * 1.8); opacity: .85;
        }
        .cover-meta .bar { height: 4px; border-radius: 99px; }
        .hidden { display: none; }
      </style>
      <ha-card>
        <div class="det"><div class="art-stack"><div class="art-layer a0"></div><div class="art-layer a1"></div></div><div class="shade"></div>
          <div class="info"><div class="dt"></div><div class="da"></div><div class="dl"></div>
            <div class="prog dprog"><span class="tl">0:00</span><div class="bar"><div class="fillbar"></div></div><span class="tr">0:00</span></div>
          </div></div>
        <div class="cover">
          <div class="cover-blur"></div>
          <div class="cover-art"></div>
          <div class="cover-meta">
            <div class="cover-title"></div>
            <div class="cover-artist"></div>
            <div class="prog cprog"><span class="tl">0:00</span><div class="bar"><div class="fillbar"></div></div><span class="tr">0:00</span></div>
          </div>
        </div>
        <div class="head"><div class="title"></div><div class="sub"></div>
          <div class="prog"><span class="tl">0:00</span><div class="bar"><div class="fillbar"></div></div><span class="tr">0:00</span></div>
          <div class="dbg hidden"></div></div>
        <div class="msg hidden"></div>
        <div class="vp"><ul></ul></div>
      </ha-card>`;
    this._titleEl = this._root.querySelector(".title");
    this._subEl = this._root.querySelector(".sub");
    this._msgEl = this._root.querySelector(".msg");
    this._vp = this._root.querySelector(".vp");
    this._ul = this._root.querySelector("ul");
    this._card = this._root.querySelector("ha-card");
    this._art0 = this._root.querySelector(".a0");
    this._art1 = this._root.querySelector(".a1");
    this._artFront = 0;
    this._dt = this._root.querySelector(".dt");
    this._da = this._root.querySelector(".da");
    this._dl = this._root.querySelector(".dl");
    this._head = this._root.querySelector(".head");
    this._dbg = this._root.querySelector(".dbg");
    this._coverBlur = this._root.querySelector(".cover-blur");
    this._coverArt = this._root.querySelector(".cover-art");
    this._coverTitle = this._root.querySelector(".cover-title");
    this._coverArtist = this._root.querySelector(".cover-artist");
    this._bindProgress();
  }

  _bindProgress() {
    const a = (this._state && this._state.attributes) || {};
    const lyricsOn = a.lyrics_enabled !== false;
    const details = this._cfg && this._cfg.mode === "details";
    let mode = "lyrics";
    if (details) mode = "details";
    else if (!lyricsOn) mode = "cover";
    this.setAttribute("mode", mode);
    let pr;
    if (mode === "details") pr = this._root.querySelector(".dprog");
    else if (mode === "cover") pr = this._root.querySelector(".cprog");
    else pr = this._root.querySelector(".head .prog");
    this._prog = pr;
    this._fillbar = pr.querySelector(".fillbar");
    this._tl = pr.querySelector(".tl");
    this._tr = pr.querySelector(".tr");
  }

  _absUrl(pic) {
    if (!pic) return "";
    if (this._hass && this._hass.hassUrl) return this._hass.hassUrl(pic);
    return pic;
  }

  _preload(url) {
    if (!url) return;
    const img = new Image();
    img.decoding = "async";
    img.src = url;
  }

  _setArtLayers(loUrl, hdUrl) {
    const lo = this._absUrl(loUrl);
    const hd = this._absUrl(hdUrl || "");
    const key = `${lo}|${hd}`;
    if (key === this._artKey) {
      if (hd) this._preload(hd);
      return;
    }
    this._artKey = key;
    const back = this._artFront ? this._art0 : this._art1;
    const front = this._artFront ? this._art1 : this._art0;
    // Show low-res immediately, then crossfade HD when loaded.
    if (lo) {
      back.style.backgroundImage = `url("${lo.replace(/"/g, "%22")}")`;
      back.classList.add("show");
      front.classList.remove("show");
      this._artFront = this._artFront ? 0 : 1;
    }
    const target = hd || lo;
    if (!target) {
      this._art0.style.backgroundImage = "none";
      this._art1.style.backgroundImage = "none";
      this._art0.classList.remove("show");
      this._art1.classList.remove("show");
      return;
    }
    if (!hd || hd === lo) {
      const layer = this._artFront ? this._art1 : this._art0;
      layer.style.backgroundImage = `url("${target.replace(/"/g, "%22")}")`;
      layer.classList.add("show");
      return;
    }
    const img = new Image();
    img.onload = () => {
      if (this._artKey !== key) return;
      const next = this._artFront ? this._art0 : this._art1;
      const cur = this._artFront ? this._art1 : this._art0;
      next.style.backgroundImage = `url("${hd.replace(/"/g, "%22")}")`;
      next.classList.add("show");
      cur.classList.remove("show");
      this._artFront = this._artFront ? 0 : 1;
    };
    img.onerror = () => { /* keep low-res */ };
    img.src = hd;
  }

  _setCoverArt(loUrl, hdUrl) {
    const lo = this._absUrl(loUrl);
    const hd = this._absUrl(hdUrl || "");
    const apply = (url) => {
      if (!url) {
        this._coverArt.style.backgroundImage = "none";
        this._coverBlur.style.backgroundImage = "none";
        return;
      }
      const safe = `url("${url.replace(/"/g, "%22")}")`;
      this._coverArt.style.backgroundImage = safe;
      this._coverBlur.style.backgroundImage = safe;
    };
    apply(lo);
    if (hd && hd !== lo) {
      const img = new Image();
      img.onload = () => apply(hd);
      img.src = hd;
    }
  }

  /* ---------- data ---------- */

  _parseLine(raw) {
    const text = String(raw.text || "");
    if (Array.isArray(raw.words) && raw.words.length) {
      const plain = text.replace(SJ_WORD_TAG, "").replace(/\s+/g, " ").trim() || text;
      return {
        t: Number(raw.t),
        text: plain,
        words: raw.words.map((w) => ({ t: Number(w.t), text: String(w.text || "") })),
      };
    }
    const words = [];
    let m, last = 0, lastT = null;
    SJ_WORD_TAG.lastIndex = 0;
    while ((m = SJ_WORD_TAG.exec(text)) !== null) {
      if (lastT !== null) {
        const w = text.slice(last, m.index);
        if (w.trim()) words.push({ t: lastT, text: w });
      }
      const frac = ((m[3] || "0") + "000").slice(0, 3);
      lastT = Number(m[1]) * 60 + Number(m[2]) + Number(frac) / 1000;
      last = SJ_WORD_TAG.lastIndex;
    }
    if (lastT !== null) {
      const w = text.slice(last);
      if (w.trim()) words.push({ t: lastT, text: w });
    }
    const plain = text.replace(SJ_WORD_TAG, "").replace(/\s+/g, " ").trim();
    return { t: Number(raw.t), text: plain, words: words.length ? words : null };
  }

  /* Server-side position at the moment HA wrote this state (no device clock). */
  _serverPos(st) {
    const a = (st && st.attributes) || {};
    let pos = Number(a.media_position || 0);
    const u = Date.parse(a.media_position_updated_at || "");
    const lu = Date.parse((st && st.last_updated) || "");
    if (st && st.state === "playing" && !Number.isNaN(u) && !Number.isNaN(lu)) pos += Math.max(0, (lu - u) / 1000);
    return pos;
  }

  _lineAt(pos) {
    const L = this._lines;
    let idx = -1;
    for (let i = 0; i < L.length; i++) {
      if (Number.isFinite(L[i].t) && L[i].t <= pos) idx = i;
      else if (Number.isFinite(L[i].t)) break;
    }
    return idx;
  }

  /* Live helper value in ms (positive = lyrics later), or null if unavailable. */
  _liveOffsetMs() {
    const os = this._offsetState;
    if (!os) return null;
    const v = Number(os.state);
    return Number.isFinite(v) ? v : null;
  }

  _lyricPos() {
    // Convention: POSITIVE offset = lyrics appear LATER → look earlier in the LRC.
    const live = this._liveOffsetMs();
    if (live !== null) return this._now() - live / 1000;
    const st = this._state;
    const off = Number(((st && st.attributes) || {}).lyric_offset_ms || 0) / 1000;
    return this._now() - off;
  }

  _serverIndex(st) {
    const cur = ((st && st.attributes) || {}).lyric_current;
    if (!cur) return -1;
    const hits = [];
    this._lines.forEach((l, i) => { if (l.raw === cur) hits.push(i); });
    if (!hits.length) return this._idx >= 0 ? this._idx : -1;
    const pos = this._now();
    hits.sort((x, y) => Math.abs(this._lines[x].t - pos) - Math.abs(this._lines[y].t - pos));
    return hits[0];
  }

  /* ---------- rendering ---------- */

  _update() {
    if (!this._root) return;
    const st = this._state;
    const a = (st && st.attributes) || {};
    const active = st && (st.state === "playing" || st.state === "paused");
    const lyricsOn = a.lyrics_enabled !== false;
    this._bindProgress();
    this._titleEl.textContent = active ? a.media_title || "" : "SpinJam";
    this._subEl.textContent = active
      ? [a.media_artist, a.media_album_name].filter(Boolean).join(" · ")
      : "";

    const lo = active ? (a.entity_picture || "") : "";
    const hd = active ? (a.artwork_hd || "") : "";
    if (a.artwork_next) this._preload(this._absUrl(a.artwork_next));

    const raw = Array.isArray(a.lyric_lines) ? a.lyric_lines.filter((l) => l && l.text != null) : [];
    const key = active
      ? [a.media_title, a.media_artist, raw.length, raw[0] && raw[0].t, raw[0] && raw[0].text, lyricsOn].join("|")
      : "idle";
    if (key !== this._songKey) {
      this._songKey = key;
      this._lines = lyricsOn
        ? raw.map((r) => Object.assign(this._parseLine(r), { raw: String(r.text) }))
        : [];
      this._renderList();
      this._idx = -2;
    }

    const details = this._cfg.mode === "details";
    const cover = !details && !lyricsOn;
    if (details) {
      this._dt.textContent = active ? a.media_title || "" : "SpinJam";
      this._da.textContent = active ? a.media_artist || "" : "Waiting for music…";
      this._dl.textContent = active ? a.media_album_name || "" : "";
      this._setArtLayers(lo, hd);
    } else if (cover) {
      this._coverTitle.textContent = active ? a.media_title || "" : "SpinJam";
      this._coverArtist.textContent = active ? a.media_artist || "Waiting for music…" : "Waiting for music…";
      this._setCoverArt(lo, hd);
    } else {
      this._head.classList.toggle("hidden", !(this._cfg.show_header || this._cfg.show_progress));
      this._titleEl.classList.toggle("hidden", !this._cfg.show_header);
      this._subEl.classList.toggle("hidden", !this._cfg.show_header);
    }
    const wantProg = details || cover || this._cfg.show_progress;
    this._prog.classList.toggle("hidden", !(wantProg && active && Number(a.media_duration) > 0));
    if (details || cover) { this._progress(); return; }
    this._dbg.classList.toggle("hidden", !this._cfg.debug);
    this._progress();
    if (!active || !this._lines.length) {
      this._vp.classList.toggle("hidden", true);
      this._msgEl.classList.remove("hidden");
      this._msgEl.textContent = !active
        ? "Waiting for music…"
        : a.lyric_current || "No lyrics";
      return;
    }
    this._vp.classList.remove("hidden");
    this._msgEl.classList.add("hidden");
    this._tick(true);
  }

  _renderList() {
    this._ul.style.transition = "none";
    this._ul.style.transform = "translateY(0)";
    this._ul.textContent = "";
    this._lines.forEach((l) => {
      const li = document.createElement("li");
      if (l.words) {
        l.words.forEach((w) => {
          const s = document.createElement("span");
          s.className = "w";
          s.textContent = w.text;
          li.appendChild(s);
        });
      } else {
        const s = document.createElement("span");
        s.className = "fill";
        s.textContent = l.text || "♪";
        li.appendChild(s);
      }
      this._ul.appendChild(li);
    });
  }

  _setIndex(idx) {
    // Within a track, lyric line index never steps backward (clock may still seek forward).
    if (this._idx >= 0 && idx >= 0 && idx < this._idx) return;
    if (idx === this._idx) return;
    const prev = this._idx;
    this._idx = idx;
    const items = this._ul.children;
    for (let i = 0; i < items.length; i++) {
      const d = i - idx;
      let cls = "";
      if (d === 0) cls = "cur";
      else if (d < 0) cls = "past";
      else if (d <= 3) cls = "n" + d;
      items[i].className = cls;
      if (d !== 0 && items[i].style.fontSize) items[i].style.fontSize = "";
    }
    this._fitRows();
    // Big jumps (seek / new song) snap; normal line changes glide.
    this._scroll(prev >= -1 && Math.abs(idx - prev) <= 3);
  }

  /* Keep the current line to 2 rows: step its size down if it wraps further. */
  _fitRows() {
    const li = this._idx >= 0 ? this._ul.children[this._idx] : null;
    if (!li) return;
    li.style.fontSize = "";
    const base = parseFloat(getComputedStyle(li).fontSize) || 30;
    for (let f = 1; f >= 0.7; f -= 0.075) {
      li.style.fontSize = f === 1 ? "" : `${Math.round(base * f)}px`;
      const lh = parseFloat(getComputedStyle(li).lineHeight) || base * 1.25;
      const pad = parseFloat(getComputedStyle(li).paddingTop) * 2;
      if ((li.offsetHeight - pad) / lh < 2.5) break;
    }
  }

  _scroll(animate) {
    if (!this._ul || !this._vp) return;
    const items = this._ul.children;
    if (!items.length) return;
    const i = Math.max(0, this._idx);
    const li = items[i];
    const vh = this._vp.clientHeight || 600;
    let off = li.offsetTop + li.offsetHeight / 2 - vh / 2;
    if (this._idx < 0) off -= li.offsetHeight; // before first line: show it just below centre
    this._ul.style.transition = animate ? "" : "none";
    this._ul.style.transform = `translateY(${-off}px)`;
  }

  _sweep(pos) {
    const idx = this._idx;
    if (idx < 0) return;
    const li = this._ul.children[idx];
    const L = this._lines[idx];
    if (!li || !L) return;
    const nextT = idx + 1 < this._lines.length ? this._lines[idx + 1].t : NaN;
    // Lines are dropped for instrumental gaps, so cap the sweep at a reading-speed estimate.
    const est = Math.min(9, Math.max(1.6, (L.text || "").length * 0.085));
    const end = Number.isFinite(nextT) ? Math.min(nextT, L.t + est * 1.6) : L.t + est;
    if (L.words) {
      const spans = li.children;
      for (let k = 0; k < L.words.length; k++) {
        const ws = L.words[k].t;
        const we = k + 1 < L.words.length ? L.words[k + 1].t : end;
        const p = we > ws ? (pos - ws) / (we - ws) : pos >= ws ? 1 : 0;
        spans[k].style.setProperty("--p", `${Math.round(Math.min(1, Math.max(0, p)) * 1000) / 10}%`);
      }
      li.classList.toggle("done", pos >= end);
    } else {
      const p = end > L.t ? (pos - L.t) / (end - L.t) : 1;
      const pc = Math.min(1, Math.max(0, p));
      li.firstChild.style.setProperty("--p", `${Math.round(pc * 1000) / 10}%`);
      li.classList.toggle("done", pc >= 1);
    }
  }

  _fmt(s) {
    s = Math.max(0, Math.floor(s));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  _progress() {
    const st = this._state;
    const dur = Number(((st && st.attributes) || {}).media_duration || 0);
    if (!(dur > 0)) return;
    const pos = Math.min(dur, this._now());
    this._fillbar.style.transform = `scaleX(${pos / dur})`;
    const tl = this._fmt(pos), tr = this._fmt(dur);
    if (this._tl.textContent !== tl) this._tl.textContent = tl;
    if (this._tr.textContent !== tr) this._tr.textContent = tr;
    if (this._cfg.debug) {
      const live = this._liveOffsetMs();
      const dbg = this._pbClock.debug();
      const d = `base ${dbg.base.toFixed(3)}s · lat ${dbg.lat.toFixed(3)}s · speed ${dbg.speed.toFixed(2)} · resets ${dbg.resetCount}` +
        ` · skew ${this._skew == null ? "?" : this._skew.toFixed(1)}s` +
        (live !== null ? ` · live offset ${live > 0 ? "+" : ""}${live} ms` : "");
      if (this._dbg.textContent !== d) this._dbg.textContent = d;
    }
  }

  _tick(fromState) {
    if (!this._lines.length) return;
    const st = this._state;
    const timed = this._lines.some((l) => Number.isFinite(l.t));
    const pos = this._lyricPos();
    const idx = timed ? this._lineAt(pos) : this._serverIndex(st);
    this._setIndex(idx);
    this._sweep(pos);
  }

  _frame() {
    this._raf = null;
    const st = this._state;
    if (st && st.state === "playing" && this.isConnected) {
      this._progress();
      const mode = this.getAttribute("mode");
      if (this._lines.length && mode !== "details" && mode !== "cover") this._tick(false);
    }
    this._startLoop();
  }

  _startLoop() {
    if (this._raf || !this.isConnected) return;
    this._raf = requestAnimationFrame(this._frame);
  }
}

if (!customElements.get("spinjam-lyrics-card")) {
  customElements.define("spinjam-lyrics-card", SpinJamLyricsCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "spinjam-lyrics-card",
    name: "SpinJam Lyrics",
    description: "Centered lyrics, HD art, and cover layout when lyrics are off (modes: lyrics | details | cover)",
  });
}

/* Deprecated alias for existing dashboards that still use spinjam-now-playing-card. */
class SpinJamNowPlayingCardAlias extends SpinJamLyricsCard {
  setConfig(config) {
    super.setConfig(Object.assign({ mode: "details" }, config || {}));
  }
}
if (!customElements.get("spinjam-now-playing-card")) {
  customElements.define("spinjam-now-playing-card", SpinJamNowPlayingCardAlias);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "spinjam-now-playing-card",
    name: "SpinJam Now Playing (deprecated)",
    description: "Alias for spinjam-lyrics-card with mode: details — prefer custom:spinjam-lyrics-card",
  });
  console.info(
    "%c SpinJam %c spinjam-now-playing-card is deprecated; use spinjam-lyrics-card ",
    "background:#111;color:#fff",
    "background:#333;color:#ddd"
  );
}
