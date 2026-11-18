/*
 * spinjam-lyrics-card v6 — lyrics + HD art crossfade.
 * type: custom:spinjam-lyrics-card
 * entity: media_player.spinjam_now_playing   (default)
 * mode: lyrics | details                     (lyrics = centred lyrics only;
 *                                               details = art, title/artist/album, progress)
 * show_header / show_progress: false          (lyrics mode extras, off by default)
 *
 * When switch.spinjam_lyrics is off, the Cast row collapses to ONE full-width
 * stage (blurred cover, centred square, title / artist / album, slim progress).
 * The switch is live: presentation only, no recast.
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
 * Plain lyrics (lyrics_status=plain) are static centred text with no sweep.
 * A dim "Lyrics: …" footer sits at the bottom right in lyrics mode.
 */
import { PlaybackClock, lyricLookPosition } from "./spinjam-playback-clock.js";
import {
  resolveCardPresentation,
  slotLayoutPatch,
  stageArtSizePx,
  stageMissingArt,
  LAYOUT_TRANSITION_MS,
  lyricDelayToast,
} from "./spinjam-card-layout.js";

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
    this._plain = false;
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
    this._noteOffsetToast();
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
    if (this._presentation) this._applyStackSlot(this._presentation);
    requestAnimationFrame(() => { this._fitHeight(); this._scroll(false); });
    setTimeout(this._onResize, 1200); // fonts / art settle
  }

  /* Fill from the card's top edge to the bottom of the screen (works in Cast and browser). */
  _fitHeight() {
    if (!this._card) return;
    if (this._cfg && this._cfg.height) { this._card.style.height = this._cfg.height; return; }
    if (this._presentation && this._presentation.fullBleed) {
      this._card.style.height = "100vh";
      this._card.style.width = "100%";
      this._clearChrome();
      this._scale();
      return;
    }
    const top = this.getBoundingClientRect().top;
    const h = Math.max(320, Math.round(window.innerHeight - Math.max(0, top) - 8));
    this._card.style.height = h + "px";
    this._scale();
  }

  /* Panel / stage cards sit flush: no Lovelace card margin, padding, or shadow. */
  _clearChrome() {
    this.style.width = "100vw";
    this.style.height = "100vh";
    this.style.margin = "0";
    this.style.padding = "0";
    let node = this.parentElement;
    for (let i = 0; i < 5 && node; i += 1) {
      node.style.margin = "0";
      node.style.padding = "0";
      node.style.border = "none";
      node.style.boxShadow = "none";
      node.style.borderRadius = "0";
      node.style.maxWidth = "none";
      node.style.width = "100%";
      node.style.height = "100%";
      node = node.parentElement;
    }
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
    const art = stageArtSizePx(r.height, r.width, window.innerHeight);
    if (art) this.style.setProperty("--sj-art", art + "px");
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
        .msg.plain {
          white-space: pre-wrap; font-weight: 600; opacity: .9; overflow: auto;
          max-height: 70%; line-height: 1.35;
        }
        .attrib {
          position: absolute; right: 14px; bottom: 8px; z-index: 3;
          font-size: 12px; line-height: 1.2; opacity: .38; letter-spacing: .02em;
          pointer-events: none;
        }
        /* details mode — stays mounted so it can crossfade into the stage */
        .det {
          position: absolute; inset: 0; display: block;
          opacity: 0; visibility: hidden; pointer-events: none;
        }
        :host([mode="details"]) .det { opacity: 1; visibility: visible; pointer-events: auto; }
        :host([mode="details"]) .lyrics-pane, :host([mode="details"]) .attrib { display: none !important; }
        :host([mode="details"]) ha-card { padding: 0; }
        .lyrics-pane {
          display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; min-width: 0;
          height: 100%; position: relative;
        }
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
        /* stage (lyrics off): one full-bleed 16:9 view, not a second panel */
        .det, .stage {
          transition: opacity ${LAYOUT_TRANSITION_MS}ms ease, visibility ${LAYOUT_TRANSITION_MS}ms ease;
        }
        :host { transition: opacity ${LAYOUT_TRANSITION_MS}ms ease; }
        .stage {
          position: absolute; inset: 0; display: block; overflow: hidden;
          background: #16161a;
          opacity: 0; visibility: hidden; pointer-events: none;
        }
        :host([mode="stage"]) .stage { opacity: 1; visibility: visible; pointer-events: auto; }
        :host([mode="stage"]) .lyrics-pane,
        :host([mode="stage"]) .attrib { display: none !important; }
        :host([mode="stage"]) ha-card,
        :host([mode="cast"]) ha-card {
          margin: 0; padding: 0; border: none; box-shadow: none; border-radius: 0;
          --ha-card-border-width: 0px; --ha-card-border-radius: 0px; --ha-card-box-shadow: none;
        }
        :host([mode="stage"]) ha-card { background: transparent; }
        :host([mode="cast"]),
        :host([mode="stage"]) {
          display: block; width: 100vw; height: 100vh; margin: 0; padding: 0;
        }
        /* cast: one card, lyrics on = details | lyrics, filling the panel */
        :host([mode="cast"]) ha-card {
          display: flex; flex-direction: row; background: #121212; width: 100%; height: 100%;
        }
        :host([mode="cast"]) .det {
          position: relative; inset: auto; flex: 1 1 50%; width: 50%; height: 100%;
          min-width: 0; opacity: 1; visibility: visible; pointer-events: auto;
        }
        :host([mode="cast"]) .lyrics-pane { flex: 1 1 50%; width: 50%; height: 100%; }
        :host([mode="cast"]) .stage { opacity: 0; visibility: hidden; pointer-events: none; }
        :host([mode="hidden"]) { display: none !important; }
        :host([mode="hidden"]) ha-card { visibility: hidden; }
        .stage-bg { position: absolute; inset: 0; overflow: hidden; background: #16161a; }
        .stage-bg.empty {
          background: linear-gradient(165deg, #3a3a42 0%, #24242a 46%, #141418 100%);
        }
        .stage-blur {
          position: absolute; inset: -14%;
          background: #1a1a1e center / cover no-repeat;
          filter: blur(46px) brightness(.48) saturate(1.12);
          transform: scale(1.2);
          opacity: 0;
          transition: opacity 700ms ease;
        }
        .stage-blur.show { opacity: 1; }
        .stage-bg.empty .stage-blur { opacity: 0; }
        .stage-dim { position: absolute; inset: 0; background: rgba(0,0,0,.28); }
        .stage-bg.empty .stage-dim { background: transparent; }
        .stage-col {
          position: relative; z-index: 1; height: 100%; box-sizing: border-box;
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          padding: 3.2vh 6vw 4vh; gap: 0.35vh;
        }
        .stage-art-wrap {
          position: relative; flex: 0 0 auto;
          width: var(--sj-art, 60vh); height: var(--sj-art, 60vh);
          max-width: 70vw;
          border-radius: 18px; overflow: hidden;
          background: linear-gradient(160deg, #4a4a52, #2a2a30 55%, #1a1a1e);
          box-shadow: 0 28px 70px rgba(0,0,0,.42), 0 2px 10px rgba(0,0,0,.28);
        }
        .stage-art {
          position: absolute; inset: 0; background: center / cover no-repeat;
          opacity: 0; transition: opacity 700ms ease;
        }
        .stage-art.show { opacity: 1; }
        .stage-placeholder {
          position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
          font-size: calc(var(--sj-art, 240px) * .34); line-height: 1; opacity: .42;
          color: #fff;
        }
        .stage-art-wrap.has-art .stage-placeholder { display: none; }
        .stage-title {
          margin-top: 2.4vh; max-width: 78vw; text-align: center;
          font-size: clamp(28px, 4.2vh, 68px); font-weight: 800; line-height: 1.12;
        }
        .stage-artist {
          max-width: 74vw; text-align: center;
          font-size: clamp(18px, 2.6vh, 40px); font-weight: 600; opacity: .9; line-height: 1.25;
        }
        .stage-album {
          max-width: 70vw; text-align: center;
          font-size: clamp(14px, 1.9vh, 28px); font-weight: 500; opacity: .5; line-height: 1.3;
        }
        .stage-col .prog {
          width: min(560px, 48vw); margin: 1.8vh auto 0;
          font-size: clamp(13px, 1.7vh, 22px); opacity: .88;
        }
        .stage-col .bar { height: 4px; border-radius: 99px; }
        .toast {
          position: absolute; left: 50%; bottom: 7%; transform: translateX(-50%);
          z-index: 6; max-width: 80%;
          padding: 10px 18px; border-radius: 999px;
          background: rgba(0,0,0,.72); color: #fff;
          font-size: clamp(14px, 2vh, 22px); font-weight: 600; text-align: center;
          opacity: 0; pointer-events: none;
          transition: opacity 220ms ease;
        }
        .toast.show { opacity: 1; }
        .hidden { display: none; }
      </style>
      <ha-card>
        <div class="det"><div class="art-stack"><div class="art-layer a0"></div><div class="art-layer a1"></div></div><div class="shade"></div>
          <div class="info"><div class="dt"></div><div class="da"></div><div class="dl"></div>
            <div class="prog dprog"><span class="tl">0:00</span><div class="bar"><div class="fillbar"></div></div><span class="tr">0:00</span></div>
          </div></div>
        <div class="stage">
          <div class="stage-bg">
            <div class="stage-blur sb0"></div>
            <div class="stage-blur sb1"></div>
            <div class="stage-dim"></div>
          </div>
          <div class="stage-col">
            <div class="stage-art-wrap">
              <div class="stage-art sa0"></div>
              <div class="stage-art sa1"></div>
              <div class="stage-placeholder" aria-hidden="true">♪</div>
            </div>
            <div class="stage-title"></div>
            <div class="stage-artist"></div>
            <div class="stage-album"></div>
            <div class="prog sprog"><span class="tl">0:00</span><div class="bar"><div class="fillbar"></div></div><span class="tr">0:00</span></div>
          </div>
        </div>
        <div class="lyrics-pane">
          <div class="head"><div class="title"></div><div class="sub"></div>
            <div class="prog"><span class="tl">0:00</span><div class="bar"><div class="fillbar"></div></div><span class="tr">0:00</span></div>
            <div class="dbg hidden"></div></div>
          <div class="msg hidden"></div>
          <div class="vp"><ul></ul></div>
        </div>
        <div class="attrib"></div>
        <div class="toast" role="status"></div>
      </ha-card>`;
    this._titleEl = this._root.querySelector(".title");
    this._subEl = this._root.querySelector(".sub");
    this._msgEl = this._root.querySelector(".msg");
    this._attrib = this._root.querySelector(".attrib");
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
    this._stageBg = this._root.querySelector(".stage-bg");
    this._stageArtWrap = this._root.querySelector(".stage-art-wrap");
    this._sb0 = this._root.querySelector(".sb0");
    this._sb1 = this._root.querySelector(".sb1");
    this._sa0 = this._root.querySelector(".sa0");
    this._sa1 = this._root.querySelector(".sa1");
    this._stageFront = 0;
    this._stageKey = null;
    this._stageTitle = this._root.querySelector(".stage-title");
    this._stageArtist = this._root.querySelector(".stage-artist");
    this._stageAlbum = this._root.querySelector(".stage-album");
    this._toast = this._root.querySelector(".toast");
    this._toastTimer = null;
    this._offsetMs = null;
    this._presentation = resolveCardPresentation({
      configuredMode: this._cfg && this._cfg.mode,
      lyricsEnabled: true,
      siblingShowsStage: false,
    });
    this._bindProgress();
  }

  _bindProgress() {
    const a = (this._state && this._state.attributes) || {};
    const presentation = resolveCardPresentation({
      configuredMode: this._cfg && this._cfg.mode,
      lyricsEnabled: a.lyrics_enabled,
      siblingShowsStage: this._siblingShowsStage(),
    });
    const prev = this.getAttribute("mode");
    this._presentation = presentation;
    this.setAttribute("mode", presentation.mode);
    this._applyStackSlot(presentation);
    if (prev && prev !== presentation.mode) {
      requestAnimationFrame(() => this._onResize());
    }
    const mode = presentation.mode;
    let pr;
    if (mode === "details" || mode === "cast") pr = this._root.querySelector(".dprog");
    else if (mode === "stage" || mode === "hidden") pr = this._root.querySelector(".sprog");
    else pr = this._root.querySelector(".head .prog");
    this._prog = pr;
    this._fillbar = pr ? pr.querySelector(".fillbar") : null;
    this._tl = pr ? pr.querySelector(".tl") : null;
    this._tr = pr ? pr.querySelector(".tr") : null;
  }

  /* Direct child of the nearest flex row or grid (horizontal-stack, sections, grid). */
  _stackSlot() {
    let node = this;
    for (let i = 0; i < 8 && node && node.parentElement; i += 1) {
      const parent = node.parentElement;
      let display = "";
      try {
        display = getComputedStyle(parent).display;
      } catch (err) {
        display = "";
      }
      const row = parent.id === "root" || (parent.classList && parent.classList.contains("horizontal"));
      const grid = display === "grid" || display === "inline-grid";
      const flex = display === "flex" || display === "inline-flex";
      if (row || grid || flex) return node;
      node = parent;
    }
    return null;
  }

  _applyStackSlot(presentation) {
    const slot = this._stackSlot();
    const parent = slot && slot.parentElement;
    let parentDisplay = "";
    try {
      parentDisplay = parent ? getComputedStyle(parent).display : "";
    } catch (err) {
      parentDisplay = "";
    }
    const patch = slotLayoutPatch(presentation, parentDisplay);
    this.style.display = patch.hostDisplay;
    if (!slot) return;
    if (!slot.dataset.sjSlot) {
      slot.dataset.sjSlot = "1";
      slot.style.transition = `flex-basis ${LAYOUT_TRANSITION_MS}ms ease, max-width ${LAYOUT_TRANSITION_MS}ms ease, opacity ${LAYOUT_TRANSITION_MS}ms ease, padding ${LAYOUT_TRANSITION_MS}ms ease`;
      slot.style.minWidth = "0";
    }
    slot.style.display = patch.slotDisplay;
    slot.style.flex = patch.slotFlex;
    slot.style.width = patch.slotWidth;
    slot.style.maxWidth = patch.slotMaxWidth;
    slot.style.margin = patch.slotMargin;
    slot.style.padding = patch.slotPadding;
    slot.style.overflow = patch.slotOverflow;
    slot.style.gridColumn = patch.slotGridColumn;
    if (!parent) return;
    if (patch.parentGridTemplateColumns) {
      if (parent.dataset.sjGrid === undefined) {
        parent.dataset.sjGrid = parent.style.gridTemplateColumns || "";
      }
      parent.style.gridTemplateColumns = patch.parentGridTemplateColumns;
    } else if (parent.dataset.sjGrid !== undefined && !(presentation && presentation.collapseSlot)) {
      parent.style.gridTemplateColumns = parent.dataset.sjGrid;
      delete parent.dataset.sjGrid;
    }
  }

  _siblingShowsStage() {
    if (!this._cfg || this._cfg.mode === "details") return false;
    const slot = this._stackSlot();
    if (!slot || !slot.parentElement) return false;
    for (const child of slot.parentElement.children) {
      if (child === slot) continue;
      const card = this._spinjamCardIn(child);
      if (!card || card === this) continue;
      const tag = (card.tagName || "").toLowerCase();
      if (tag === "spinjam-now-playing-card") return true;
      // Configured mode, not the live attribute: a details card's attribute
      // becomes "stage" while lyrics are off, and it still owns the stage.
      if (card._cfg && card._cfg.mode === "details") return true;
    }
    return false;
  }

  _spinjamCardIn(node) {
    if (!node || node === this) return null;
    const tag = (node.tagName || "").toLowerCase();
    if (tag === "spinjam-lyrics-card" || tag === "spinjam-now-playing-card") return node;
    if (node.querySelector) {
      return node.querySelector("spinjam-lyrics-card, spinjam-now-playing-card");
    }
    return null;
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

  _cssUrl(url) {
    if (!url) return "none";
    return `url("${String(url).replace(/"/g, "%22")}")`;
  }

  /* Crossfade low-res → HD on the blurred fill and the square together. */
  _setStageArt(loUrl, hdUrl) {
    const lo = this._absUrl(loUrl);
    const hd = this._absUrl(hdUrl || "");
    const missing = stageMissingArt(lo, hd);
    if (this._stageBg) this._stageBg.classList.toggle("empty", missing);
    if (this._stageArtWrap) this._stageArtWrap.classList.toggle("has-art", !missing);
    const blurs = [this._sb0, this._sb1].filter(Boolean);
    const arts = [this._sa0, this._sa1].filter(Boolean);
    const clear = (els) => {
      els.forEach((el) => {
        el.style.backgroundImage = "none";
        el.classList.remove("show");
      });
    };
    if (missing) {
      this._stageKey = "|";
      clear(blurs);
      clear(arts);
      return;
    }
    const key = `${lo}|${hd}`;
    if (key === this._stageKey) {
      if (hd) this._preload(hd);
      return;
    }
    this._stageKey = key;
    const showPair = (idx, url) => {
      const css = this._cssUrl(url);
      [blurs, arts].forEach((els) => {
        if (!els[idx]) return;
        els[idx].style.backgroundImage = css;
        els[idx].classList.add("show");
        if (els[1 - idx]) els[1 - idx].classList.remove("show");
      });
      this._stageFront = idx;
    };
    const immediate = lo || hd;
    const back = this._stageFront ? 0 : 1;
    showPair(back, immediate);
    if (!hd || !lo || hd === lo) return;
    const img = new Image();
    img.onload = () => {
      if (this._stageKey !== key) return;
      showPair(this._stageFront ? 0 : 1, hd);
    };
    img.onerror = () => { /* keep the low-res cover */ };
    img.src = hd;
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
    // Positive offset delays lyrics. Applied once, on top of the playback clock
    // (the clock already includes delivery delay; sync_offset is inside media_position).
    const live = this._liveOffsetMs();
    const off = live !== null
      ? live
      : Number(((this._state && this._state.attributes) || {}).lyric_offset_ms || 0);
    return lyricLookPosition(this._now(), off);
  }

  _shouldToast() {
    const mode = this.getAttribute("mode");
    if (mode === "hidden") return false;
    if (this._cfg && this._cfg.mode === "lyrics") return mode === "stage";
    return mode === "cast" || mode === "stage" || mode === "details" || mode === "lyrics";
  }

  _noteOffsetToast() {
    const next = this._liveOffsetMs();
    const prev = this._offsetMs;
    if (prev !== null && next !== null && prev !== next && this._shouldToast()) {
      this._showOffsetToast(prev, next);
    }
    if (next !== null) this._offsetMs = next;
  }

  _showOffsetToast(previousMs, nextMs) {
    if (!this._toast) return;
    this._toast.textContent = lyricDelayToast(previousMs, nextMs);
    this._toast.classList.add("show");
    if (this._toastTimer) clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      if (this._toast) this._toast.classList.remove("show");
    }, 2000);
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
    const status = String(a.lyrics_status || "");
    const key = active
      ? [a.media_title, a.media_artist, status, a.lyrics_source, raw.length, raw[0] && raw[0].t, raw[0] && raw[0].text, lyricsOn].join("|")
      : "idle";
    if (key !== this._songKey) {
      this._songKey = key;
      this._lines = lyricsOn
        ? raw.map((r) => Object.assign(this._parseLine(r), { raw: String(r.text) }))
        : [];
      this._renderList();
      this._idx = -2;
    }

    const mode = this.getAttribute("mode");
    const details = mode === "details";
    const cast = mode === "cast";
    const stage = mode === "stage";
    if (mode === "hidden") {
      if (this._prog) this._prog.classList.add("hidden");
      return;
    }
    if (details || cast) {
      this._dt.textContent = active ? a.media_title || "" : "SpinJam";
      this._da.textContent = active ? a.media_artist || "" : "Waiting for music…";
      this._dl.textContent = active ? a.media_album_name || "" : "";
      this._setArtLayers(lo, hd);
    }
    if (stage) {
      this._stageTitle.textContent = active ? a.media_title || "SpinJam" : "SpinJam";
      this._stageArtist.textContent = active
        ? (a.media_artist || "")
        : "Waiting for music…";
      this._stageAlbum.textContent = active ? a.media_album_name || "" : "";
      this._setStageArt(lo, hd);
    }
    if (!details && !stage) {
      this._head.classList.toggle("hidden", !(this._cfg.show_header || this._cfg.show_progress));
      this._titleEl.classList.toggle("hidden", !this._cfg.show_header);
      this._subEl.classList.toggle("hidden", !this._cfg.show_header);
    }
    const wantProg = details || cast || stage || this._cfg.show_progress;
    if (this._prog) {
      this._prog.classList.toggle("hidden", !(wantProg && active && Number(a.media_duration) > 0));
    }
    this._setAttrib(a);
    if ((details || stage) && !cast) { this._progress(); return; }
    this._dbg.classList.toggle("hidden", !this._cfg.debug);
    this._progress();
    this._plain = status === "plain";
    if (this._plain && this._lines.length) {
      this._vp.classList.add("hidden");
      this._msgEl.classList.remove("hidden");
      this._msgEl.classList.add("plain");
      this._msgEl.textContent = this._lines.map((l) => l.text).join("\n");
      return;
    }
    this._msgEl.classList.remove("plain");
    if (!active || !this._lines.length) {
      this._vp.classList.add("hidden");
      this._msgEl.classList.remove("hidden");
      this._msgEl.textContent = this._emptyLyricsText(active, status, a);
      if (!this._msgEl.textContent) this._msgEl.classList.add("hidden");
      return;
    }
    this._vp.classList.remove("hidden");
    this._msgEl.classList.add("hidden");
    this._tick(true);
  }

  _emptyLyricsText(active, status, a) {
    if (!active) return "Waiting for music…";
    if (status === "not_found") return "Lyrics not available for this song";
    if (status === "instrumental") return "Instrumental";
    if (status === "error" || status === "disabled" || !status) return a.lyric_current || "";
    return a.lyric_current || "No lyrics";
  }

  _setAttrib(a) {
    if (!this._attrib) return;
    const src = String((a && a.lyrics_source) || "");
    const label = src === "lrclib" ? "Lyrics: LRCLIB"
      : src === "qqmusic" ? "Lyrics: QQ Music"
      : src === "lyricsovh" ? "Lyrics: lyrics.ovh"
      : "";
    if (this._attrib.textContent !== label) this._attrib.textContent = label;
    const mode = this.getAttribute("mode");
    this._attrib.classList.toggle("hidden", !label || mode === "details" || mode === "stage" || mode === "hidden");
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
    if (!(dur > 0) || !this._fillbar || !this._tl || !this._tr) return;
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
    if (this.isConnected && this._state && this._root) {
      const lyricsOff = (this._state.attributes || {}).lyrics_enabled === false;
      if (lyricsOff) {
        const next = resolveCardPresentation({
          configuredMode: this._cfg && this._cfg.mode,
          lyricsEnabled: false,
          siblingShowsStage: this._siblingShowsStage(),
        });
        if (!this._presentation || next.mode !== this._presentation.mode) this._update();
      }
    }
    if (st && st.state === "playing" && this.isConnected) {
      this._progress();
      const mode = this.getAttribute("mode");
      if (this._lines.length && !this._plain && mode !== "details" && mode !== "stage" && mode !== "hidden") this._tick(false);
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
    description: "One Cast card: split lyrics when on, full-screen stage when off (modes: cast | lyrics | details)",
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
