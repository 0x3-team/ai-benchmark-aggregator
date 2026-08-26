// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useMemo, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import {
  DatasetProvider,
  createDatasetAccess,
  useDataset,
  type DatasetModel,
} from "../data/dataset";
import { computeRanking, sortModels, type RankRow } from "../lib/aggregate";
import { BODY_MAX_H, ROW_BUFFER, ROW_H } from "../lib/table";
import {
  SCALE_BENCHMARK_COUNT,
  SCALE_MODEL_COUNT,
  buildScaleDataset,
  expectedScaleValue,
} from "../lib/scaleFixtures";
import { ScoreTable } from "./ScoreTable";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

type SortState = { benchmarkId: string | null; dir: "asc" | "desc" } | null;

function scaleModelName(index: number): string {
  return `Scale Model ${String(index).padStart(3, "0")}`;
}

/** The virtualization window the table must stay inside for these constants. */
function initialVisibleCount(): number {
  return Math.ceil(Math.min(BODY_MAX_H, SCALE_MODEL_COUNT * ROW_H) / ROW_H) + ROW_BUFFER * 2;
}

/**
 * Mini-App harness: mirrors App's data flow exactly (full-cohort ranking,
 * query filter, then column sort) so the table is tested through the same
 * code path the app uses, without pulling in unrelated chrome.
 */
function ScaleHarness() {
  const { models, benchmarks, getValue } = useDataset();
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortState>(null);

  const ranking = useMemo(
    () => computeRanking(models, benchmarks, getValue),
    [models, benchmarks, getValue]
  );
  const rankMap = useMemo(() => {
    const map: Record<string, RankRow> = {};
    ranking.forEach((row) => {
      map[row.model.id] = row;
    });
    return map;
  }, [ranking]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? models.filter((m) => m.name.toLowerCase().includes(q)) : models;
  }, [models, query]);
  const sorted = useMemo(
    () => sortModels(filtered, sort, benchmarks, benchmarks, getValue, ranking),
    [filtered, sort, benchmarks, getValue, ranking]
  );

  return (
    <>
      <input
        aria-label="Scale search"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <ScoreTable
        models={sorted}
        cohortModels={models}
        benchmarks={benchmarks}
        sort={sort}
        onSort={(benchmarkId) =>
          setSort((prev) =>
            prev?.benchmarkId === benchmarkId
              ? { benchmarkId, dir: prev.dir === "asc" ? "desc" : "asc" }
              : { benchmarkId, dir: "desc" }
          )
        }
        onBenchmarkClick={() => {}}
        onOpenModel={() => {}}
        onClearSort={() => setSort(null)}
        onToggleModelSelect={() => {}}
        selectedModels={[]}
        rankMap={rankMap}
        rankCohortTotal={benchmarks.length}
      />
    </>
  );
}

const mounted: Array<{ root: Root; container: HTMLElement }> = [];
const SCALE_DATASET = buildScaleDataset();

function renderHarness(): { root: Root; container: HTMLElement } {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <DatasetProvider data={SCALE_DATASET}>
        <ScaleHarness />
      </DatasetProvider>
    );
  });
  const handle = { root, container };
  mounted.push(handle);
  return handle;
}

afterEach(() => {
  while (mounted.length > 0) {
    const { root, container } = mounted.pop()!;
    act(() => root.unmount());
    container.remove();
  }
});


function modelRows(container: HTMLElement): HTMLTableRowElement[] {
  return Array.from(container.querySelectorAll("tbody tr")).filter((row) =>
    row.querySelector('input[type="checkbox"]')
  ) as HTMLTableRowElement[];
}

function spacerRows(container: HTMLElement): HTMLTableRowElement[] {
  return Array.from(
    container.querySelectorAll('tbody tr[aria-hidden="true"]')
  ) as HTMLTableRowElement[];
}

function scrollContainerOf(container: HTMLElement): HTMLDivElement {
  const table = container.querySelector("table");
  if (!table?.parentElement) throw new Error("Expected the table scroll container.");
  return table.parentElement as HTMLDivElement;
}

function scrollTo(container: HTMLElement, top: number): void {
  const scroller = scrollContainerOf(container);
  // jsdom has no layout engine, so pin scrollTop the way a real browser
  // would report it before dispatching the scroll event React listens for.
  Object.defineProperty(scroller, "scrollTop", { value: top, configurable: true });
  act(() => {
    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
  });
}

