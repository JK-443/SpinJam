import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CARD_MODE_CAST,
  CARD_MODE_DETAILS,
  CARD_MODE_HIDDEN,
  CARD_MODE_LYRICS,
  CARD_MODE_STAGE,
  slotLayoutPatch,
  LAYOUT_TRANSITION_MS,
  STAGE_ART_HEIGHT_RATIO,
  resolveCardPresentation,
  stageArtSizePx,
  stageMissingArt,
  CAST_LYRIC_PAD_RATIO,
  LYRIC_EMPHASIS_SCALE,
  castLyricLineMaxPx,
  formatLyricDelay,
  formatLyricDelaySeconds,
  lyricDelayToast,
} from "../custom_components/spinjam/www/spinjam-card-layout.js";

test("lyrics on keeps the two-panel layout", () => {
  const details = resolveCardPresentation({
    configuredMode: "details",
    lyricsEnabled: true,
    siblingShowsStage: false,
  });
  const lyrics = resolveCardPresentation({
    configuredMode: "lyrics",
    lyricsEnabled: true,
    siblingShowsStage: true,
  });
  assert.equal(details.mode, CARD_MODE_DETAILS);
  assert.equal(details.collapseSlot, false);
  assert.equal(details.expandSlot, false);
  assert.equal(lyrics.mode, CARD_MODE_LYRICS);
  assert.equal(lyrics.collapseSlot, false);
  assert.equal(lyrics.expandSlot, false);
});

test("cast mode is one card: split when lyrics are on, stage when off", () => {
  const on = resolveCardPresentation({
    configuredMode: "cast",
    lyricsEnabled: true,
  });
  const off = resolveCardPresentation({
    configuredMode: "cast",
    lyricsEnabled: false,
    siblingShowsStage: true,
  });
  assert.equal(on.mode, CARD_MODE_CAST);
  assert.equal(on.fullBleed, true);
  assert.equal(on.collapseSlot, false);
  assert.equal(off.mode, CARD_MODE_STAGE);
  assert.equal(off.fullBleed, true);
  assert.equal(off.collapseSlot, false);
  assert.equal(off.expandSlot, false);
});

test("a leftover lyrics card collapses its grid column when lyrics are off", () => {
  const hidden = resolveCardPresentation({
    configuredMode: "lyrics",
    lyricsEnabled: false,
    siblingShowsStage: true,
  });
  const patch = slotLayoutPatch(hidden, "grid");
  assert.equal(hidden.mode, CARD_MODE_HIDDEN);
  assert.equal(patch.hostDisplay, "none");
  assert.equal(patch.slotDisplay, "none");
  assert.equal(patch.parentGridTemplateColumns, "1fr");
  const stage = resolveCardPresentation({
    configuredMode: "details",
    lyricsEnabled: false,
  });
  const expanded = slotLayoutPatch(stage, "grid");
  assert.equal(expanded.slotGridColumn, "1 / -1");
  assert.equal(expanded.slotWidth, "100%");
});

test("missing lyrics_enabled stays in lyrics mode (default on)", () => {
  const lyrics = resolveCardPresentation({ configuredMode: "lyrics" });
  assert.equal(lyrics.mode, CARD_MODE_LYRICS);
  assert.equal(lyrics.collapseSlot, false);
});

test("lyrics off on the details card is one full-width stage", () => {
  const stage = resolveCardPresentation({
    configuredMode: "details",
    lyricsEnabled: false,
    siblingShowsStage: false,
  });
  assert.equal(stage.mode, CARD_MODE_STAGE);
  assert.equal(stage.expandSlot, true);
  assert.equal(stage.collapseSlot, false);
});

test("lyrics off collapses the lyrics card when a details sibling owns the stage", () => {
  const hidden = resolveCardPresentation({
    configuredMode: "lyrics",
    lyricsEnabled: false,
    siblingShowsStage: true,
  });
  assert.equal(hidden.mode, CARD_MODE_HIDDEN);
  assert.equal(hidden.collapseSlot, true);
  assert.equal(hidden.expandSlot, false);
});

test("a lone lyrics card becomes the stage when lyrics are off", () => {
  const stage = resolveCardPresentation({
    configuredMode: "lyrics",
    lyricsEnabled: false,
    siblingShowsStage: false,
  });
  assert.equal(stage.mode, CARD_MODE_STAGE);
  assert.equal(stage.expandSlot, true);
});

test("toggling lyrics only changes presentation (no recast flag)", () => {
  const on = resolveCardPresentation({
    configuredMode: "details",
    lyricsEnabled: true,
  });
  const off = resolveCardPresentation({
    configuredMode: "details",
    lyricsEnabled: false,
  });
  assert.equal(on.mode, CARD_MODE_DETAILS);
  assert.equal(off.mode, CARD_MODE_STAGE);
  assert.equal(Object.hasOwn(off, "recast"), false);
  assert.ok(LAYOUT_TRANSITION_MS >= 200);
});

test("missing art uses a placeholder, present art does not", () => {
  assert.equal(stageMissingArt("", ""), true);
  assert.equal(stageMissingArt(null, undefined), true);
  assert.equal(stageMissingArt("/local/cover.jpg", ""), false);
  assert.equal(stageMissingArt("", "https://example.invalid/hd.jpg"), false);
});

test("stage cover is 55-65% of a 16:9 viewport height", () => {
  assert.ok(STAGE_ART_HEIGHT_RATIO >= 0.55);
  assert.ok(STAGE_ART_HEIGHT_RATIO <= 0.65);
  const height = 1080;
  const width = 1920;
  const size = stageArtSizePx(height, width, height);
  const ratio = size / height;
  assert.ok(ratio >= 0.55 && ratio <= 0.65, `ratio ${ratio}`);
});

test("lyric delay label and toast name the direction", () => {
  assert.equal(formatLyricDelaySeconds(2000), "+2.0 s");
  assert.equal(formatLyricDelay(2000), "+2.0 s (later)");
  assert.equal(formatLyricDelaySeconds(2250), "+2.25 s");
  assert.equal(formatLyricDelay(-250), "-0.25 s (earlier)");
  assert.equal(formatLyricDelay(0), "0.0 s (on time)");
  assert.equal(lyricDelayToast(2000, 2250), "Lyrics +250 ms later, now +2.25 s");
  assert.equal(lyricDelayToast(2000, 1750), "Lyrics -250 ms earlier, now +1.75 s");
});

test("cast lyric line fits the pane after padding and the scale-up", () => {
  assert.equal(CAST_LYRIC_PAD_RATIO, 0.04);
  const pane = 960;
  const inner = pane * (1 - CAST_LYRIC_PAD_RATIO * 2);
  const max = castLyricLineMaxPx(inner);
  assert.ok(max > 0);
  assert.ok(max * LYRIC_EMPHASIS_SCALE <= inner + 0.01);
  assert.equal(castLyricLineMaxPx(0), 0);
});

test("narrow card still keeps a square that fits the width", () => {
  const size = stageArtSizePx(1000, 400, 1000);
  assert.ok(size <= 400 * 0.46 + 1);
  assert.ok(size >= 96);
});
