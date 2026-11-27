import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const sandbox = {
  console,
  URL,
  Math,
  Number,
  String,
  Object,
  isFinite,
  isNaN,
};
sandbox.window = sandbox;
vm.runInNewContext(
  fs.readFileSync(new URL("../tizen/js/logic.js", import.meta.url), "utf8"),
  sandbox
);
const L = sandbox.SpinJamLogic;

test("registry lookup uses platform and translation key, not a fixed entity id", () => {
  const renamed = L.resolveSpinJam({
    entities: [
      { ei: "light.other", pl: "hue", tk: "now_playing" },
      { ei: "media_player.room_display", pl: "spinjam", tk: "now_playing" },
      { ei: "switch.room_lyrics", pl: "spinjam", tk: "lyrics" },
      { ei: "switch.room_cast", pl: "spinjam", tk: "cast" },
      { ei: "number.room_delay", pl: "spinjam", tk: "lyric_offset" },
      { ei: "sensor.room_delay_label", pl: "spinjam", tk: "lyric_delay" },
    ],
  });
  assert.equal(renamed.nowPlaying, "media_player.room_display");
  assert.equal(renamed.lyrics, "switch.room_lyrics");
  assert.equal(renamed.lyricDelay, "number.room_delay");
});

test("full registry list falls back to unique id", () => {
  const found = L.resolveSpinJam([
    {
      entity_id: "media_player.custom",
      platform: "spinjam",
      unique_id: "spinjam_now_playing",
    },
    {
      entity_id: "switch.custom_lyrics",
      platform: "spinjam",
      unique_id: "spinjam_lyrics",
    },
    {
      entity_id: "number.custom_delay",
      platform: "spinjam",
      unique_id: "spinjam_lyric_offset",
    },
  ]);
  assert.equal(found.nowPlaying, "media_player.custom");
  assert.equal(found.lyrics, "switch.custom_lyrics");
  assert.equal(found.lyricDelay, "number.custom_delay");
});

test("base url and websocket use the origin only", () => {
  assert.equal(L.normalizeBaseUrl("  http://ha.example:8123/spinjam-tv/now  "), "http://ha.example:8123");
  assert.equal(L.normalizeBaseUrl("not a url"), "");
  assert.equal(L.websocketUrl("https://ha.example:8123"), "wss://ha.example:8123/api/websocket");
  const art = L.absoluteUrl(
    "http://ha.example:8123",
    "/api/media_player_proxy/media_player.custom?token=picture"
  );
  assert.equal(art, "http://ha.example:8123/api/media_player_proxy/media_player.custom?token=picture");
  assert.equal(L.sameOrigin("http://ha.example:8123", art), true);
  assert.equal(L.sameOrigin("http://ha.example:8123", "https://cdn.example/cover.jpg"), false);
});

test("compressed entity events add, patch, and remove", () => {
  let states = L.applyEntityEvent({}, {
    a: {
      "media_player.custom": {
        s: "playing",
        a: { media_title: "First", artwork_next: "http://cdn.example/next.jpg", lyric_lines: [{ t: 1, text: "Hello" }] },
        lc: 1_700_000_000,
      },
    },
  });
  assert.equal(states["media_player.custom"].state, "playing");
  assert.equal(states["media_player.custom"].attributes.media_title, "First");
  assert.equal(states["media_player.custom"].last_updated_ms, 1_700_000_000_000);

  states = L.applyEntityEvent(states, {
    c: {
      "media_player.custom": {
        "+": { s: "paused", lu: 1_700_000_002, a: { media_title: "Second" } },
        "-": { a: ["artwork_next"] },
      },
    },
  });
  assert.equal(states["media_player.custom"].state, "paused");
  assert.equal(states["media_player.custom"].attributes.media_title, "Second");
  assert.equal(states["media_player.custom"].attributes.lyric_lines[0].text, "Hello");
  assert.equal("artwork_next" in states["media_player.custom"].attributes, false);
  assert.equal(states["media_player.custom"].last_updated_ms, 1_700_000_002_000);
  assert.equal(states["media_player.custom"].last_changed_ms, 1_700_000_000_000);

  states = L.applyEntityEvent(states, { r: ["media_player.custom"] });
  assert.equal(states["media_player.custom"], undefined);
});

test("lyrics on is the split view, lyrics off is the stage, idle waits", () => {
  assert.equal(L.presentation({ playerState: "playing", lyricsSwitchState: "on" }).mode, "lyrics");
  assert.equal(L.presentation({ playerState: "paused", lyricsSwitchState: "off" }).mode, "stage");
  assert.equal(L.presentation({ playerState: "idle", lyricsSwitchState: "on" }).mode, "idle");
  assert.equal(
    L.presentation({ playerState: "playing", lyricsEnabledAttr: false }).mode,
    "stage"
  );
  assert.equal(L.lyricOffsetMs("250", 0), 250);
  assert.equal(L.lyricOffsetMs("unavailable", -40), -40);
  assert.equal(L.lyricLookPosition(12.5, 250), 12.25);
});

test("lyric lines merge by timestamp and a seek can move backward", () => {
  const first = L.parseLyricLines([
    { t: 1, text: "One" },
    { t: 5, text: "Five" },
  ]);
  const more = L.parseLyricLines([
    { t: 5, text: "Five" },
    { t: 9, text: "Nine" },
  ]);
  const merged = L.mergeLyricLines(first, more, false);
  assert.equal(merged.map((line) => line.text).join("|"), "One|Five|Nine");
  assert.equal(L.lineIndexAt(merged, 5, -1), 1);
  assert.equal(L.lineIndexAt(merged, 4.99, 1), 1);
  assert.equal(L.lineIndexAt(merged, 1, 1), 0);
});

test("playback clock advances between updates and does not step backward", () => {
  const clock = new L.PlaybackClock();
  clock.observe({
    mediaPosition: 10,
    mediaPositionUpdatedAtMs: 1_000_000,
    lastUpdatedMs: 1_000_000,
    nowMs: 1_000_050,
    nowPerf: 0,
    playing: true,
    trackKey: "Song|Artist|Album",
  });
  const later = clock.position(1000);
  assert.ok(later > 10.5 && later < 11.5, String(later));
  assert.ok(clock.position(900) >= later - 0.001);
  const jumped = clock.observe({
    mediaPosition: 40,
    mediaPositionUpdatedAtMs: 2_000_000,
    lastUpdatedMs: 2_000_000,
    nowMs: 2_000_050,
    nowPerf: 2000,
    playing: true,
    trackKey: "Song|Artist|Album",
  });
  assert.equal(jumped.action, "reset");
  assert.ok(Math.abs(clock.position(2000) - 40) < 0.2);
});

test("retry delays back off and then stay capped", () => {
  assert.deepEqual(
    [0, 1, 2, 3, 4, 5].map((attempt) => L.retryDelayMs(attempt)),
    [2000, 5000, 10000, 20000, 30000, 30000]
  );
});
