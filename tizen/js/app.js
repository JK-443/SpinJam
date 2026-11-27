(function () {
  "use strict";

  var STORAGE_KEY = "spinjam.dashboardUrl";
  var BACK_KEYS = { 10009: true, 461: true };
  var RETRY_MS = [2000, 5000, 10000, 20000, 30000];

  var settingsEl = document.getElementById("settings");
  var viewerEl = document.getElementById("viewer");
  var formEl = document.getElementById("settings-form");
  var inputEl = document.getElementById("dashboard-url");
  var errorEl = document.getElementById("settings-error");
  var openEl = document.getElementById("open");
  var frameEl = document.getElementById("dashboard");
  var statusEl = document.getElementById("status");

  var savedUrl = "";
  var loadedUrl = "";
  var showingDashboard = false;
  var frameLoaded = false;
  var retryCount = 0;
  var retryTimer = null;
  var watchdog = null;

  function readStoredUrl() {
    try {
      return window.localStorage.getItem(STORAGE_KEY) || "";
    } catch (err) {
      return "";
    }
  }

  function writeStoredUrl(url) {
    try {
      window.localStorage.setItem(STORAGE_KEY, url);
      return true;
    } catch (err) {
      return false;
    }
  }

  function normalizeUrl(raw) {
    var value = String(raw || "").trim();
    if (!/^https?:\/\//i.test(value)) {
      return "";
    }
    try {
      var parsed = new URL(value);
      if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
        return "";
      }
      return parsed.toString();
    } catch (err) {
      return "";
    }
  }

  function keepAwake() {
    try {
      if (window.webapis && webapis.appcommon && webapis.appcommon.setScreenSaver) {
        var off = 0;
        var states = webapis.appcommon.AppCommonScreenSaverState;
        if (states && typeof states.SCREEN_SAVER_OFF !== "undefined") {
          off = states.SCREEN_SAVER_OFF;
        }
        webapis.appcommon.setScreenSaver(
          off,
          function () {},
          function () {}
        );
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

  function showStatus(text) {
    statusEl.hidden = false;
    statusEl.textContent = text;
  }

  function hideStatus() {
    statusEl.hidden = true;
    statusEl.textContent = "";
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

  function armWatchdog() {
    clearWatchdog();
    watchdog = window.setTimeout(function () {
      if (!frameLoaded) {
        scheduleReload("The dashboard did not load");
      }
    }, 20000);
  }

  function scheduleReload(reason) {
    if (!showingDashboard || !savedUrl || retryTimer) {
      return;
    }
    loadedUrl = "";
    showStatus(reason + ". Reconnecting…");
    var delay = RETRY_MS[Math.min(retryCount, RETRY_MS.length - 1)];
    retryCount += 1;
    retryTimer = window.setTimeout(function () {
      retryTimer = null;
      loadFrame(true);
    }, delay);
  }

  function loadFrame(bounce) {
    if (!savedUrl) {
      return;
    }
    frameLoaded = false;
    loadedUrl = savedUrl;
    armWatchdog();
    if (!bounce) {
      frameEl.src = savedUrl;
      return;
    }
    frameEl.src = "about:blank";
    window.setTimeout(function () {
      if (showingDashboard && savedUrl) {
        frameEl.src = savedUrl;
      }
    }, 40);
  }

  function showSettings() {
    showingDashboard = false;
    clearRetry();
    clearWatchdog();
    hideStatus();
    viewerEl.hidden = true;
    settingsEl.hidden = false;
    inputEl.value = savedUrl;
    openEl.hidden = !savedUrl;
    errorEl.textContent = "";
    window.setTimeout(function () {
      inputEl.focus();
    }, 0);
  }

  function showDashboard() {
    if (!savedUrl) {
      showSettings();
      return;
    }
    showingDashboard = true;
    settingsEl.hidden = true;
    viewerEl.hidden = false;
    if (loadedUrl !== savedUrl) {
      loadFrame(false);
    }
  }

  function onSave(event) {
    if (event) {
      event.preventDefault();
    }
    var next = normalizeUrl(inputEl.value);
    if (!next) {
      errorEl.textContent = "Enter a full http or https address.";
      inputEl.focus();
      return;
    }
    if (!writeStoredUrl(next)) {
      errorEl.textContent = "This TV could not store the address.";
      return;
    }
    savedUrl = next;
    errorEl.textContent = "";
    showDashboard();
  }

  function onBack(event) {
    event.preventDefault();
    if (event.stopPropagation) {
      event.stopPropagation();
    }
    if (showingDashboard && savedUrl) {
      showSettings();
      return;
    }
    if (!showingDashboard && savedUrl) {
      showDashboard();
    }
  }

  function onKey(event) {
    if (BACK_KEYS[event.keyCode]) {
      onBack(event);
    }
  }

  frameEl.addEventListener("load", function () {
    var src = frameEl.src || "";
    if (!src || src === "about:blank") {
      return;
    }
    frameLoaded = true;
    retryCount = 0;
    clearRetry();
    clearWatchdog();
    hideStatus();
  });

  frameEl.addEventListener("error", function () {
    scheduleReload("The dashboard failed to load");
  });

  window.addEventListener("offline", function () {
    scheduleReload("The network dropped");
  });

  window.addEventListener("online", function () {
    retryCount = 0;
    clearRetry();
    if (showingDashboard && savedUrl) {
      loadFrame(true);
    }
  });

  window.addEventListener("keydown", onKey, true);
  formEl.addEventListener("submit", onSave);
  openEl.addEventListener("click", function () {
    showDashboard();
  });

  registerKeys();
  keepAwake();
  window.setInterval(keepAwake, 30000);
  window.setInterval(function () {
    if (showingDashboard && savedUrl && navigator.onLine === false) {
      scheduleReload("The network dropped");
    }
  }, 15000);

  savedUrl = normalizeUrl(readStoredUrl());
  if (savedUrl) {
    showDashboard();
  } else {
    showSettings();
  }
})();
