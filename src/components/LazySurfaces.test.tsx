// @vitest-environment jsdom
//
// Regression coverage for the React.lazy code-split of the chart-heavy
// secondary surfaces (ModelComparison, ModelDetail, BenchmarkCard). Each is
// only mounted while its owning Sheet/dialog is open, so the Suspense fallback
// appears on cold open and is replaced once the deferred chunk resolves.
//
// To observe the fallback *before* the import resolves in a deterministic
// (non wall-clock) way, the underlying chunk modules are replaced with a
// controllable lazy component: its render function throws a pending Promise
// until the test resolves it, so the Suspense boundary is genuinely in the
// collapsed/loading state at the moment we assert the `role="status"` fallback.
// Respecting the getValue load path and the real App chrome means the primary
// workflow (ScoreTable, trust UI, a11y) is exercised unmodified. The three
// code-split boundary paths (benchmark Sheet, model Sheet, Compare view) are
// each covered; every open proves the fallback is shown first, the unique
// secondary node appears after resolution, and each is closed through its real
// close control while the primary table survives.

import { act } from "react";
import { createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppWithDataSources } from "../App";
import type { DatasetInput } from "../data/dataset";
import type { OfficialLoadResult } from "../data/official";
import { fixtureBenchmark, fixtureModel, fixtureScore } from "../data/testFixtures";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Controllable lazy-load control per chunk boundary: each Suspense boundary
// suspends on a fresh pending Promise (`make`) until `trigger()` resolves it.
// `make` creates a new promise every call, so afterEach can reset each boundary
// with a *brand-new* unresolved promise — otherwise an already-resolved promise
// would never surface a fallback in a later test.
interface SuspendedState {
  pending: Promise<void>;
  trigger: () => void;
  done: boolean;
}
const ctl = vi.hoisted(() => {
  const make = (): SuspendedState => {
    let self!: () => void;
    const state: SuspendedState = { pending: Promise.resolve(), trigger: () => {}, done: false };
    // Build a fresh pending promise whose resolver `trigger` controls. `trigger`
    // must flip the *object's* `done` property (which the 'Marker' reads before
    // choosing to suspend), not a closure the returned object never observes.
    state.pending = new Promise<void>((resolve) => {
      self = resolve;
    });
    state.trigger = () => {
      state.done = true;
      self();
    };
    return state;
  };
  const shared: {
    benchmark: SuspendedState;
    model: SuspendedState;
    comparison: SuspendedState;
  } = { benchmark: make(), model: make(), comparison: make() };
  return {
    open: () => shared,
    reset: () => {
      shared.benchmark = make();
      shared.model = make();
      shared.comparison = make();
    },
  };
});

/** A function component that suspends until its control is triggered. */
function SuspendedMarker({
  state,
  text,
}: {
  state: { done: boolean; pending: Promise<void> };
  text: string;
}) {
  if (!state.done) throw state.pending;
  return createElement("div", { className: "lazy-marker" }, text);
}

// Mock exactly the three code-split chunk modules the app lazy-loads, so each
// Suspense boundary has a call-by-our-own trigger rather than a real network
// chunk. The rest of App (the primary table, trust chrome, sheets) stays real.
vi.mock("./BenchmarkCard", () => ({
  BenchmarkCard: () =>
    createElement(SuspendedMarker, { state: ctl.open().benchmark, text: "BENCHMARK-LAZY" }),
}));
vi.mock("./ModelDetail", () => ({
  ModelDetail: () =>
    createElement(SuspendedMarker, { state: ctl.open().model, text: "MODEL-LAZY" }),
}));
vi.mock("./ModelComparison", () => ({
  ModelComparison: () =>
    createElement(SuspendedMarker, { state: ctl.open().comparison, text: "COMPARE-LAZY" }),
}));
// The "Benchmark catalog" pie is a 4th lazy boundary (kept eager-adjacent but
// code-split to hold the budget). It is NOT one of the surfaces this suite is
// about, so resolve it immediately: keep the primary view synchronous and stop
// its "Loading chart…" fallback from shadowing the sheet/dialog fallbacks the
// tests opened below. This keeps primary-workflow-renders-eager assertion real.
vi.mock("./charts/CatalogSharePie", () => ({
  CatalogSharePie: () => createElement("div", { className: "catalog-pie-mock" }, "CATALOG-PIE"),
}));