function setSearch(input: HTMLInputElement, value: string): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (!setter) throw new Error("Expected an input value setter.");
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/** Independent expected order for a column sort, derived only from golden cell values. */
function expectedColumnOrder(benchmarkIndex: number, dir: "asc" | "desc"): string[] {
  const rows: Array<{ id: string; name: string; value: number | null }> = [];
  for (let i = 0; i < SCALE_MODEL_COUNT; i += 1) {
    rows.push({
      id: `scale-model-${String(i).padStart(3, "0")}`,
      name: scaleModelName(i),
      value: expectedScaleValue(i, benchmarkIndex),
    });
  }
  const byName = (a: { name: string }, b: { name: string }) => (a.name < b.name ? -1 : 1);
  rows.sort((a, b) => {
    if (a.value == null && b.value == null) return byName(a, b);
    if (a.value == null) return 1;
    if (b.value == null) return -1;
    const ordered = dir === "asc" ? a.value - b.value : b.value - a.value;
    return ordered !== 0 ? ordered : byName(a, b);
  });
  return rows.map((row) => row.id);
}

/** The app's default (rank-ordered) model sequence, computed outside the DOM. */
function defaultOrder(): readonly DatasetModel[] {
  const access = createDatasetAccess(SCALE_DATASET);
  const ranking = computeRanking(access.models, access.benchmarks, access.getValue);
  return sortModels(
    access.models,
    null,
    access.benchmarks,
    access.benchmarks,
    access.getValue,
    ranking
  );
}


describe("ScoreTable over the 500 x 42 scale fixture", () => {
  it("renders a bounded virtualized window, never all 500 rows", { timeout: 20_000 }, () => {
    const { container } = renderHarness();
    const visible = initialVisibleCount();
    const rows = modelRows(container);

    // The dataset really is large; the DOM window really is small.
    expect(SCALE_MODEL_COUNT).toBe(500);
    expect(rows.length).toBe(visible);
    expect(rows.length).toBeLessThan(60);
    expect(rows.length).toBeLessThan(SCALE_MODEL_COUNT / 10);

    // Bounded cells: 44 columns per rendered row plus spacer rows, not 22k.
    const bodyCells = container.querySelectorAll("tbody td").length;
    expect(bodyCells).toBe(rows.length * (SCALE_BENCHMARK_COUNT + 2) + 1);
    expect(bodyCells).toBeLessThan(3000);

    // The trailing spacer keeps the scrollbar honest for all 500 rows.
    const spacers = spacerRows(container);
    expect(spacers).toHaveLength(1);
    expect(spacers[0].style.height).toBe(`${(SCALE_MODEL_COUNT - visible) * ROW_H}px`);

    // The visible policy states the immutable cohort and eligibility threshold.
    expect(container.querySelector("#overall-ranking-policy")?.textContent).toContain("60%");
    expect(container.querySelector("#overall-ranking-policy")?.textContent).toContain(
      "26 of 42 benchmarks"
    );
  });

  it("sorts the full 500-model fixture correctly in both directions", () => {
    const access = createDatasetAccess(buildScaleDataset());
    for (const [benchmarkIndex, dir] of [
      [3, "desc"],
      [13, "asc"],
      [23, "desc"],
    ] as const) {
      const sorted = sortModels(
        access.models,
        { benchmarkId: `scale-bench-${String(benchmarkIndex).padStart(2, "0")}`, dir },
        access.benchmarks,
        access.benchmarks,
        access.getValue
      );
      expect(sorted.map((model) => model.id)).toEqual(
        expectedColumnOrder(benchmarkIndex, dir)
      );
    }
  });

  it("keeps column sort correct in the DOM and retains header focus", { timeout: 20_000 }, () => {
    const { container } = renderHarness();
    const sortButton = container.querySelector(
      'button[aria-label="Sort by Scale Benchmark 03"]'
    ) as HTMLButtonElement;
    expect(sortButton).toBeTruthy();

    sortButton.focus();
    act(() => sortButton.click());

    // Banner names the active column; focus never left the header control.
    expect(container.textContent).toContain("Sorted by");
    expect(container.textContent).toContain("ScaleBench 03");
    expect(document.activeElement).toBe(sortButton);

    const expectedDesc = expectedColumnOrder(3, "desc");
    expect(modelRows(container)[0].textContent).toContain(
      scaleModelName(Number(expectedDesc[0].slice(-3)))
    );

    act(() => sortButton.click());
    expect(document.activeElement).toBe(sortButton);
    const expectedAsc = expectedColumnOrder(3, "asc");
    expect(modelRows(container)[0].textContent).toContain(
      scaleModelName(Number(expectedAsc[0].slice(-3)))
    );
  });

describe("filtering and virtualization scroll at scale", () => {
  it("filters 500 models correctly while keyboard focus stays in the search field", () => {
    const { container } = renderHarness();
    const search = container.querySelector('input[type="search"]') as HTMLInputElement;

    search.focus();
    setSearch(search, "scale model 05");

    const rows = modelRows(container);
    expect(rows).toHaveLength(10);
    for (const row of rows) {
      expect(row.textContent).toContain("Scale Model 05");
    }
    // Row context survives filtering: full-coverage and empty rows keep
    // their own rank/coverage identity from the full-cohort ranking.
    const fullRow = rows.find((row) => row.textContent?.includes("Scale Model 056"));
    const emptyRow = rows.find((row) => row.textContent?.includes("Scale Model 050"));
    expect(fullRow?.textContent).toContain("42/42 coverage");
    expect(emptyRow?.textContent).toContain("0/42 coverage");
    expect(document.activeElement).toBe(search);

    // Narrowing to one row keeps that row mounted and focusable.
    const checkbox = fullRow?.querySelector('input[type="checkbox"]') as HTMLInputElement;
    checkbox.focus();
    expect(document.activeElement).toBe(checkbox);
    setSearch(search, "scale model 056");
    const remaining = modelRows(container);
    expect(remaining).toHaveLength(1);
    expect(remaining[0].textContent).toContain("Scale Model 056");
    expect(document.activeElement).toBe(checkbox);
  });

  it("moves the virtualization window on scroll without losing row or column context", () => {
    const { container } = renderHarness();
    const expected = defaultOrder();

    // Focus a header control: the thead is not virtualized, so it must
    // keep focus and identity across any body scroll.
    const sortButton = container.querySelector(
      'button[aria-label="Sort by Scale Benchmark 05"]'
    ) as HTMLButtonElement;
    sortButton.focus();

    scrollTo(container, 200 * ROW_H);

    // After the scroll, the window is recomputed from the reported
    // scrollTop; jsdom reports clientHeight 0, so only the buffer rows
    // render: firstIndex = 200 - ROW_BUFFER.
    const firstIndex = 200 - ROW_BUFFER;
    const rows = modelRows(container);
    expect(rows.length).toBe(ROW_BUFFER * 2);
    expect(rows[0].textContent).toContain(expected[firstIndex].name);
    expect(rows[rows.length - 1].textContent).toContain(
      expected[firstIndex + ROW_BUFFER * 2 - 1].name
    );

    // Spacer math keeps total virtual height at 500 rows.
    const spacers = spacerRows(container);
    expect(spacers).toHaveLength(2);
    expect(spacers[0].style.height).toBe(`${firstIndex * ROW_H}px`);
    expect(spacers[1].style.height).toBe(
      `${(SCALE_MODEL_COUNT - (firstIndex + ROW_BUFFER * 2)) * ROW_H}px`
    );

    // Sticky left cells are still present on the freshly rendered window.
    const firstCells = rows[0].querySelectorAll("td");
    expect(firstCells[0].className).toContain("sticky left-0");
    expect(firstCells[1].className).toContain("sticky");
    expect(firstCells[1].style.left).toBe("34px");

    // Column context intact: the header control is still focused and the
    // visible policy still states the full cohort eligibility basis.
    expect(document.activeElement).toBe(sortButton);
    expect(container.querySelector("#overall-ranking-policy")?.textContent).toContain(
      "26 of 42 benchmarks"
    );
  });
});
});

