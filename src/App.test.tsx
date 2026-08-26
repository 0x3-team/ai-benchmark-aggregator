// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppWithDataSources } from "./App";
import { DatasetProvider, type DatasetInput } from "./data/dataset";
import type { OfficialLoadResult } from "./data/official";
import { fixtureModel, fixtureBenchmark, fixtureScore } from "./data/testFixtures";
import { BenchmarkCard } from "./components/BenchmarkCard";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

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

function sparsePublishedFixture(
  artifactId = "official-sparse-artifact",
  contentSha256 = "d".repeat(64)
): OfficialLoadResult {
  const result = publishedFixture();
  if (result.availability !== "published") throw new Error("Expected a published fixture.");
  const models = [
    { ...fixtureModel, id: "sparse-complete", name: "Complete Model" },
    { ...fixtureModel, id: "sparse-eligible", name: "Eligible Sparse Model" },
    { ...fixtureModel, id: "sparse-ineligible", name: "Ineligible Sparse Model" },
    { ...fixtureModel, id: "sparse-zero", name: "No Published Scores Model" },
  ];
  const benchmarks = Array.from({ length: 5 }, (_, index) => ({
    ...fixtureBenchmark,
    id: `sparse-benchmark-${index + 1}`,
    name: `Sparse Bench ${index + 1}`,
    fullName: `Sparse Benchmark ${index + 1}`,
  }));
  const score = (modelId: string, benchmarkIndex: number, value: number) => ({
    ...fixtureScore,
    modelId,
    benchmarkId: benchmarks[benchmarkIndex].id,
    value,
  });

  return {
    ...result,
    artifact: {
      ...result.artifact,
      artifactId,
      manifest: {
        ...result.artifact.manifest,
        contentSha256,
        modelCount: models.length,
        benchmarkCount: benchmarks.length,
        scoreCount: 10,
      },
    },
    data: {
      models,
      benchmarks,
      scores: [
        score("sparse-complete", 0, 50),
        score("sparse-complete", 1, 80),
        score("sparse-complete", 2, 80),
        score("sparse-complete", 3, 80),
        score("sparse-complete", 4, 80),
        score("sparse-eligible", 0, 99),
        score("sparse-eligible", 1, 99),
        score("sparse-eligible", 2, 99),
        score("sparse-ineligible", 0, 100),
        score("sparse-ineligible", 1, 100),
      ],
    },
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

  it("restores and canonicalizes a valid v1 permalink", async () => {
    window.history.replaceState(
      null,
      "",
      "/?unknown=drop&compare=sparse-eligible&vendor=TestVendor&q=eligible&v=1" +
        "&category=knowledge&sort=sparse-benchmark-1&dir=desc" +
        "&model=sparse-eligible&zero=1"
    );
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AppWithDataSources officialLoadResult={sparsePublishedFixture()} />);
      });
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 0));
      });

      const search = container.querySelector('input[type="search"]') as HTMLInputElement;
      const vendor = Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent?.trim() === "TestVendor"
      );
      const category = Array.from(container.querySelectorAll("button")).find(
        (button) => button.textContent?.trim() === "Knowledge"
      );
      expect(search.value).toBe("eligible");
      expect(vendor?.getAttribute("aria-pressed")).toBe("true");
      expect(category?.getAttribute("aria-pressed")).toBe("true");
      expect(document.querySelector('[role="dialog"]')?.textContent).toContain(
        "Eligible Sparse Model"
      );
      expect(container.textContent).toContain("Sorted by");
      expect(window.location.search).toBe(
        "?v=1&q=eligible&vendor=TestVendor&category=knowledge" +
          "&sort=sparse-benchmark-1&dir=desc&compare=sparse-eligible" +
          "&model=sparse-eligible&zero=1"
      );
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("fails closed when a permalink tries to open both detail sheets", () => {
    window.history.replaceState(
      null,
      "",
      "/?v=1&model=sparse-eligible&benchmark=sparse-benchmark-1"
    );
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AppWithDataSources officialLoadResult={sparsePublishedFixture()} />);
      });
      expect(window.location.search).toBe("?v=1");
      expect(document.querySelector('[role="dialog"]')).toBeNull();
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("restores permalink state on popstate without a user interaction", () => {
    window.history.replaceState(null, "", "/?v=1&q=complete");
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AppWithDataSources officialLoadResult={sparsePublishedFixture()} />);
      });
      const search = container.querySelector('input[type="search"]') as HTMLInputElement;
      expect(search.value).toBe("complete");

      act(() => {
        window.history.pushState(null, "", "/?v=1&q=eligible");
        window.dispatchEvent(new PopStateEvent("popstate"));
      });

      expect(search.value).toBe("eligible");
      expect(window.location.search).toBe("?v=1&q=eligible");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("uses a 60% immutable cohort threshold and hides zero-score models until requested", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AppWithDataSources officialLoadResult={sparsePublishedFixture()} />);
      });

      const caption = container.querySelector("caption")?.textContent;
      expect(caption).toBe("Official benchmark scores and coverage-adjusted presentation rankings.");
      expect(container.querySelector("table")?.getAttribute("aria-describedby")).toBe(
        "overall-ranking-policy"
      );
      const policy = container.querySelector("#overall-ranking-policy")?.textContent;
      expect(policy).toContain("UI-only");
      expect(policy).toContain("at least 60%");
      expect(policy).toContain("3 of 5 benchmarks");
      expect(policy).toContain("published-score coverage");
      expect(policy).toContain("Each missing score counts as rank 5");
      const rows = Array.from(container.querySelectorAll("tbody tr"));
      expect(rows[0].textContent).toContain("Complete Model");
      expect(rows[1].textContent).toContain("Eligible Sparse Model");
      expect(rows[2].textContent).toContain("Ineligible Sparse Model");
      expect(container.textContent).not.toContain("No Published Scores Model");

      const toggle = container.querySelector(
        '[aria-label="Show models with no published scores"]'
      ) as HTMLButtonElement;
      expect(toggle).toBeTruthy();
      expect(toggle.getAttribute("aria-checked")).toBe("false");
      act(() => toggle.click());
      expect(toggle.getAttribute("aria-checked")).toBe("true");
      expect(container.textContent).toContain("No Published Scores Model");
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it("resets the zero-score visibility control when the Official snapshot remounts", () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<AppWithDataSources officialLoadResult={sparsePublishedFixture()} />);
      });
      const toggle = container.querySelector(
        '[aria-label="Show models with no published scores"]'
      ) as HTMLButtonElement;
      act(() => toggle.click());
      expect(container.textContent).toContain("No Published Scores Model");

      act(() => {
        root.render(
          <AppWithDataSources
            officialLoadResult={sparsePublishedFixture(
              "official-sparse-artifact-next",
              "e".repeat(64)
            )}
          />
        );
      });

      const resetToggle = container.querySelector(
        '[aria-label="Show models with no published scores"]'
      ) as HTMLButtonElement;
      expect(resetToggle.getAttribute("aria-checked")).toBe("false");
      expect(container.textContent).not.toContain("No Published Scores Model");
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
