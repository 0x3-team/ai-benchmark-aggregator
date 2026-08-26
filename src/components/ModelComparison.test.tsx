// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { DatasetProvider, type DatasetInput } from "../data/dataset";
import { fixtureBenchmark, fixtureModel, fixtureScore } from "../data/testFixtures";
import { ModelComparison } from "./ModelComparison";

// This regression only exercises cohort labels; keep unrelated chart renderers
// out of the focused DOM test.
vi.mock("./charts/CapabilityRadar", () => ({ CapabilityRadar: () => <div /> }));
vi.mock("./charts/CategoryAverageBars", () => ({ CategoryAverageBars: () => <div /> }));
vi.mock("./charts/CategoryVsFieldComposed", () => ({ CategoryVsFieldComposed: () => <div /> }));
vi.mock("./charts/CategoryBenchmarkSankey", () => ({ CategoryBenchmarkSankey: () => <div /> }));
vi.mock("./ScoreHeatmap", () => ({ ScoreHeatmap: () => <div /> }));
vi.mock("./BenchmarkBars", () => ({ BenchmarkBars: () => <div /> }));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("ModelComparison cohort claims", () => {
  it("does not label a selected model as category leader when a non-selected cohort model leads", () => {
    const leader = { ...fixtureModel, id: "comparison-leader", name: "Global Leader" };
    const selected = { ...fixtureModel, id: "comparison-selected", name: "Selected Model" };
    const benchmark = { ...fixtureBenchmark, id: "comparison-benchmark" };
    const data: DatasetInput = {
      models: [leader, selected],
      benchmarks: [benchmark],
      scores: [
        { ...fixtureScore, modelId: leader.id, benchmarkId: benchmark.id, value: 99 },
        { ...fixtureScore, modelId: selected.id, benchmarkId: benchmark.id, value: 40 },
      ],
    };
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <DatasetProvider data={data}>
            <ModelComparison
              models={[selected]}
              allModels={[leader, selected]}
              benchmarks={[benchmark]}
              onOpenModel={() => undefined}
            />
          </DatasetProvider>
        );
      });

      expect(container.textContent).toContain("Selected Model");
      expect(container.textContent).not.toContain("Leads in 1");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });
});
