import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PlaybackClock,
  arrivalPosition,
  IGNORE_ERR_S,
} from "../custom_components/spinjam/www/spinjam-playback-clock.js";

function sample(clock, opts) {
  const {
    pos,
    playing = true,
    trackKey = "Song|Artist",
    lastUpdatedMs,
    mediaUpdatedMs,
    nowMs,
    nowPerf,
  } = opts;
  return clock.observe({
    mediaPosition: pos,
    mediaPositionUpdatedAtMs: mediaUpdatedMs,
    lastUpdatedMs,
    nowMs,
    nowPerf,
    playing,
    trackKey,
  });
}

test("delivery delay uses base lat so TV clock offset cancels", () => {
  // TV clock 30s ahead of HA: lat ≈ 30 + delivery.
  const samples = [];
  for (let i = 0; i < 10; i += 1) {
    samples.push(30.05);
  }
  const arrival = arrivalPosition({
    mediaPosition: 10,
    mediaPositionUpdatedAtMs: 1_000_000,
    lastUpdatedMs: 1_000_000,
    nowMs: 1_000_000 + 30_050, // 30.05s lat
    playing: true,
    latSamples: samples,
  });
  assert.ok(arrival);
  // delay = clamp(30.05 - 30.05, 0, 2) = 0 → pos stays ~10
  assert.ok(Math.abs(arrival.pos - 10) < 0.01);
  assert.ok(Math.abs(arrival.base - 30.05) < 0.01);
});

test("50ms updates with 0.3–0.7s spikes never go backwards within a track", () => {
  const clock = new PlaybackClock();
  let nowMs = 1_000_000;
  let nowPerf = 0;
  let mediaPos = 0;
  const mediaUpdated = nowMs;
  const positions = [];

  sample(clock, {
    pos: 0,
    lastUpdatedMs: nowMs,
    mediaUpdatedMs: mediaUpdated,
    nowMs: nowMs + 45,
    nowPerf,
    trackKey: "A|B",
  });

  for (let i = 0; i < 120; i += 1) {
    const delivery = i > 0 && i % 25 === 0 ? 300 + (i % 7) * 50 : 45;
    nowMs += 1000;
    nowPerf += 1000;
    mediaPos += 1;
    sample(clock, {
      pos: mediaPos,
      lastUpdatedMs: nowMs,
      mediaUpdatedMs: nowMs, // fresh stamp each write
      nowMs: nowMs + delivery,
      nowPerf: nowPerf + delivery,
      trackKey: "A|B",
    });
    // Advance local clock ~1s between updates.
    for (let t = 0; t < 10; t += 1) {
      positions.push(clock.position(nowPerf + delivery + t * 100));
    }
  }

  for (let i = 1; i < positions.length; i += 1) {
    assert.ok(
      positions[i] + 1e-9 >= positions[i - 1],
      `backwards at ${i}: ${positions[i - 1]} -> ${positions[i]}`
    );
  }
});

test("10s seek resets immediately", () => {
  const clock = new PlaybackClock();
  sample(clock, {
    pos: 20,
    lastUpdatedMs: 1000,
    mediaUpdatedMs: 1000,
    nowMs: 1045,
    nowPerf: 0,
  });
  const before = clock.position(500);
  const result = sample(clock, {
    pos: 10,
    lastUpdatedMs: 2000,
    mediaUpdatedMs: 2000,
    nowMs: 2045,
    nowPerf: 1000,
  });
  assert.equal(result.action, "reset");
  assert.ok(clock.position(1000) < before || result.pos === 10);
  assert.ok(clock.debug().resetCount >= 2);
});

test("track change resets", () => {
  const clock = new PlaybackClock();
  sample(clock, {
    pos: 40,
    lastUpdatedMs: 1000,
    mediaUpdatedMs: 1000,
    nowMs: 1045,
    nowPerf: 0,
    trackKey: "One|A",
  });
  const result = sample(clock, {
    pos: 0,
    lastUpdatedMs: 2000,
    mediaUpdatedMs: 2000,
    nowMs: 2045,
    nowPerf: 5000,
    trackKey: "Two|A",
  });
  assert.equal(result.action, "reset");
  assert.ok(Math.abs(clock.position(5000) - 0) < 0.05);
});

test("0.8s error corrects gradually with no jump", () => {
  const clock = new PlaybackClock();
  sample(clock, {
    pos: 10,
    lastUpdatedMs: 1000,
    mediaUpdatedMs: 1000,
    nowMs: 1045,
    nowPerf: 0,
  });
  // Local clock advanced to ~10.0; server says ~10.8 via arrival.
  const mid = sample(clock, {
    pos: 10.8,
    lastUpdatedMs: 1000,
    mediaUpdatedMs: 1000,
    nowMs: 1045,
    nowPerf: 50,
  });
  assert.equal(mid.action, "gradual");
  assert.ok(mid.speed > 1);
  const p0 = clock.position(50);
  const p1 = clock.position(850);
  assert.ok(p1 > p0);
  // Should not hard-jump by the full 0.8s in one frame.
  assert.ok(p1 - p0 < 0.8);
});

test("ignore sub-threshold error", () => {
  const clock = new PlaybackClock();
  sample(clock, {
    pos: 5,
    lastUpdatedMs: 1000,
    mediaUpdatedMs: 1000,
    nowMs: 1045,
    nowPerf: 0,
  });
  const result = sample(clock, {
    pos: 5 + IGNORE_ERR_S / 2,
    lastUpdatedMs: 1000,
    mediaUpdatedMs: 1000,
    nowMs: 1045,
    nowPerf: 10,
  });
  assert.equal(result.action, "ignore");
});
