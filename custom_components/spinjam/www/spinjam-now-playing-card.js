/**
 * SpinJam TV now-playing card (vanilla custom element, no Lit).
 * Designed for Cast / 1080p TV: large art, metadata, progress, scrolling lyrics.
 *
 * type: custom:spinjam-now-playing-card
 * entity: media_player.spinjam_now_playing
 */
class SpinJamNowPlayingCard extends HTMLElement {
  static getStubConfig() {
    return {
      type: "custom:spinjam-now-playing-card",
      entity: "media_player.spinjam_now_playing",
    };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("SpinJam card requires an entity");
    }
    this._config = config;
    this._entity = config.entity;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    if (!this._root) {
      this._root = this.attachShadow({ mode: "open" });
      this._tick = setInterval(() => this._render(true), 500);
    }
    this._render();
  }

  disconnectedCallback() {
    if (this._tick) {
      clearInterval(this._tick);
      this._tick = null;
    }
  }

  getCardSize() {
    return 12;
  }

  /** Interpolated media position (sync_offset already baked into entity position). */
  _position(state) {
    if (!state) return 0;
    const attrs = state.attributes || {};
    let pos = Number(attrs.media_position || 0);
    if (state.state === "playing" && attrs.media_position_updated_at) {
      const updated = Date.parse(attrs.media_position_updated_at);
      if (!Number.isNaN(updated)) {
        pos += Math.max(0, (Date.now() - updated) / 1000);
      }
    }
    return Math.max(0, pos);
  }

  /** Position used for lyric highlight (adds lyric_offset_ms). */
  _lyricPosition(state) {
    const attrs = (state && state.attributes) || {};
    return this._position(state) + Number(attrs.lyric_offset_ms || 0) / 1000;
  }

  _render(fromTick) {
    if (!this._root || !this._hass || !this._config) return;
    const state = this._hass.states[this._entity];
    const attrs = (state && state.attributes) || {};
    const playing = state && (state.state === "playing" || state.state === "paused");
    const title = attrs.media_title || "";
    const artist = attrs.media_artist || "";
    const album = attrs.media_album_name || "";
    const art = attrs.entity_picture || "";
    const duration = Number(attrs.media_duration || 0);
    const pos = this._position(state);
    const lyricPos = this._lyricPosition(state);
    const lines = Array.isArray(attrs.lyric_lines) ? attrs.lyric_lines : [];
    let currentIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      const start = Number(lines[i].t != null ? lines[i].t : lines[i].start || 0);
      if (start <= lyricPos) currentIdx = i;
      else break;
    }
    if (!fromTick || !this._built) {
      this._root.innerHTML = `
        <style>
          :host { display:block; height:100vh; background:#0b0b0c; color:#f5f5f5;
            font-family: "Segoe UI", system-ui, sans-serif; }
          .wrap { box-sizing:border-box; height:100%; padding:4vh 5vw; display:grid;
            grid-template-columns: 42vw 1fr; gap:4vw; align-items:center; }
          .art { width:100%; aspect-ratio:1; object-fit:cover; border-radius:8px;
            box-shadow: 0 20px 60px rgba(0,0,0,.55); background:#1a1a1c; }
          .meta h1 { font-size: clamp(2.2rem, 4.5vw, 4rem); margin:0 0 .2em; font-weight:650; }
          .meta h2 { font-size: clamp(1.3rem, 2.4vw, 2.2rem); margin:0; font-weight:450; opacity:.9; }
          .meta h3 { font-size: clamp(1rem, 1.8vw, 1.5rem); margin:.4em 0 1.2em; opacity:.65; font-weight:400; }
          .bar { height:8px; background:#2a2a2e; border-radius:99px; overflow:hidden; margin:1.2em 0 1.6em; }
          .bar > i { display:block; height:100%; background:#e8e8ea; width:0%; }
          .lyrics { max-height: 42vh; overflow:hidden; position:relative; }
          .lyrics ul { list-style:none; margin:0; padding:0; transition: transform .35s ease; }
          .lyrics li { font-size: clamp(1.1rem, 2vw, 1.7rem); line-height:1.55; padding:.18em 0;
            opacity:.35; transition: opacity .2s, transform .2s; }
          .lyrics li.cur { opacity:1; font-weight:600; transform: scale(1.02); transform-origin:left center; }
          .idle { grid-column:1/-1; text-align:center; opacity:.7; }
          .idle .logo { font-size:3rem; letter-spacing:.12em; margin-bottom:.4em; }
          @media (max-width: 900px) {
            .wrap { grid-template-columns:1fr; }
          }
        </style>
        <div class="wrap"></div>
      `;
      this._built = true;
    }
    const wrap = this._root.querySelector(".wrap");
    if (!playing || (!title && !artist)) {
      wrap.innerHTML =
        `<div class="idle"><div class="logo">SPINJAM</div><div>Waiting for music…</div></div>`;
      return;
    }
    const pct = duration > 0 ? Math.min(100, (pos / duration) * 100) : 0;
    const artUrl = art
      ? art.startsWith("http")
        ? art
        : `${this._hass.hassUrl(art)}`
      : "";
    let lyricsHtml = "";
    if (lines.length) {
      const items = lines
        .map((line, i) => {
          const text = line.text || line.l || "";
          return `<li class="${i === currentIdx ? "cur" : ""}">${this._esc(text)}</li>`;
        })
        .join("");
      lyricsHtml = `<div class="lyrics"><ul>${items}</ul></div>`;
    } else if (attrs.lyric_current) {
      lyricsHtml = `<div class="lyrics"><ul><li class="cur">${this._esc(attrs.lyric_current)}</li>
        ${attrs.lyric_next ? `<li>${this._esc(attrs.lyric_next)}</li>` : ""}</ul></div>`;
    }
    wrap.innerHTML = `
      <img class="art" alt="" src="${artUrl || ""}" onerror="this.style.opacity=.15"/>
      <div class="meta">
        <h1>${this._esc(title)}</h1>
        <h2>${this._esc(artist)}</h2>
        <h3>${this._esc(album)}</h3>
        <div class="bar"><i style="width:${pct}%"></i></div>
        ${lyricsHtml}
      </div>`;
    const ul = this._root.querySelector(".lyrics ul");
    const cur = this._root.querySelector(".lyrics li.cur");
    if (ul && cur) {
      const box = this._root.querySelector(".lyrics");
      const offset = Math.max(0, cur.offsetTop - box.clientHeight * 0.35);
      ul.style.transform = `translateY(${-offset}px)`;
    }
  }

  _esc(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}

customElements.define("spinjam-now-playing-card", SpinJamNowPlayingCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "spinjam-now-playing-card",
  name: "SpinJam Now Playing",
  description: "TV / Cast now-playing view with art, progress, and synced lyrics",
});
console.info(
  "%c SpinJam %c now-playing card ",
  "background:#111;color:#fff",
  "background:#333;color:#ddd"
);
