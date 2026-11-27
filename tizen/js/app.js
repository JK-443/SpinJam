(function () {
  "use strict";

  var URL_KEY = "spinjam.baseUrl";
  var TOKEN_KEY = "spinjam.accessToken";
  var BACK_KEYS = { 10009: true, 461: true };
  var HOLD_MS = 700;
  var L = window.SpinJamLogic;

  var settingsEl = document.getElementById("settings");
  var playerEl = document.getElementById("player");
  var formEl = document.getElementById("settings-form");
  var urlInput = document.getElementById("ha-base-url");
  var tokenInput = document.getElementById("ha-token");
  var errorEl = document.getElementById("settings-error");
  var openEl = document.getElementById("open");
  var bannerEl = document.getElementById("banner");
  var idleEl = document.getElementById("idle");
  var idleTitleEl = document.getElementById("idle-title");
  var idleSubEl = document.getElementById("idle-sub");
  var castEl = document.getElementById("cast");
  var stageEl = document.getElementById("stage");
  var stageBgEl = document.getElementById("stage-bg");
  var stageWrapEl = document.getElementById("stage-art-wrap");
  var castTitleEl = document.getElementById("cast-title");
  var castArtistEl = document.getElementById("cast-artist");
  var castAlbumEl = document.getElementById("cast-album");
  var stageTitleEl = document.getElementById("stage-title");
  var stageArtistEl = document.getElementById("stage-artist");
  var stageAlbumEl = document.getElementById("stage-album");
  var castProgEl = document.getElementById("cast-prog");
  var stageProgEl = document.getElementById("stage-prog");
  var castTl = document.getElementById("cast-tl");
  var castTr = document.getElementById("cast-tr");
  var stageTl = document.getElementById("stage-tl");
  var stageTr = document.getElementById("stage-tr");
  var castFill = document.getElementById("cast-fill");
  var stageFill = document.getElementById("stage-fill");
  var lyricMsgEl = document.getElementById("lyric-msg");
  var lyricVpEl = document.getElementById("lyric-vp");
  var lyricListEl = document.getElementById("lyric-list");
  var lyricAttribEl = document.getElementById("lyric-attrib");
  var artLayers = [
    [document.getElementById("la0"), document.getElementById("la1")],
    [document.getElementById("sa0"), document.getElementById("sa1")],
    [document.getElementById("sb0"), document.getElementById("sb1")]
  ];

  var baseUrl = "";
  var token = "";
  var showingPlayer = false;
  var socket = null;
  var closing = false;
  var authed = false;
  var authRejected = false;
  var nextId = 1;
  var pending = {};
  var subs = {};
  var retryCount = 0;
  var retryTimer = null;
  var watchdog = null;
  var registryTimer = null;
  var states = {};
  var resolved = { nowPlaying: null, lyrics: null, lyricDelay: null };
  var subscribedKey = "";
  var currentMode = "idle";
  var playing = false;
  var lines = [];
  var lineIdx = -2;
  var lineSig = "";
  var plain = false;
  var offsetMs = 0;
  var track = "";
  var clock = new L.PlaybackClock();
  var raf = null;
  var holdTimer = null;
  var holdFired = false;
  var artKey = "";
  var artFront = 0;
  var blobList = [];
  var attrs = {};

  function readStored(key) {
    try {
      return window.localStorage.getItem(key) || "";
    } catch (err) {
      return "";
    }
  }

  function writeStored(key, value) {
    try {
      window.localStorage.setItem(key, value);
      return true;
    } catch (err) {
      return false;
    }
  }

  function nowPerf() {
    if (window.performance && performance.now) return performance.now();
    return Date.now();
  }

  function keepAwake() {
    try {
      if (window.webapis && webapis.appcommon && webapis.appcommon.setScreenSaver) {
        var off = 0;
        var screenStates = webapis.appcommon.AppCommonScreenSaverState;
        if (screenStates && typeof screenStates.SCREEN_SAVER_OFF !== "undefined") {
          off = screenStates.SCREEN_SAVER_OFF;
        }
        webapis.appcommon.setScreenSaver(off, function () {}, function () {});
      }
    } catch (err) {}
    try {
      if (window.tizen && tizen.power && tizen.power.request) {
        tizen.power.request("SCREEN", "SCREEN_NORMAL");
        tizen.power.request("CPU", "CPU_AWAKE");
      }
    } catch (err) {}
  }

  function registerKeys() {
    try {
      if (window.tizen && tizen.tvinputdevice && tizen.tvinputdevice.registerKey) {
        tizen.tvinputdevice.registerKey("Back");
      }
    } catch (err) {}
  }

  function setText(el, value) {
    var next = value || "";
    if (el.textContent !== next) el.textContent = next;
  }

  function showBanner(text) {
    bannerEl.hidden = false;
    bannerEl.textContent = text;
  }

  function hideBanner() {
    bannerEl.hidden = true;
    bannerEl.textContent = "";
  }

  function clearRetry() {
    if (retryTimer) {
      window.clearTimeout(retryTimer);
      retryTimer = null;
    }
  }

  function clearWatchdog() {
    if (watchdog) {
      window.clearTimeout(watchdog);
      watchdog = null;
    }
  }

  function clearRegistryTimer() {
    if (registryTimer) {
      window.clearTimeout(registryTimer);
      registryTimer = null;
    }
  }

  function armWatchdog() {
    clearWatchdog();
    watchdog = window.setTimeout(function () {
      if (!authed) scheduleReconnect("Home Assistant did not answer");
    }, 20000);
  }

  function scheduleReconnect(reason) {
    if (authRejected || !baseUrl || !token || retryTimer) return;
    showBanner(reason + ". Reconnecting…");
    var delay = L.retryDelayMs(retryCount);
    retryCount += 1;
    retryTimer = window.setTimeout(function () {
      retryTimer = null;
      connect();
    }, delay);
  }

  function scheduleRegistryRetry() {
    if (registryTimer || !authed) return;
    registryTimer = window.setTimeout(function () {
      registryTimer = null;
      if (socket && socket.readyState === 1) requestRegistry();
    }, 15000);
  }

  function sendRaw(obj) {
    if (!socket || socket.readyState !== 1) return;
    socket.send(JSON.stringify(obj));
  }

  function sendCmd(obj) {
    var id = nextId;
    nextId += 1;
    obj.id = id;
    pending[id] = obj.type;
    if (obj.type === "subscribe_entities") subs[id] = true;
    sendRaw(obj);
    return id;
  }

  function requestRegistry() {
    sendCmd({ type: "config/entity_registry/list_for_display" });
  }

  function subscribeResolved() {
    var key = [resolved.nowPlaying || "", resolved.lyrics || "", resolved.lyricDelay || ""].join("|");
    if (!resolved.nowPlaying) {
      subscribedKey = key;
      scheduleRegistryRetry();
      render();
      return;
    }
    if (key === subscribedKey) {
      render();
      return;
    }
    subscribedKey = key;
    var ids = [resolved.nowPlaying];
    if (resolved.lyrics) ids.push(resolved.lyrics);
    if (resolved.lyricDelay) ids.push(resolved.lyricDelay);
    sendCmd({ type: "subscribe_entities", entity_ids: ids });
  }

  function resetSessionState() {
    states = {};
    resolved = { nowPlaying: null, lyrics: null, lyricDelay: null };
    subscribedKey = "";
    subs = {};
    lines = [];
    lineIdx = -2;
    lineSig = "";
    track = "";
    attrs = {};
    artKey = "";
    clock.resetStats();
    paintArt("");
  }

  function connect() {
    if (!baseUrl || !token) {
      showSettings("");
      return;
    }
    clearRetry();
    clearWatchdog();
    clearRegistryTimer();
    pending = {};
    subs = {};
    subscribedKey = "";
    authed = false;
    if (socket) {
      closing = true;
      socket.onclose = null;
      socket.onerror = null;
      socket.onmessage = null;
      try { socket.close(); } catch (err) {}
      socket = null;
      closing = false;
    }
    var url;
    try {
      url = L.websocketUrl(baseUrl);
      socket = new WebSocket(url);
    } catch (err) {
      scheduleReconnect("Could not open the connection");
      return;
    }
    armWatchdog();
    socket.onopen = function () {};
    socket.onmessage = onMessage;
    socket.onerror = function () {
      scheduleReconnect("The connection failed");
    };
    socket.onclose = function () {
      socket = null;
      authed = false;
      if (closing) {
        closing = false;
        return;
      }
      scheduleReconnect("The connection closed");
    };
  }

  function onMessage(event) {
    var msg;
    try {
      msg = JSON.parse(event.data);
    } catch (err) {
      return;
    }
    if (!msg || !msg.type) return;
    if (msg.type === "ping") {
      sendRaw({ type: "pong" });
      return;
    }
    if (msg.type === "auth_required") {
      sendRaw({ type: "auth", access_token: token });
      return;
    }
    if (msg.type === "auth_invalid") {
      authRejected = true;
      clearRetry();
      clearWatchdog();
      showSettings("Home Assistant rejected the access token.");
      return;
    }
    if (msg.type === "auth_ok") {
      authed = true;
      authRejected = false;
      retryCount = 0;
      clearRetry();
      clearWatchdog();
      hideBanner();
      requestRegistry();
      return;
    }
    if (msg.type === "result") {
      var kind = pending[msg.id];
      delete pending[msg.id];
      if (!msg.success) {
        if (kind === "config/entity_registry/list_for_display") {
          sendCmd({ type: "config/entity_registry/list" });
          return;
        }
        if (kind === "config/entity_registry/list") {
          showBanner("Could not read the entity registry");
          scheduleRegistryRetry();
        }
        return;
      }
      if (kind === "config/entity_registry/list_for_display" || kind === "config/entity_registry/list") {
        resolved = L.resolveSpinJam(msg.result);
        subscribeResolved();
      }
      return;
    }
    if (msg.type === "event" && subs[msg.id] && msg.event) {
      states = L.applyEntityEvent(states, msg.event);
      render();
    }
  }

  function cssUrl(url) {
    if (!url) return "none";
    return 'url("' + String(url).replace(/\\/g, "\\\\").replace(/"/g, "%22") + '")';
  }

  function paintArt(url) {
    var idx = artFront ? 0 : 1;
    var g;
    for (g = 0; g < artLayers.length; g += 1) {
      var show = artLayers[g][idx];
      var hide = artLayers[g][1 - idx];
      show.style.backgroundImage = cssUrl(url);
      if (url) show.classList.add("show");
      else show.classList.remove("show");
      if (hide) hide.classList.remove("show");
    }
    artFront = idx;
    var missing = !url;
    stageBgEl.classList.toggle("empty", missing);
    stageWrapEl.classList.toggle("has-art", !missing);
  }

  function rememberBlob(url) {
    blobList.push(url);
    while (blobList.length > 6) {
      var old = blobList.shift();
      try { URL.revokeObjectURL(old); } catch (err) {}
    }
  }

  function resolveImage(url, cb) {
    if (!url) {
      cb("");
      return;
    }
    if (!token || !L.sameOrigin(baseUrl, url)) {
      cb(url);
      return;
    }
    var xhr = new XMLHttpRequest();
    xhr.open("GET", url, true);
    xhr.responseType = "blob";
    xhr.setRequestHeader("Authorization", "Bearer " + token);
    xhr.onload = function () {
      if (xhr.status >= 200 && xhr.status < 300 && xhr.response) {
        var blobUrl = URL.createObjectURL(xhr.response);
        rememberBlob(blobUrl);
        cb(blobUrl);
      } else {
        cb(url);
      }
    };
    xhr.onerror = function () { cb(url); };
    xhr.send();
  }

  function updateArt(active) {
    var lo = active ? L.absoluteUrl(baseUrl, attrs.entity_picture || "") : "";
    var hd = active ? L.absoluteUrl(baseUrl, attrs.artwork_hd || "") : "";
    var key = lo + "|" + hd;
    if (key === artKey) return;
    artKey = key;
    if (attrs.artwork_next && active) {
      var next = L.absoluteUrl(baseUrl, attrs.artwork_next);
      if (next && !L.sameOrigin(baseUrl, next)) {
        var ahead = new Image();
        ahead.src = next;
      }
    }
    if (!lo && !hd) {
      paintArt("");
      return;
    }
    var first = lo || hd;
    resolveImage(first, function (url) {
      if (artKey !== key) return;
      paintArt(url);
    });
    if (hd && lo && hd !== lo) {
      resolveImage(hd, function (url) {
        if (artKey !== key) return;
        paintArt(url);
      });
    }
  }

  function renderLines(nextLines) {
    lyricListEl.style.transition = "none";
    lyricListEl.style.webkitTransform = "translateY(0)";
    lyricListEl.style.transform = "translateY(0)";
    lyricListEl.textContent = "";
    var i;
    for (i = 0; i < nextLines.length; i += 1) {
      var line = nextLines[i];
      var li = document.createElement("li");
      var span = document.createElement("span");
      span.textContent = line.text || "\u266a";
      li.appendChild(span);
      lyricListEl.appendChild(li);
    }
    lineIdx = -2;
  }

  function scrollLyrics(animate) {
    var items = lyricListEl.children;
    if (!items.length) return;
    var index = lineIdx < 0 ? 0 : lineIdx;
    var li = items[index];
    if (!li) return;
    var vh = lyricVpEl.clientHeight || 600;
    var off = li.offsetTop + li.offsetHeight / 2 - vh / 2;
    if (lineIdx < 0) off -= li.offsetHeight;
    var transition = animate ? "" : "none";
    lyricListEl.style.transition = transition;
    lyricListEl.style.webkitTransition = animate ? "" : "none";
    var shift = "translateY(" + (-off) + "px)";
    lyricListEl.style.webkitTransform = shift;
    lyricListEl.style.transform = shift;
  }

  function setLineIndex(idx, animate) {
    if (idx === lineIdx) return;
    var prev = lineIdx;
    lineIdx = idx;
    var items = lyricListEl.children;
    var i;
    for (i = 0; i < items.length; i += 1) {
      var distance = i - idx;
      var cls = "";
      if (distance === 0) cls = "cur";
      else if (distance < 0) cls = "past";
      else if (distance === 1) cls = "n1";
      else if (distance === 2) cls = "n2";
      else if (distance === 3) cls = "n3";
      if (items[i].className !== cls) items[i].className = cls;
    }
    var glide = animate && prev >= -1 && idx >= 0 && Math.abs(idx - prev) <= 3;
    scrollLyrics(glide);
  }

  function renderLyricHighlight(animate) {
    if (currentMode !== "lyrics" || plain || !lines.length) return;
    var pos = L.lyricLookPosition(clock.position(nowPerf()), offsetMs);
    var idx = L.hasTimedLines(lines)
      ? L.lineIndexAt(lines, pos, lineIdx)
      : lineIdx;
    setLineIndex(idx, animate);
  }

  function renderProgress() {
    var duration = Number(attrs.media_duration);
    var show = currentMode !== "idle" && isFinite(duration) && duration > 0 && clock.anchored();
    castProgEl.hidden = !show || currentMode !== "lyrics";
    stageProgEl.hidden = !show || currentMode !== "stage";
    if (!show) return;
    var pos = Math.min(duration, Math.max(0, clock.position(nowPerf())));
    var scale = "scaleX(" + (pos / duration) + ")";
    castFill.style.webkitTransform = scale;
    castFill.style.transform = scale;
    stageFill.style.webkitTransform = scale;
    stageFill.style.transform = scale;
    var left = L.formatTime(pos);
    var right = L.formatTime(duration);
    setText(castTl, left);
    setText(stageTl, left);
    setText(castTr, right);
    setText(stageTr, right);
  }

  function observeClock(player, active) {
    var position = Number(attrs.media_position);
    if (!active || !isFinite(position)) {
      if (!active) clock.resetStats();
      return;
    }
    var updated = Date.parse(attrs.media_position_updated_at || "");
    clock.observe({
      mediaPosition: position,
      mediaPositionUpdatedAtMs: isNaN(updated) ? NaN : updated,
      lastUpdatedMs: player.last_updated_ms,
      nowMs: Date.now(),
      nowPerf: nowPerf(),
      playing: player.state === "playing",
      trackKey: track
    });
  }

  function render() {
    var player = resolved.nowPlaying ? states[resolved.nowPlaying] : null;
    var lyricsSwitch = resolved.lyrics ? states[resolved.lyrics] : null;
    var delay = resolved.lyricDelay ? states[resolved.lyricDelay] : null;
    attrs = (player && player.attributes) || {};
    var view = L.presentation({
      playerState: player ? player.state : "",
      lyricsSwitchState: lyricsSwitch ? lyricsSwitch.state : "",
      lyricsEnabledAttr: attrs.lyrics_enabled
    });
    currentMode = view.mode;
    playing = view.playing;
    offsetMs = L.lyricOffsetMs(delay ? delay.state : null, attrs.lyric_offset_ms);
    var nextTrack = L.trackKey(attrs);
    var trackChanged = nextTrack !== track;
    if (trackChanged) {
      track = nextTrack;
      lineIdx = -2;
    }
    if (player) observeClock(player, view.active);

    var status = String(attrs.lyrics_status || "");
    var incoming = view.lyricsOn ? L.parseLyricLines(attrs.lyric_lines) : [];
    var replaceLines = trackChanged || status === "plain" || !L.hasTimedLines(incoming);
    lines = L.mergeLyricLines(lines, incoming, replaceLines);
    plain = status === "plain" && lines.length > 0;
    var sig = status + "|" + lines.length + "|" + (lines.length ? lines[0].t + lines[0].text : "") + "|" + (lines.length ? lines[lines.length - 1].t + lines[lines.length - 1].text : "");
    if (sig !== lineSig) {
      lineSig = sig;
      renderLines(lines);
    }

    idleEl.hidden = currentMode !== "idle";
    castEl.hidden = currentMode !== "lyrics";
    stageEl.hidden = currentMode !== "stage";

    if (!authed && !player) {
      setText(idleTitleEl, "Connecting\u2026");
      setText(idleSubEl, "");
    } else if (!resolved.nowPlaying && authed) {
      setText(idleTitleEl, "Waiting for music");
      setText(idleSubEl, "SpinJam is not set up in Home Assistant.");
    } else {
      setText(idleTitleEl, "Waiting for music");
      setText(idleSubEl, "Back opens settings.");
    }

    var title = view.active ? (attrs.media_title || "") : "";
    var artist = view.active ? (attrs.media_artist || "") : "";
    var album = view.active ? (attrs.media_album_name || "") : "";
    setText(castTitleEl, title);
    setText(castArtistEl, artist);
    setText(castAlbumEl, album);
    setText(stageTitleEl, title || "SpinJam");
    setText(stageArtistEl, artist);
    setText(stageAlbumEl, album);
    castAlbumEl.hidden = !album;
    stageAlbumEl.hidden = !album;

    updateArt(view.active);
    setText(lyricAttribEl, view.lyricsOn && view.active ? L.lyricsSourceLabel(attrs.lyrics_source) : "");

    if (currentMode === "lyrics" && plain) {
      lyricVpEl.hidden = true;
      lyricMsgEl.hidden = false;
      lyricMsgEl.className = "msg plain";
      var parts = [];
      var i;
      for (i = 0; i < lines.length; i += 1) parts.push(lines[i].text);
      setText(lyricMsgEl, parts.join("\n"));
    } else if (currentMode === "lyrics" && !lines.length) {
      lyricVpEl.hidden = true;
      var empty = L.emptyLyricsText(status, attrs.lyric_current);
      lyricMsgEl.hidden = !empty;
      lyricMsgEl.className = "msg";
      setText(lyricMsgEl, empty);
    } else if (currentMode === "lyrics") {
      lyricVpEl.hidden = false;
      lyricMsgEl.hidden = true;
      renderLyricHighlight(false);
      window.requestAnimationFrame(function () {
        if (currentMode === "lyrics" && !plain) scrollLyrics(false);
      });
    }

    renderProgress();
    if (showingPlayer && playing) startLoop();
    else stopLoop();
  }

  function frame() {
    raf = null;
    if (!showingPlayer || !playing) return;
    renderProgress();
    renderLyricHighlight(true);
    startLoop();
  }

  function startLoop() {
    if (raf || !showingPlayer || !playing) return;
    raf = window.requestAnimationFrame(frame);
  }

  function stopLoop() {
    if (!raf) return;
    window.cancelAnimationFrame(raf);
    raf = null;
  }

  function showSettings(message) {
    showingPlayer = false;
    stopLoop();
    playerEl.hidden = true;
    settingsEl.hidden = false;
    urlInput.value = baseUrl;
    tokenInput.value = token;
    openEl.hidden = !(baseUrl && token);
    errorEl.textContent = message || "";
    window.setTimeout(function () { urlInput.focus(); }, 0);
  }

  function showPlayer() {
    if (!baseUrl || !token) {
      showSettings("");
      return;
    }
    showingPlayer = true;
    settingsEl.hidden = true;
    playerEl.hidden = false;
    errorEl.textContent = "";
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    try { playerEl.focus(); } catch (err) {}
    render();
  }

  function onSave(event) {
    if (event) event.preventDefault();
    var nextUrl = L.normalizeBaseUrl(urlInput.value);
    var nextToken = String(tokenInput.value || "").replace(/^\s+|\s+$/g, "");
    if (!nextUrl) {
      errorEl.textContent = "Enter the Home Assistant address, including http:// or https://.";
      urlInput.focus();
      return;
    }
    if (!nextToken) {
      errorEl.textContent = "Enter a long-lived access token.";
      tokenInput.focus();
      return;
    }
    if (!writeStored(URL_KEY, nextUrl) || !writeStored(TOKEN_KEY, nextToken)) {
      errorEl.textContent = "This TV could not store the address.";
      return;
    }
    var changed = nextUrl !== baseUrl || nextToken !== token;
    baseUrl = nextUrl;
    token = nextToken;
    authRejected = false;
    errorEl.textContent = "";
    if (changed) resetSessionState();
    showPlayer();
    connect();
  }

  function onBackShort() {
    if (!showingPlayer) {
      if (baseUrl && token) showPlayer();
      return;
    }
    if (currentMode === "idle") showSettings("");
  }

  function isBack(event) {
    return !!BACK_KEYS[event.keyCode] || event.key === "Back" || event.key === "XF86Back" || event.key === "BrowserBack";
  }

  function onKeyDown(event) {
    if (!isBack(event)) return;
    event.preventDefault();
    if (event.stopPropagation) event.stopPropagation();
    if (holdTimer) return;
    holdFired = false;
    holdTimer = window.setTimeout(function () {
      holdTimer = null;
      holdFired = true;
      showSettings("");
      window.setTimeout(function () { holdFired = false; }, 300);
    }, HOLD_MS);
  }

  function onKeyUp(event) {
    if (!isBack(event)) return;
    event.preventDefault();
    if (holdTimer) {
      window.clearTimeout(holdTimer);
      holdTimer = null;
      if (!holdFired) onBackShort();
    }
    holdFired = false;
  }

  window.addEventListener("keydown", onKeyDown, true);
  window.addEventListener("keyup", onKeyUp, true);
  formEl.addEventListener("submit", onSave);
  openEl.addEventListener("click", function () { showPlayer(); });

  window.addEventListener("offline", function () {
    scheduleReconnect("The network dropped");
  });
  window.addEventListener("online", function () {
    retryCount = 0;
    clearRetry();
    if (baseUrl && token && !authRejected) connect();
  });

  registerKeys();
  keepAwake();
  window.setInterval(keepAwake, 30000);
  window.setInterval(function () {
    if (baseUrl && token && navigator.onLine === false) scheduleReconnect("The network dropped");
  }, 15000);

  baseUrl = L.normalizeBaseUrl(readStored(URL_KEY));
  token = String(readStored(TOKEN_KEY) || "").replace(/^\s+|\s+$/g, "");
  if (baseUrl && token) {
    showPlayer();
    connect();
  } else {
    showSettings("");
  }
})();