function demoFixture(): DatasetInput {
  return { models: [fixtureModel], benchmarks: [fixtureBenchmark], scores: [fixtureScore] };
}

const unavailable: OfficialLoadResult = {
  availability: "unavailable",
  reason: "No governed release authorization is configured for this build.",
};

const mounted: Array<{ root: Root; container: HTMLElement }> = [];

async function renderApp() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  // Async act: the 4th lazy boundary (catalog pie), though mocked to a sync
  // component, still resolves through a dynamic `import()` on a microtask. An
  // async act flushes that microtask so the catalog chunk commits to its own
  // Suspense boundary *while still inside act* — otherwise its settle fires
  // after the synchronous act returns and React reports "suspended resource
  // finished loading outside act" on the never-opening primary test.
  await act(async () => {
    root.render(<AppWithDataSources demoData={demoFixture()} officialLoadResult={unavailable} />);
  });
  const handle = { root, container };
  mounted.push(handle);
  return handle;
}

afterEach(() => {
  // Reset all lazy controls so the next test starts in the un-resolved state.
  ctl.reset();
  while (mounted.length > 0) {
    const { root, container } = mounted.pop()!;
    act(() => root.unmount());
    container.remove();
  }
});

/** Resolve a lazy chunk inside an act so the Suspense boundary commits and the
 * unique secondary surface is actually mounted in the living document. Every
 * step that lets the suspended chunk settle (trigger flips the marker on, the
 * chunk promise resolves, and React re-renders past the fallback) stays inside
 * a single async `act`. Awaiting the thrown promise *within* that act scope —
 * not via a timer-driven poll that runs after the act callback returns — is what
 * stops the "resolves suspended data should be wrapped in act" warning and keeps
 * the assert on the resolved `.lazy-marker` deterministic. */
async function resolveLazy(state: SuspendedState) {
  await act(async () => {
    state.trigger();
    await state.pending; // the chunk promise settles; React flushes under act
  });
  // The surface has committed synchronously with the act flush above. Prove it.
  expect(document.body.querySelector(".lazy-marker")).toBeTruthy();
}

// The Sheet content mounts into a Base-UI portal attached to <body>, so the
// sheet/lazy assertions read from the living document, not the inert container.
/** The Suspense `role="status"` fallback whose text starts with "Loading". App
 * also has a status-live announcement region, so disambiguate by text. */
/** The Suspense fallback belonging to one of the secondary sheet/dialog
 * surfaces this suite mounts (benchmark, model, comparison). The catalog pie's
 * "Loading chart…" fallback resolves immediately on mount and is intentionally
 * NOT treated as a secondary-surface open. */
function surfaceFallback(): HTMLElement | null {
  const text = Array.from(document.body.querySelectorAll('[role="status"]'))
    .map((n) => n.textContent?.trim() ?? "")
    .find((t) => t.startsWith("Loading benchmark") || t.startsWith("Loading model") || t.startsWith("Loading comparison"));
  if (!text) return null;
  return (
    Array.from(document.body.querySelectorAll('[role="status"]')).find(
      (n) => n.textContent?.trim() === text
    ) as HTMLElement | null
  );
}

