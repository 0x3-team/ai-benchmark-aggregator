// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { DatasetProvider, type DatasetInput } from "../data/dataset";
import { fixtureBenchmark, fixtureModel, fixtureScore } from "../data/testFixtures";
import { ModelComparison } from "./ModelComparison";
import { ScoreHeatmap } from "./ScoreHeatmap";
import { ScoreTable } from "./ScoreTable";
import { Badge } from "./ui/badge";
import {
  Toast,
  ToastClose,
  ToastProvider,
  ToastViewport,
} from "./ui/toast";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function render(ui: React.ReactNode): { container: HTMLDivElement; root: Root } {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  return { container, root };
}

function datasetWithModels(count: number): DatasetInput {
  const models = Array.from({ length: count }, (_, index) => ({
    ...fixtureModel,
    id: `w6b-model-${index + 1}`,
    name: `W6B Model ${index + 1}`,
  }));
  const benchmark = { ...fixtureBenchmark, id: "w6b-benchmark" };
  return {
    models,
    benchmarks: [benchmark],
    scores: models.map((model, index) => ({
      ...fixtureScore,
      modelId: model.id,
      benchmarkId: benchmark.id,
      value: 60 + index,
    })),
  };
}

describe("W6B interaction and accessibility semantics", () => {
  it("keeps badges presentational unless the interactive path is requested", () => {
    const view = render(
      <>
        <Badge>Category</Badge>
        <Badge interactive onClick={vi.fn()}>
          Filter
        </Badge>
      </>
    );
    try {
      expect(view.container.querySelector("span")?.textContent).toBe("Category");
      expect(view.container.querySelectorAll("button")).toHaveLength(1);
      expect(view.container.querySelector("span")?.tabIndex).toBe(-1);
    } finally {
      act(() => rootCleanup(view.root));
      view.container.remove();
    }
  });

  it("does not put ordinary heatmap scores into the tab sequence", () => {
    const data = datasetWithModels(1);
    const view = render(
      <DatasetProvider data={data}>
        <ScoreHeatmap
          models={data.models as never}
          benchmarks={data.benchmarks as never}
          onOpenModel={vi.fn()}
        />
      </DatasetProvider>
    );
    try {
      expect(view.container.querySelector('button[aria-label*="W6B Model 1 · Fixture Bench 1"]')).toBeNull();
      expect(view.container.querySelector('button[title="Open W6B Model 1"]')).toBeTruthy();
    } finally {
      act(() => rootCleanup(view.root));
      view.container.remove();
    }
  });

  it("exposes radar series visibility as a pressed state", () => {
    const data = datasetWithModels(1);
    const view = render(
      <DatasetProvider data={data}>
        <ModelComparison
          models={data.models as never}
          allModels={data.models as never}
          benchmarks={data.benchmarks as never}
          onOpenModel={vi.fn()}
        />
      </DatasetProvider>
    );
    try {
      const toggle = view.container.querySelector<HTMLButtonElement>(
        'button[aria-label="Hide W6B Model 1 on capability radar"]'
      );
      expect(toggle?.getAttribute("aria-pressed")).toBe("true");
      act(() => toggle?.click());
      expect(toggle?.getAttribute("aria-pressed")).toBe("false");
    } finally {
      act(() => rootCleanup(view.root));
      view.container.remove();
    }
  });

  it("disables unselected rows and explains the six-model comparison limit", () => {
    const data = datasetWithModels(7);
    const rankMap = Object.fromEntries(
      data.models.map((model, index) => [
        model.id,
        {
          model,
          rank: index + 1,
          avgRank: index + 1,
          firsts: index === 0 ? 1 : 0,
          coverage: 1,
          covered: 1,
          total: 1,
          unrankedReason: null,
        },
      ])
    );
    const view = render(
      <DatasetProvider data={data}>
        <ScoreTable
          models={data.models as never}
          cohortModels={data.models as never}
          benchmarks={data.benchmarks as never}
          sort={null}
          onSort={vi.fn()}
          onBenchmarkClick={vi.fn()}
          onOpenModel={vi.fn()}
          onClearSort={vi.fn()}
          onToggleModelSelect={vi.fn()}
          selectedModels={data.models.slice(0, 6).map((model) => model.id)}
          rankMap={rankMap}
          rankCohortTotal={1}
        />
      </DatasetProvider>
    );
    try {
      expect(view.container.textContent).toContain("Comparison limit reached");
      const unselected = view.container.querySelector<HTMLInputElement>(
        'input[aria-label="Select W6B Model 7 for comparison"]'
      );
      expect(unselected?.disabled).toBe(true);
      expect(unselected?.getAttribute("aria-disabled")).toBe("true");
      expect(unselected?.getAttribute("aria-describedby")).toBe("comparison-limit-help");
    } finally {
      act(() => rootCleanup(view.root));
      view.container.remove();
    }
  });

  it("gives the toast close control an accessible name", () => {
    const view = render(
      <ToastProvider>
        <ToastViewport>
          <Toast open>
            <ToastClose />
          </Toast>
        </ToastViewport>
      </ToastProvider>
    );
    try {
      expect(document.body.querySelector('button[aria-label="Dismiss notification"]')).toBeTruthy();
    } finally {
      act(() => rootCleanup(view.root));
      view.container.remove();
    }
  });
});

function rootCleanup(root: Root): void {
  root.unmount();
}
