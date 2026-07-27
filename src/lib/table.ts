// Shared constants for the sticky-column tables (ScoreTable, ScoreHeatmap).
// The background must be opaque enough to hide content scrolling under the
// sticky edge while still reading as part of the glass surface.
export const STICKY_BG = "rgba(13,18,28,0.94)";
export const GROUP_H = 30;

// Fixed height (px) of each rendered body row in ScoreTable. Virtualization
// relies on a constant row height so the spacer rows and the scroll container
// height can be computed without measuring the DOM.
export const ROW_H = 40;

// How many rows of buffer to render above and below the visible viewport.
export const ROW_BUFFER = 10;

// Max viewport height (px) for the virtualized body before it scrolls. Large
// enough to show roughly the same number of rows as before, but bounded so a
// 500+ row dataset never paints every cell.
export const BODY_MAX_H = 560;
