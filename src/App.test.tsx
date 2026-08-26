// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { AppWithDataSources } from "./App";
import { DatasetProvider, type DatasetInput } from "./data/dataset";
import type { OfficialLoadResult } from "./data/official";
import { fixtureModel, fixtureBenchmark, fixtureScore } from "./data/testFixtures";
import { BenchmarkCard } from "./components/BenchmarkCard";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function datasetFixture(): DatasetInput {
  return {
    models: [fixtureModel],
    benchmarks: [fixtureBenchmark],
    scores: [fixtureScore],
  };
}

function publishedFixture(): OfficialLoadResult {
  const fixture = datasetFixture();
  const model = {
    ...fixture.models[0],
    id: "official-ui03-model",
    name: "Official UI-03 Model",
  };
  const benchmark = {
    ...fixture.benchmarks[0],
    id: "official-ui03-benchmark",
    name: "Official UI-03 Bench",
    fullName: "Official UI-03 Benchmark",
  };
  return {
    availability: "published",
    artifact: {
      artifactId: "official-ui03-artifact",
      policyVersion: "official-release-artifact-v2",
      releaseApproval: {
        decisionId: "official-ui03-approval",
        policyVersion: "official-release-artifact-v2",
        approvedAt: "2026-07-13T11:00:00.000Z",
      },
      manifest: {
        algorithm: "sha256-canonical-json-v1",
        contentSha256: "b".repeat(64),
        modelCount: 1,
        benchmarkCount: 1,
        sourceSnapshotCount: 1,
        scoreCount: 1,
      },
      sourceManifest: [],
    },
    data: {
      models: [model],
      benchmarks: [benchmark],
      scores: [
        {
          ...fixture.scores[0],
          modelId: model.id,
          benchmarkId: benchmark.id,
          value: 77,
          date: "2026-07-13T10:00:00.000Z",
          scoreRaw: "77",
          captureStatus: "published",
          officialSourceId: "official-source-ui03",
          sourceSnapshotId: "official-snapshot-ui03",
          claimId: "official-claim-ui03",
        },
      ],
    },
  };
}

function wideDatasetFixture(): DatasetInput {
  const benchmarks = Array.from({ length: 13 }, (_, index) => ({
    ...fixtureBenchmark,
    id: `fixture-wide-bench-${index + 1}`,
    name: `Wide Bench ${index + 1}`,
    fullName: `Wide Benchmark ${index + 1}`,
  }));
  return {
    models: [fixtureModel],
    benchmarks,
    scores: benchmarks.map((benchmark) => ({
      ...fixtureScore,
      benchmarkId: benchmark.id,
    })),
  };
}

function widePublishedFixture(): OfficialLoadResult {
  const result = publishedFixture();
  if (result.availability !== "published") throw new Error("Expected a published fixture.");
  const data = wideDatasetFixture();
  return {
    ...result,
    artifact: {
      ...result.artifact,
      artifactId: "official-wide-artifact",
      manifest: {
        ...result.artifact.manifest,
        benchmarkCount: data.benchmarks.length,
        scoreCount: data.scores.length,
        contentSha256: "c".repeat(64),
      },
    },
    data,
  };
}

