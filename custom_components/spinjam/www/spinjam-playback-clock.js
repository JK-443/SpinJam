/**
 * SpinJam playback clock — delivery-delay aware, gradual corrections, no reverse.
 *
 * Pure module (no DOM). Used by spinjam-lyrics-card.js and node:test.
 *
 * Position on arrival:
 *   lat  = now - last_updated
 *   base = min(lat) over the last N samples  (cancels TV↔HA clock offset)
 *   pos  = media_position
 *        + max(0, last_updated - media_position_updated_at)
 *        + clamp(lat - base, 0, 2)
 *
 * Same track + play state:
 *   |err| < 0.15s  → ignore
 *   0.15–1.5s      → speed 0.9–1.1 until converged
 *   > 1.5s / track or play-state change → hard reset
 */

export const LAT_WINDOW = 30;
export const LAT_CLAMP_S = 2;
export const IGNORE_ERR_S = 0.15;
export const GRADUAL_ERR_S = 1.5;
export const SPEED_MIN = 0.9;
export const SPEED_MAX = 1.1;

/**
 * @param {number} value
 * @param {number} lo
 * @param {number} hi
 */
export function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, value));
}

/**
 * Where to read the lyric file.
 * Positive offsetMs delays the lyrics (look earlier in the LRC). Applied once;
 * the clock position already includes delivery delay and must not be shifted again.
 * @param {number} mediaPosition seconds from PlaybackClock.position
 * @param {number} offsetMs
 */
export function lyricLookPosition(mediaPosition, offsetMs) {
  const off = Number(offsetMs);
  const delay = Number.isFinite(off) ? off / 1000 : 0;
  const pos = Number(mediaPosition);
  if (!Number.isFinite(pos)) return 0;
  return pos - delay;
}

/**
 * Server position at HA write time, plus delivery delay above the observed baseline.
 * @param {{
 *   mediaPosition: number,
 *   mediaPositionUpdatedAtMs: number,
 *   lastUpdatedMs: number,
 *   nowMs: number,
 *   playing: boolean,
 *   latSamples: number[],
 * }} args
 */
export function arrivalPosition(args) {
  const {
    mediaPosition,
    mediaPositionUpdatedAtMs,
    lastUpdatedMs,
    nowMs,
    playing,
    latSamples,
  } = args;
  if (!Number.isFinite(mediaPosition)) return null;

  const lat = Number.isFinite(lastUpdatedMs)
    ? Math.max(0, (nowMs - lastUpdatedMs) / 1000)
    : 0;
  const samples = Array.isArray(latSamples) ? latSamples.slice() : [];
  samples.push(lat);
  while (samples.length > LAT_WINDOW) samples.shift();
  const base = samples.length ? Math.min(...samples) : lat;
  const delay = clamp(lat - base, 0, LAT_CLAMP_S);

  let pos = mediaPosition;
  if (
    playing &&
    Number.isFinite(mediaPositionUpdatedAtMs) &&
    Number.isFinite(lastUpdatedMs)
  ) {
    pos += Math.max(0, (lastUpdatedMs - mediaPositionUpdatedAtMs) / 1000);
  }
  pos += delay;
  return {
    pos,
    lat,
    base,
    delay,
    latSamples: samples,
  };
}

/**
 * Mutable playback clock used by the TV card.
 */
export class PlaybackClock {
  constructor() {
    this.resetStats();
  }

  resetStats() {
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
  }

  /** @returns {{ base: number, lat: number, speed: number, resetCount: number }} */
  debug() {
    return {
      base: this._lastBase,
      lat: this._lastLat,
      speed: this._speed,
      resetCount: this._resetCount,
    };
  }

  /**
   * @param {{
   *   mediaPosition: number,
   *   mediaPositionUpdatedAtMs: number,
   *   lastUpdatedMs: number,
   *   nowMs: number,
   *   nowPerf: number,
   *   playing: boolean,
   *   trackKey: string,
   * }} sample
   */
  observe(sample) {
    const arrival = arrivalPosition({
      mediaPosition: sample.mediaPosition,
      mediaPositionUpdatedAtMs: sample.mediaPositionUpdatedAtMs,
      lastUpdatedMs: sample.lastUpdatedMs,
      nowMs: sample.nowMs,
      playing: sample.playing,
      latSamples: this._latSamples,
    });
    if (!arrival) {
      this._hasAnchor = false;
      return { action: "clear" };
    }
    this._latSamples = arrival.latSamples;
    this._lastLat = arrival.lat;
    this._lastBase = arrival.base;

    const trackChanged = sample.trackKey !== this._trackKey;
    const playChanged = sample.playing !== this._playing;
    const hardReset = trackChanged || playChanged || !this._hasAnchor;

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

    const predicted = this.position(sample.nowPerf);
    const err = arrival.pos - predicted;
    const abs = Math.abs(err);

    if (abs < IGNORE_ERR_S) {
      return { action: "ignore", pos: predicted, err };
    }
    if (abs > GRADUAL_ERR_S) {
      this._anchorPos = arrival.pos;
      this._anchorPerf = sample.nowPerf;
      this._speed = 1;
      this._targetPos = null;
      this._targetPerf = null;
      this._resetCount += 1;
      this._lastEmitted = arrival.pos;
      return { action: "reset", pos: arrival.pos, err };
    }

    // Gradual: aim to converge by running slightly fast/slow.
    this._targetPos = arrival.pos;
    this._targetPerf = sample.nowPerf;
    // If behind (err>0) speed up; if ahead, slow down.
    this._speed = err > 0 ? SPEED_MAX : SPEED_MIN;
    this._anchorPos = predicted;
    this._anchorPerf = sample.nowPerf;
    return { action: "gradual", pos: predicted, err, speed: this._speed };
  }

  /**
   * Current media position (seconds), monotonic within a track except hard resets.
   * @param {number} nowPerf
   */
  position(nowPerf) {
    if (!this._hasAnchor) return 0;
    let pos =
      this._anchorPos +
      (this._playing
        ? ((nowPerf - this._anchorPerf) / 1000) * this._speed
        : 0);

    if (
      this._playing &&
      this._targetPos != null &&
      this._targetPerf != null &&
      this._speed !== 1
    ) {
      // Stop adjusting once we meet/cross the target.
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

    // Never emit a backwards position within the track (except after hard reset,
    // which replaces the anchor above).
    if (pos < this._lastEmitted) {
      pos = this._lastEmitted;
    } else {
      this._lastEmitted = pos;
    }
    return Math.max(0, pos);
  }
}
