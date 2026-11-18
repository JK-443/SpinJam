/**
 * Pure layout decisions for spinjam-lyrics-card.
 * Lyrics on: the existing two-panel Cast layout (details | lyrics).
 * Lyrics off: one full-width stage. A lyrics-mode card collapses when a
 * sibling details card will draw that stage, so the row is not duplicated.
 * Switching modes is a client-side presentation change (no recast).
 */

export const CARD_MODE_LYRICS = "lyrics";
export const CARD_MODE_DETAILS = "details";
export const CARD_MODE_CAST = "cast";
export const CARD_MODE_STAGE = "stage";
export const CARD_MODE_HIDDEN = "hidden";

/** Opacity / slot transition. Long enough to read, short enough for a TV toggle. */
export const LAYOUT_TRANSITION_MS = 480;

/**
 * Square cover as a fraction of the viewport (and card) height.
 * Kept inside the 55–65% band so title, artist, album, and the progress
 * bar still fit underneath on a 16:9 television.
 */
export const STAGE_ART_HEIGHT_RATIO = 0.6;

export function resolveCardPresentation({
  configuredMode,
  lyricsEnabled,
  siblingShowsStage,
} = {}) {
  const lyricsOn = lyricsEnabled !== false;
  const details = configuredMode === "details";
  const cast = configuredMode === "cast";
  // One card owns both layouts and fills the panel. No sibling column to collapse.
  if (cast) {
    return {
      mode: lyricsOn ? CARD_MODE_CAST : CARD_MODE_STAGE,
      collapseSlot: false,
      expandSlot: false,
      fullBleed: true,
    };
  }
  if (lyricsOn) {
    return {
      mode: details ? CARD_MODE_DETAILS : CARD_MODE_LYRICS,
      collapseSlot: false,
      expandSlot: false,
      fullBleed: false,
    };
  }
  if (!details && siblingShowsStage) {
    return {
      mode: CARD_MODE_HIDDEN,
      collapseSlot: true,
      expandSlot: false,
      fullBleed: false,
    };
  }
  return {
    mode: CARD_MODE_STAGE,
    collapseSlot: false,
    expandSlot: true,
    fullBleed: true,
  };
}

/**
 * How a card slot should size when a custom layout still has two cards.
 * A grid keeps an empty track unless the template itself collapses.
 */
export function slotLayoutPatch(presentation, parentDisplay) {
  const empty = {
    hostDisplay: "",
    slotDisplay: "",
    slotFlex: "",
    slotWidth: "",
    slotMaxWidth: "",
    slotMargin: "",
    slotPadding: "",
    slotOverflow: "",
    slotGridColumn: "",
    parentGridTemplateColumns: "",
  };
  if (!presentation) return empty;
  if (presentation.collapseSlot) {
    return {
      hostDisplay: "none",
      slotDisplay: "none",
      slotFlex: "0 0 0px",
      slotWidth: "0px",
      slotMaxWidth: "0px",
      slotMargin: "0px",
      slotPadding: "0px",
      slotOverflow: "hidden",
      slotGridColumn: "",
      parentGridTemplateColumns: parentDisplay === "grid" || parentDisplay === "inline-grid" ? "1fr" : "",
    };
  }
  if (presentation.expandSlot) {
    return {
      ...empty,
      slotFlex: "1 1 100%",
      slotWidth: "100%",
      slotMaxWidth: "100%",
      slotGridColumn: "1 / -1",
    };
  }
  return empty;
}

/** True when the stage should show the neutral gradient and a placeholder cover. */
export function stageMissingArt(loUrl, hdUrl) {
  return !loUrl && !hdUrl;
}

/**
 * Pixel size of the centred cover. 60% of the card height, also capped at
 * 62% of the viewport and a share of the width so a 16:9 frame does not crop it.
 */
export function stageArtSizePx(cardHeight, cardWidth, viewportHeight) {
  const h = Number(cardHeight) || 0;
  const w = Number(cardWidth) || 0;
  const vh = Number(viewportHeight) || h;
  if (h <= 0) return 0;
  const byCard = h * STAGE_ART_HEIGHT_RATIO;
  const byViewport = vh * 0.62;
  const byWidth = w > 0 ? w * 0.46 : byCard;
  return Math.max(96, Math.round(Math.min(byCard, byViewport, byWidth)));
}

/** Signed seconds: "+2.0 s", "+2.25 s", "-0.25 s", "0.0 s". */
export function formatLyricDelaySeconds(offsetMs) {
  const offset = Number(offsetMs) || 0;
  if (offset === 0) return "0.0 s";
  const seconds = Math.abs(offset) / 1000;
  let text = seconds.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  if (!text.includes(".")) text = seconds.toFixed(1);
  const sign = offset > 0 ? "+" : "-";
  return `${sign}${text} s`;
}

/** "+2.0 s (later)" / "0.0 s (on time)". */
export function formatLyricDelay(offsetMs) {
  const offset = Number(offsetMs) || 0;
  const word = offset > 0 ? "later" : offset < 0 ? "earlier" : "on time";
  return `${formatLyricDelaySeconds(offset)} (${word})`;
}

/** "Lyrics +250 ms later, now +2.25 s" */
export function lyricDelayToast(previousMs, nextMs) {
  const delta = Number(nextMs) - Number(previousMs);
  const direction = delta > 0 ? "later" : "earlier";
  const signed = `${delta > 0 ? "+" : ""}${delta} ms`;
  return `Lyrics ${signed} ${direction}, now ${formatLyricDelaySeconds(nextMs)}`;
}