function setSearch(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  if (!setter) throw new Error("Expected an input value setter.");
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function buttonStartingWith(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find((candidate) =>
    candidate.textContent?.trim().startsWith(text)
  );
  if (!button) throw new Error("Expected matching button.");
  return button;
}

function modelSelectionCheckbox(container: HTMLElement): HTMLInputElement {
  const checkbox = Array.from(container.querySelectorAll('input[type="checkbox"]')).find(
    (candidate) => candidate.closest("td") !== null
  );
  if (!(checkbox instanceof HTMLInputElement)) throw new Error("Expected a model selection checkbox.");
  return checkbox;
}

describe("App Official data boundary", () => {
  it("contains an invalid published dataset without silently rendering fallback data", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const fixture = datasetFixture();
    const invalid: DatasetInput = {
      ...fixture,
      scores: [...fixture.scores, { ...fixture.scores[0] }],
    };
    const published = publishedFixture();
    if (published.availability !== "published") throw new Error("Expected a published fixture.");
    const invalidPublished: OfficialLoadResult = { ...published, data: invalid };
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);

    try {
      act(() => {
        root.render(
          <AppWithDataSources officialLoadResult={invalidPublished} />
        );
      });

      const heading = container.querySelector("#dataset-error-title");
      expect(heading?.textContent).toBe("Data display unavailable");
      expect(container.textContent).toContain("No fallback dataset was selected.");
      expect(container.textContent).not.toContain(fixture.models[0].name);
      expect(container.querySelector("button")?.textContent).toBe("Try again");
      expect(document.activeElement).toBe(heading);
    } finally {
      act(() => root.unmount());
      consoleError.mockRestore();
      container.remove();
    }
  });

  it("renders the tracked unavailable result as an honest empty awaiting state", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const unavailable: OfficialLoadResult = {
      availability: "unavailable",
      reason: "No governed release authorization is configured for this build.",
      artifactId: "official-unavailable-test",
    };

    try {
      act(() => {
        root.render(
          <AppWithDataSources officialLoadResult={unavailable} />
        );
      });
      const status = container.querySelector("#official-data-status");
      expect(status?.getAttribute("role")).toBe("status");
      expect(status?.textContent).toContain("Awaiting Official publication");
      expect(status?.textContent).toContain("No benchmark data is currently published");
      expect(container.textContent).toContain("0 models · 0 benchmarks · Awaiting publication");
      expect(container.textContent).toContain("No benchmark claims are published in this build");
      expect(container.textContent).not.toContain(fixtureModel.name);
      expect(container.querySelector('[aria-label="Data source"]')).toBeNull();
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("renders a verified Official result directly with governed release metadata", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    try {
      act(() => {
        root.render(<AppWithDataSources officialLoadResult={publishedFixture()} />);
      });
      expect(container.textContent).toContain("Official UI-03 Model");
      expect(container.textContent).toContain("official-ui03-artifact");
      expect(container.textContent).toContain("1 models · 1 benchmarks · Official claims");
      expect(container.textContent).not.toContain("0 models · 0 benchmarks · Awaiting publication");
      expect(container.querySelector('[aria-label="Data source"]')).toBeNull();
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("resets all dependent state when the governed Official source changes", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <AppWithDataSources officialLoadResult={widePublishedFixture()} />
        );
      });

      const showAll = buttonStartingWith(container, "Show all 13");
      act(() => showAll.click());
      expect(container.textContent).toContain("Show fewer benchmarks");

      const search = container.querySelector('input[type="search"]') as HTMLInputElement;
      setSearch(search, fixtureModel.name.toLowerCase());
      const checkbox = modelSelectionCheckbox(container);
      act(() => checkbox.click());
      const sortButton = container.querySelector('[aria-label^="Sort by"]') as HTMLButtonElement;
      act(() => sortButton.click());

      act(() => {
        root.render(<AppWithDataSources officialLoadResult={publishedFixture()} />);
      });

      const returnedSearch = container.querySelector('input[type="search"]') as HTMLInputElement;
      const returnedCheckbox = modelSelectionCheckbox(container);
      expect(returnedSearch.value).toBe("");
      expect(returnedCheckbox.checked).toBe(false);
      expect(container.textContent).not.toContain("Show fewer benchmarks");
      expect(container.textContent).not.toContain("Sorted by");
      expect(container.textContent).toContain("Official UI-03 Model");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });
});

describe("full-cohort detail claims", () => {
  it("keeps benchmark best/top claims global when visible rows are filtered", () => {
    const leader = { ...fixtureModel, id: "cohort-leader", name: "Cohort Leader" };
    const visible = { ...fixtureModel, id: "cohort-visible", name: "Visible Model" };
    const benchmark = { ...fixtureBenchmark, id: "cohort-benchmark" };
    const data: DatasetInput = {
      models: [leader, visible],
      benchmarks: [benchmark],
      scores: [
        { ...fixtureScore, modelId: leader.id, benchmarkId: benchmark.id, value: 99 },
        { ...fixtureScore, modelId: visible.id, benchmarkId: benchmark.id, value: 40 },
      ],
    };
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <DatasetProvider data={data}>
            <BenchmarkCard
              benchmark={benchmark}
              models={[visible]}
              cohortModels={[leader, visible]}
            />
          </DatasetProvider>
        );
      });
      expect(container.textContent).toContain("Best");
      expect(container.textContent).toContain("99");
      expect(container.textContent).toContain("Cohort Leader");
      expect(container.textContent).toContain("2/2");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });
});
