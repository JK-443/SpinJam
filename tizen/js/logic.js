/*
 * Pure helpers for the SpinJam Tizen display.
 * No entity ids. Entities are chosen from the Home Assistant entity registry
 * by platform "spinjam" and translation key (or unique id on the full list).
 *
 * Now-playing media player attributes this app reads:
 *   media_title, media_artist, media_album_name
 *   media_position, media_position_updated_at, media_duration
 *   entity_picture, artwork_hd, artwork_next
 *   lyric_lines[{t, text, words?: [{t, text}]}]  — t is seconds from the start
 *   lyric_offset_ms, lyrics_enabled, lyrics_status, lyrics_source, lyric_current
 * Lyrics switch state is "on" / "off". Lyric delay number state is milliseconds
 * (positive = lyrics later). The number wins over lyric_offset_ms when it is set.
 */
(function (root) {
  "use strict";

  var PLATFORM = "spinjam";
  var ROLE_BY_KEY = {
    now_playing: "nowPlaying",
    lyrics: "lyrics",
    lyric_offset: "lyricDelay"
  };
  var ROLE_BY_UID = {
    spinjam_now_playing: "nowPlaying",
    spinjam_lyrics: "lyrics",
    spinjam_lyric_offset: "lyricDelay"
  };
  var RETRY_MS = [2000, 5000, 10000, 20000, 30000];
  var LAT_WINDOW = 30;
  var LAT_CLAMP_S = 2;
  var IGNORE_ERR_S = 0.15;
  var GRADUAL_ERR_S = 1.5;
  var SPEED_MIN = 0.9;
  var SPEED_MAX = 1.1;

  function clamp(value, lo, hi) {
    return Math.min(hi, Math.max(lo, value));
  }

  function finite(value) {
    return typeof value === "number" && isFinite(value);
  }

  function retryDelayMs(attempt) {
    var index = attempt;
    if (!(index >= 0)) index = 0;
    if (index >= RETRY_MS.length) index = RETRY_MS.length - 1;
    return RETRY_MS[index];
  }

  function normalizeBaseUrl(raw) {
    var value = String(raw || "").replace(/^\s+|\s+$/g, "");
    if (!/^https?:\/\//i.test(value)) return "";
    try {
      var parsed = new URL(value);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
      if (!parsed.hostname) return "";
      return parsed.origin;
    } catch (err) {
      return "";
    }
  }

  function websocketUrl(base) {
    var parsed = new URL(base);
    parsed.protocol = parsed.protocol === "https:" ? "wss:" : "ws:";
    parsed.pathname = "/api/websocket";
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString();
  }

  function absoluteUrl(base, raw) {
    if (!raw) return "";
    try {
      return new URL(raw, base).toString();
    } catch (err) {
      return "";
    }
  }

  function sameOrigin(base, url) {
    try {
      return new URL(url, base).origin === new URL(base).origin;
    } catch (err) {
      return false;
    }
  }

  function domainOf(entityId) {
    var text = String(entityId || "");
    var dot = text.indexOf(".");
    if (dot <= 0) return "";
    return text.slice(0, dot);
  }

  function normalizeEntry(entry) {
    if (!entry) return null;
    var entityId = entry.ei || entry.entity_id;
    var platform = entry.pl || entry.platform;
    if (!entityId || !platform) return null;
    return {
      entityId: entityId,
      platform: platform,
      translationKey: entry.tk || entry.translation_key || "",
      uniqueId: entry.unique_id || ""
    };
  }

  function registryEntries(result) {
    var raw = [];
    if (!result) return [];
    if (Object.prototype.toString.call(result) === "[object Array]") raw = result;
    else if (result.entities && result.entities.length >= 0 && result.entities.slice) raw = result.entities;
    var out = [];
    var i;
    for (i = 0; i < raw.length; i += 1) {
      var entry = normalizeEntry(raw[i]);
      if (entry) out.push(entry);
    }
    return out;
  }

  function resolveSpinJam(result) {
    var found = { nowPlaying: null, lyrics: null, lyricDelay: null };
    var entries = registryEntries(result);
    var i;
    for (i = 0; i < entries.length; i += 1) {
      var entry = entries[i];
      if (entry.platform !== PLATFORM) continue;
      var role = ROLE_BY_KEY[entry.translationKey] || ROLE_BY_UID[entry.uniqueId] || "";
      if (!role) {
        if (entry.translationKey || entry.uniqueId) continue;
        var domain = domainOf(entry.entityId);
        if (domain === "media_player") role = "nowPlaying";
        else if (domain === "number") role = "lyricDelay";
      }
      if (role && !found[role]) found[role] = entry.entityId;
    }
    return found;
  }

  function copyAttributes(src) {
    var attrs = {};
    var key;
    var from = src || {};
    for (key in from) {
      if (Object.prototype.hasOwnProperty.call(from, key)) attrs[key] = from[key];
    }
    return attrs;
  }

  function stateFromCompressed(entityId, compressed) {
    var packed = compressed || {};
    var changed = packed.lc;
    var updated = packed.lu != null ? packed.lu : changed;
    return {
      entity_id: entityId,
      state: packed.s != null ? String(packed.s) : "",
      attributes: copyAttributes(packed.a),
      last_changed_ms: changed != null ? Number(changed) * 1000 : null,
      last_updated_ms: updated != null ? Number(updated) * 1000 : null
    };
  }

  function copyState(state) {
    return {
      entity_id: state.entity_id,
      state: state.state,
      attributes: copyAttributes(state.attributes),
      last_changed_ms: state.last_changed_ms,
      last_updated_ms: state.last_updated_ms
    };
  }

  function applyCompressedDiff(previous, entityId, diff) {
    var base = previous
      ? copyState(previous)
      : stateFromCompressed(entityId, { s: "", a: {} });
    var change = diff || {};
    var add = change["+"] || {};
    var rem = change["-"] || {};
    base.entity_id = entityId;
    if (add.s != null) base.state = String(add.s);
    if (add.lc != null) {
      base.last_changed_ms = Number(add.lc) * 1000;
      if (add.lu == null) base.last_updated_ms = base.last_changed_ms;
    }
    if (add.lu != null) base.last_updated_ms = Number(add.lu) * 1000;
    if (add.a) {
      var key;
      for (key in add.a) {
        if (Object.prototype.hasOwnProperty.call(add.a, key)) base.attributes[key] = add.a[key];
      }
    }
    if (rem.a && rem.a.length) {
      var i;
      for (i = 0; i < rem.a.length; i += 1) delete base.attributes[rem.a[i]];
    }
    return base;
  }

  function applyEntityEvent(states, event) {
    var next = {};
    var id;
    var source = states || {};
    for (id in source) {
      if (Object.prototype.hasOwnProperty.call(source, id)) next[id] = source[id];
    }
    var body = event || {};
    var added = body.a || {};
    for (id in added) {
      if (Object.prototype.hasOwnProperty.call(added, id)) {
        next[id] = stateFromCompressed(id, added[id]);
      }
    }
    var removed = body.r || [];
    var i;
    for (i = 0; i < removed.length; i += 1) delete next[removed[i]];
    var changed = body.c || {};
    for (id in changed) {
      if (Object.prototype.hasOwnProperty.call(changed, id)) {
        next[id] = applyCompressedDiff(next[id], id, changed[id]);
      }
    }
    return next;
  }

  function presentation(opts) {
    var options = opts || {};
    var state = options.playerState || "";
    var active = state === "playing" || state === "paused";
    var lyricsOn = true;
    if (options.lyricsSwitchState === "on" || options.lyricsSwitchState === "off") {
      lyricsOn = options.lyricsSwitchState === "on";
    } else if (options.lyricsEnabledAttr === false) {
      lyricsOn = false;
    }
    var mode = "idle";
    if (active && lyricsOn) mode = "lyrics";
    else if (active) mode = "stage";
    return {
      mode: mode,
      active: active,
      lyricsOn: lyricsOn,
      playing: state === "playing"
    };
  }

  function lyricOffsetMs(numberState, attributeOffset) {
    if (
      numberState != null &&
      numberState !== "" &&
      numberState !== "unavailable" &&
      numberState !== "unknown"
    ) {
      var fromNumber = Number(numberState);
      if (finite(fromNumber)) return fromNumber;
    }
    var fromAttr = Number(attributeOffset);
    return finite(fromAttr) ? fromAttr : 0;
  }

  function parseLyricLines(raw) {
    if (!raw || !raw.length) return [];
    var out = [];
    var i;
    for (i = 0; i < raw.length; i += 1) {
      var row = raw[i];
      if (!row || row.text == null) continue;
      var words = null;
      if (row.words && row.words.length) {
        words = [];
        var w;
        for (w = 0; w < row.words.length; w += 1) {
          var word = row.words[w];
          if (!word) continue;
          words.push({ t: Number(word.t), text: String(word.text || "") });
        }
        if (!words.length) words = null;
      }
      out.push({ t: Number(row.t), text: String(row.text), words: words });
    }
    return out;
  }

  function hasTimedLines(lines) {
    var i;
    for (i = 0; i < lines.length; i += 1) {
      if (finite(lines[i].t)) return true;
    }
    return false;
  }

  function mergeLyricLines(previous, incoming, replace) {
    if (replace || !previous || !previous.length) return incoming.slice();
    var seen = {};
    var out = [];
    function add(line) {
      var key = (finite(line.t) ? "t" + line.t : "x") + "\n" + line.text;
      if (seen[key]) return;
      seen[key] = true;
      out.push(line);
    }
    var i;
    for (i = 0; i < previous.length; i += 1) add(previous[i]);
    for (i = 0; i < incoming.length; i += 1) add(incoming[i]);
    var timed = true;
    for (i = 0; i < out.length; i += 1) {
      if (!finite(out[i].t)) {
        timed = false;
        break;
      }
    }
    if (timed) out.sort(function (a, b) { return a.t - b.t; });
    return out;
  }

  function lineIndexAt(lines, pos, previousIndex) {
    var idx = -1;
    var i;
    for (i = 0; i < lines.length; i += 1) {
      if (finite(lines[i].t) && lines[i].t <= pos) idx = i;
      else if (finite(lines[i].t)) break;
    }
    if (previousIndex >= 0 && idx < previousIndex) {
      var current = lines[previousIndex];
      if (current && finite(current.t) && pos + 0.05 >= current.t) return previousIndex;
    }
    return idx;
  }

  function lyricLookPosition(mediaPosition, offsetMs) {
    var off = Number(offsetMs);
    var delay = finite(off) ? off / 1000 : 0;
    var pos = Number(mediaPosition);
    if (!finite(pos)) return 0;
    return pos - delay;
  }

  function arrivalPosition(args) {
    var mediaPosition = args.mediaPosition;
    if (!finite(mediaPosition)) return null;
    var lastUpdatedMs = args.lastUpdatedMs;
    var nowMs = args.nowMs;
    var lat = finite(lastUpdatedMs) ? Math.max(0, (nowMs - lastUpdatedMs) / 1000) : 0;
    var samples = args.latSamples && args.latSamples.slice ? args.latSamples.slice() : [];
    samples.push(lat);
    while (samples.length > LAT_WINDOW) samples.shift();
    var base = samples.length ? Math.min.apply(Math, samples) : lat;
    var delay = clamp(lat - base, 0, LAT_CLAMP_S);
    var pos = mediaPosition;
    if (
      args.playing &&
      finite(args.mediaPositionUpdatedAtMs) &&
      finite(lastUpdatedMs)
    ) {
      pos += Math.max(0, (lastUpdatedMs - args.mediaPositionUpdatedAtMs) / 1000);
    }
    pos += delay;
    return { pos: pos, lat: lat, base: base, delay: delay, latSamples: samples };
  }

  function PlaybackClock() {
    this.resetStats();
  }

  PlaybackClock.prototype.resetStats = function () {
    this._latSamples = [];
    this._anchorPos = 0;
    this._anchorPerf = 0;
    this._speed = 1;
    this._playing = false;
    this._trackKey = null;
    this._targetPos = null;
    this._targetPerf = null;
    this._resetCount = 0;
    this._lastLat = 0;
    this._lastBase = 0;
    this._lastEmitted = 0;
    this._hasAnchor = false;
  };

  PlaybackClock.prototype.anchored = function () {
  return this._hasAnchor;
};

PlaybackClock.prototype.debug = function () {
    return {
      base: this._lastBase,
      lat: this._lastLat,
      speed: this._speed,
      resetCount: this._resetCount
    };
  };

  PlaybackClock.prototype.observe = function (sample) {
    var arrival = arrivalPosition({
      mediaPosition: sample.mediaPosition,
      mediaPositionUpdatedAtMs: sample.mediaPositionUpdatedAtMs,
      lastUpdatedMs: sample.lastUpdatedMs,
      nowMs: sample.nowMs,
      playing: sample.playing,
      latSamples: this._latSamples
    });
    if (!arrival) {
      this._hasAnchor = false;
      return { action: "clear" };
    }
    this._latSamples = arrival.latSamples;
    this._lastLat = arrival.lat;
    this._lastBase = arrival.base;
    var trackChanged = sample.trackKey !== this._trackKey;
    var playChanged = sample.playing !== this._playing;
    var hardReset = trackChanged || playChanged || !this._hasAnchor;
    if (hardReset) {
      this._trackKey = sample.trackKey;
      this._playing = sample.playing;
      this._anchorPos = arrival.pos;
      this._anchorPerf = sample.nowPerf;
      this._speed = 1;
      this._targetPos = null;
      this._targetPerf = null;
      this._hasAnchor = true;
      this._resetCount += 1;
      this._lastEmitted = arrival.pos;
      return { action: "reset", pos: arrival.pos };
    }
    var predicted = this.position(sample.nowPerf);
    var err = arrival.pos - predicted;
    var abs = Math.abs(err);
    if (abs < IGNORE_ERR_S) return { action: "ignore", pos: predicted, err: err };
    if (abs > GRADUAL_ERR_S) {
      this._anchorPos = arrival.pos;
      this._anchorPerf = sample.nowPerf;
      this._speed = 1;
      this._targetPos = null;
      this._targetPerf = null;
      this._resetCount += 1;
      this._lastEmitted = arrival.pos;
      return { action: "reset", pos: arrival.pos, err: err };
    }
    this._targetPos = arrival.pos;
    this._targetPerf = sample.nowPerf;
    this._speed = err > 0 ? SPEED_MAX : SPEED_MIN;
    this._anchorPos = predicted;
    this._anchorPerf = sample.nowPerf;
    return { action: "gradual", pos: predicted, err: err, speed: this._speed };
  };

  PlaybackClock.prototype.position = function (nowPerf) {
    if (!this._hasAnchor) return 0;
    var pos = this._anchorPos + (this._playing ? ((nowPerf - this._anchorPerf) / 1000) * this._speed : 0);
    if (
      this._playing &&
      this._targetPos != null &&
      this._targetPerf != null &&
      this._speed !== 1
    ) {
      if (this._speed > 1 && pos >= this._targetPos) {
        pos = this._targetPos;
        this._anchorPos = pos;
        this._anchorPerf = nowPerf;
        this._speed = 1;
        this._targetPos = null;
        this._targetPerf = null;
      } else if (this._speed < 1 && pos <= this._targetPos) {
        pos = this._targetPos;
        this._anchorPos = pos;
        this._anchorPerf = nowPerf;
        this._speed = 1;
        this._targetPos = null;
        this._targetPerf = null;
      }
    }
    if (pos < this._lastEmitted) pos = this._lastEmitted;
    else this._lastEmitted = pos;
    return Math.max(0, pos);
  };

  function formatTime(seconds) {
    var whole = Math.max(0, Math.floor(Number(seconds) || 0));
    var minutes = Math.floor(whole / 60);
    var remain = whole % 60;
    return minutes + ":" + (remain < 10 ? "0" : "") + remain;
  }

  function emptyLyricsText(status, lyricCurrent) {
    if (status === "not_found") return "Lyrics not available for this song";
    if (status === "instrumental") return "Instrumental";
    if (status === "plain") return "";
    if (lyricCurrent) return String(lyricCurrent);
    if (status === "error" || status === "disabled" || !status) return "";
    return "No lyrics";
  }

  function lyricsSourceLabel(source) {
    if (source === "lrclib") return "Lyrics: LRCLIB";
    if (source === "qqmusic") return "Lyrics: QQ Music";
    if (source === "lyricsovh") return "Lyrics: lyrics.ovh";
    return "";
  }

  function trackKey(attrs) {
    var a = attrs || {};
    return [a.media_title || "", a.media_artist || "", a.media_album_name || ""].join("|");
  }

  root.SpinJamLogic = {
    PLATFORM: PLATFORM,
    RETRY_MS: RETRY_MS,
    retryDelayMs: retryDelayMs,
    normalizeBaseUrl: normalizeBaseUrl,
    websocketUrl: websocketUrl,
    absoluteUrl: absoluteUrl,
    sameOrigin: sameOrigin,
    resolveSpinJam: resolveSpinJam,
    applyEntityEvent: applyEntityEvent,
    presentation: presentation,
    lyricOffsetMs: lyricOffsetMs,
    parseLyricLines: parseLyricLines,
    hasTimedLines: hasTimedLines,
    mergeLyricLines: mergeLyricLines,
    lineIndexAt: lineIndexAt,
    lyricLookPosition: lyricLookPosition,
    arrivalPosition: arrivalPosition,
    PlaybackClock: PlaybackClock,
    formatTime: formatTime,
    emptyLyricsText: emptyLyricsText,
    lyricsSourceLabel: lyricsSourceLabel,
    trackKey: trackKey
  };
})(typeof window !== "undefined" ? window : this);