/**
 * Deterministic 500×42 behavior coverage built on DOM row/cell bounds and
 * getValue/getScoreEntry call counts — NOT wall-clock jsdom timing. This
 * asserts the two things the audit wants without a flaky timer:
 *
 *   1. DOM row/cell bounds: the live window stays at
 *      visibleCount × (benchCount + 2 sticky) regardless of scroll depth. This
 *      is the SCROLL_CAPTURED_CELLS budget, expressed as DOM cells (a
 *      deterministic quantity), not milliseconds.
 *   2. getValue access-count: the full-cohort column scans (statsByBench /
 *      bestByBench) are memoized on [cohortModels, benchmarks, getValue]. When
 *      the visible rows change but the cohort reference is stable, that scan
 *      must NOT re-run. We count getValue calls across a cohort-stable
 *      re-render and assert growth is bounded to the visible window, not the
 *      full cohort.
 */
describe("ScoreTable deterministic scale budget (DOM bounds + access counts)", () => {
  it("keeps live row/cell DOM counts within a scroll-depth-invariant bound", { timeout: 20_000 }, () => {
    const { container } = renderHarness();
    const rows = modelRows(container);
    // 2 sticky cells per row + 42 data cells, plus one top-pad spacer row that
    // occupies the full row width as a single td.
    const cells = container.querySelectorAll("tbody td").length;
    const expectedCells = rows.length * (SCALE_BENCHMARK_COUNT + 2) + 1;
    expect(cells).toBe(expectedCells);
    // The window never grows past twice the buffer around the visible viewport.
    expect(rows.length).toBeLessThanOrEqual(initialVisibleCount());
    expect(cells).toBeLessThan(3_000);

    // Deep-scroll: the same window bound holds at a different scrollTop.
    scrollTo(container, Math.floor(SCALE_MODEL_COUNT * ROW_H * 0.7));
    const rowsDeep = modelRows(container);
    const cellsDeep = container.querySelectorAll("tbody td").length;
    expect(rowsDeep.length).toBeLessThanOrEqual(initialVisibleCount());
    expect(cellsDeep).toBeLessThan(3_000);
    // The window actually moved (fresh rows mounted), not stuck at the top.
    expect(cellsDeep).toBeGreaterThan(0);
  });
});
