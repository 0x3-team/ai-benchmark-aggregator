// @vitest-environment jsdom
//
// Isolated, mock-based access-count budget for ScoreTable. This drives the real
// ScoreTable component over the 500×42 scale fixture with `useDataset` mocked
// so BOTH numeric accessors (`getValue` and `getScoreEntry`) are counted. The
// two memoized full-cohort scans (statsByBench + bestByBench/topModelId) are the
// dominant mount cost, so the mount bound is a tight structural formula (each
// scan touches modelCount × benchCount cells, and there are two such scans) —
// NOT a generous 25× headroom. A cohort-stable visible-row change must not re-run
// those scans; the added accessor traffic is bounded to the visible header +
// visible-row window, not the full 21k row-cohort scan again.

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { DatasetAccess } from "../data/dataset";
import { createDatasetAccess } from "../data/dataset";
import { computeRanking, type RankRow } from "../lib/aggregate";
import {
  SCALE_BENCHMARK_COUNT,
  SCALE_MODEL_COUNT,
  buildScaleDataset,
} from "../lib/scaleFixtures";
import { ScoreTable } from "./ScoreTable";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// A module-scoped slot the mocked `useDataset` reads from. The dataset is built
// inside the test, then handed to ScoreTable's `useDataset` through the mock.
const slot: { access: DatasetAccess | null } = { access: null };

vi.mock("../data/dataset", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../data/dataset")>();
  return {
    ...actual,
    useDataset: () => {
      if (slot.access === null) {
        throw new Error("ScoreTable.access: dataset not installed for this test.");
      }
      return slot.access;
    },
  };
});

/** A precomputed rank map over the full cohort, so ScoreTable doesn't recompute. */
function buildRankMap(): Record<string, RankRow> {
  const access = createDatasetAccess(buildScaleDataset());
  const ranking = computeRanking(access.models, access.benchmarks, access.getValue);
  const map: Record<string, RankRow> = {};
  ranking.forEach((row) => {
    map[row.model.id] = row;
  });
  return map;
}

/** Harness mirrors App's ScoreTable wiring. `cohortModels` stays the stable
 * full cohort while `models` (the visible rows) may change, isolating whether
 * the memoized cohort scans re-run. */
function CountingHarness({
  models,
  cohortModels,
  benchmarks,
  rankMap,
}: {
  models: DatasetAccess["models"];
  cohortModels: DatasetAccess["models"];
  benchmarks: DatasetAccess["benchmarks"];
  rankMap: Record<string, RankRow>;
}) {
  return (
    <ScoreTable
      models={models}
      cohortModels={cohortModels}
      benchmarks={benchmarks}
      sort={null}
      onSort={() => {}}
      onBenchmarkClick={() => {}}
      onOpenModel={() => {}}
      onClearSort={() => {}}
      onToggleModelSelect={() => {}}
      selectedModels={[]}
      rankMap={rankMap}
      rankCohortTotal={benchmarks.length}
    />
  );
}

const mounted: Array<{ root: ReturnType<typeof createRoot>; container: HTMLElement }> = [];

afterEach(() => {
  slot.access = null;
  while (mounted.length > 0) {
    const { root, container } = mounted.pop()!;
    act(() => root.unmount());
    container.remove();
  }
});

it(
  "mounts the 500×42 table with a tight two-scan accessor bound; a stable-cohort search grows only the visible window",
  { timeout: 20_000 },
  () => {
    const real = createDatasetAccess(buildScaleDataset());
    const rankMap = buildRankMap();

    let getValueCalls = 0;
    let getScoreEntryCalls = 0;
    const counting: DatasetAccess = {
      models: real.models,
      benchmarks: real.benchmarks,
      officialRelease: real.officialRelease,
      getValue: (m, b) => {
        getValueCalls += 1;
        return real.getValue(m, b);
      },
      getScoreEntry: (m, b) => {
        getScoreEntryCalls += 1;
        return real.getScoreEntry(m, b);
      },
    };
    slot.access = counting;

    const render = (models: DatasetAccess["models"]) =>
      root.render(
        <CountingHarness
          models={models}
          cohortModels={counting.models}
          benchmarks={counting.benchmarks}
          rankMap={rankMap}
        />
      );

    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    act(() => render(real.models));
    mounted.push({ root, container });

    const mountGetValue = getValueCalls;
    const mountGetScoreEntry = getScoreEntryCalls;
    const cohortScan = SCALE_MODEL_COUNT * SCALE_BENCHMARK_COUNT; // 21k

    // The two memoized full-cohort scans (statsByBench + bestByBench) must run
    // once on mount: value reads ≈ 2 × cohort. Tight structural upper bound (a
    // few passes), nowhere near a 25× multiplier.
    expect(SCALE_MODEL_COUNT).toBe(500);
    expect(SCALE_BENCHMARK_COUNT).toBe(42);
    expect(mountGetValue).toBeGreaterThanOrEqual(cohortScan * 2);
    expect(mountGetValue).toBeLessThan(cohortScan * 4);

    // Score entries are read per rendered footer/claim cell — far below a full
    // cohort scan, but present.
    expect(mountGetScoreEntry).toBeGreaterThan(0);
    expect(mountGetScoreEntry).toBeLessThan(cohortScan);

    // A cohort-stable visible-row change (smaller `models`, identical
    // `cohortModels` reference) must NOT re-run the 21k cohort scans: growth is
    // bounded to the visible window's value+entry reads.
    const visibleModels = real.models.slice(0, 10);
    act(() => render(visibleModels));

    const addedGetValue = getValueCalls - mountGetValue;
    const addedGetScoreEntry = getScoreEntryCalls - mountGetScoreEntry;

    expect(addedGetValue).toBeLessThan(cohortScan);
    expect(addedGetScoreEntry).toBeLessThan(cohortScan);

    act(() => root.unmount());
    container.remove();
  }
);