describe("lazy secondary surfaces open/close contract", () => {
  it("loads the primary Table workflow eagerly and mounts no secondary surface until opened", async () => {
    const { container } = await renderApp();
    expect(container.querySelector("table")).toBeTruthy();
    expect(container.textContent).toContain(fixtureModel.name);
    // No secondary surface node and no lazy Suspense fallback is mounted before
    // an open. (Header legitimately renders its own official-data-status
    // `role="status"` announcement, so scope the fallback check to the
    // "Loading…" Suspense fallbacks used by the lazy boundaries.)
    expect(document.body.querySelector(".lazy-marker")).toBeNull();
    expect(surfaceFallback()).toBeNull();
  });

it("opens the benchmark detail Sheet: fallback shows first, the unique surface appears after resolve, and the real close control unmounts it while the table survives", { timeout: 30_000 }, async () => {
    const { container } = await renderApp();
    const benchmarkButton = container.querySelector(
      'button[title="Open benchmark detail"]'
    ) as HTMLButtonElement;
    expect(benchmarkButton).toBeTruthy();

    act(() => benchmarkButton.click());

    // Still suspended: the Suspense fallback (role=status) is observable now,
    // before the benchmark chunk resolves. The real surface node is absent.
    const fallback = surfaceFallback();
    expect(fallback).toBeTruthy();
    expect(fallback?.textContent).toContain("Loading benchmark");
    expect(document.body.querySelector(".lazy-marker")).toBeNull();

    // Resolve the benchmark chunk: the unique surface node must now appear.
    await resolveLazy(ctl.open().benchmark);
    const surface = document.body.querySelector(".lazy-marker");
    expect(surface).toBeTruthy();
    expect(surface?.textContent).toContain("BENCHMARK-LAZY");

    // The primary table is still alive underneath.
    expect(container.querySelector("table")).toBeTruthy();

    // Close through the real Sheet close control (the sr-only "Close" button).
    const sheetClose = Array.from(document.body.querySelectorAll("button")).find((b) =>
      b.textContent?.trim() === "Close"
    );
    expect(sheetClose).toBeTruthy();
    act(() => (sheetClose as HTMLButtonElement).click());

    // The secondary surface unmounts entirely; the main table remains.
    expect(document.body.querySelector(".lazy-marker")).toBeNull();
    expect(container.querySelector("table")).toBeTruthy();
  });

  it("opens the model detail sheet: fallback first, unique surface on resolve, closes via its close control with the table intact", { timeout: 30_000 }, async () => {
    const { container } = await renderApp();
    const modelButton = container.querySelector(
      'button[title*="best in column"]'
    ) as HTMLButtonElement;
    expect(modelButton).toBeTruthy();

    act(() => modelButton.click());

    // Suspended fallback is observable before the model chunk resolves.
    const fallback = surfaceFallback();
    expect(fallback).toBeTruthy();
    expect(fallback?.textContent).toContain("Loading model");

    await resolveLazy(ctl.open().model);
    const surface = document.body.querySelector(".lazy-marker");
    expect(surface).toBeTruthy();
    expect(surface?.textContent).toContain("MODEL-LAZY");

    expect(container.querySelector("table")).toBeTruthy();

    const close = Array.from(document.body.querySelectorAll("button")).find((b) =>
      b.textContent?.trim() === "Close"
    );
    expect(close).toBeTruthy();
    act(() => (close as HTMLButtonElement).click());

    expect(document.body.querySelector(".lazy-marker")).toBeNull();
    expect(container.querySelector("table")).toBeTruthy();
  });

  it("switches to the Compare view: fallback shows, the surface appears on resolve, and leaving the view restores the table", { timeout: 30_000 }, async () => {
    const { container } = await renderApp();
    // Compare is disabled without a selection, so arm a model first.
    const select = container.querySelector(
      'input[aria-label*="for comparison"]'
    ) as HTMLInputElement;
    expect(select).toBeTruthy();
    // Toggling the controlled checkbox fires React's onChange (which calls
    // onToggleModelSelect) and the Header's Compare tab becomes enabled.
    // `.click()` is the reliable way to drive a controlled checkbox in jsdom:
    // setting `.checked` then dispatching a synthetic `change` is not noticed
    // by React 19's input value tracker.
    act(() => select.click());

    // Click the "Compare" header tab.
    const headerCompare = Array.from(container.querySelectorAll("button")).find((b) =>
      b.textContent?.includes("Compare")
    );
    expect(headerCompare).toBeTruthy();
    act(() => (headerCompare as HTMLButtonElement).click());

    // Compare view is suspended -> its fallback appears first.
    const fallback = surfaceFallback();
    expect(fallback).toBeTruthy();
    expect(fallback?.textContent).toContain("Loading comparison");

    await resolveLazy(ctl.open().comparison);
    const surface = document.body.querySelector(".lazy-marker");
    expect(surface).toBeTruthy();
    expect(surface?.textContent).toContain("COMPARE-LAZY");

    // Return to the leaderboard/tab view; the Compare surface unmounts and the
    // primary table is back.
    const tableTab = Array.from(container.querySelectorAll("button")).find((b) =>
      b.textContent?.includes("Leaderboard")
    );
    expect(tableTab).toBeTruthy();
    act(() => (tableTab as HTMLButtonElement).click());

    expect(document.body.querySelector(".lazy-marker")).toBeNull();
    expect(container.querySelector("table")).toBeTruthy();
  });
});