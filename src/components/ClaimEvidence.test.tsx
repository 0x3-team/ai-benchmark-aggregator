// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { benchmarks as demoBenchmarks } from "../data/benchmarks";
import {
  DatasetProvider,
  useDataset,
  type DatasetInput,
} from "../data/dataset";
import { models as demoModels } from "../data/models";
import { BenchmarkBars } from "./BenchmarkBars";
import { BenchmarkCard } from "./BenchmarkCard";
import { ClaimEvidence, SourceManifestEvidence } from "./ClaimEvidence";
import { ModelDetail } from "./ModelDetail";
import { ScoreHeatmap } from "./ScoreHeatmap";
import { ScoreTable } from "./ScoreTable";
import { TooltipProvider } from "./ui/tooltip";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function officialFixture({ includeManifest = true }: { includeManifest?: boolean } = {}): DatasetInput {
  const model = {
    ...demoModels[0],
    id: "provenance-model",
    name: "Provenance Model",
  };
  const benchmark = {
    ...demoBenchmarks[0],
    id: "provenance-benchmark",
    name: "ProvenanceBench",
    fullName: "Provenance Benchmark",
  };
  const source = {
    sourceManifestKey: "manifest-provenance-001",
    officialSourceId: "official-source-provenance-001",
    sourceRevisionId: "source-revision-provenance-001",
    sourceRevisionDecisionId: "source-revision-decision-provenance-001",
    sourceName: "Official provenance source",
    sourceUrl: "https://official.example.test/provenance",
    sourceType: "official_api",
    sourceRevisionDefinitionSha256: "1".repeat(64),
    sourceSnapshotId: "snapshot-provenance-001",
    snapshotContentSha256: "2".repeat(64),
    snapshotCapturedAt: "2026-07-13T10:00:00.000Z",
  };
  return {
    models: [model],
    benchmarks: [benchmark],
    scores: [
      {
        modelId: model.id,
        benchmarkId: benchmark.id,
        value: 42.5,
        date: "2026-07-13T10:30:00.000Z",
        scoreRaw: "42.50 percent exactly",
        captureStatus: "published",
        officialSourceId: source.officialSourceId,
        sourceSnapshotId: source.sourceSnapshotId,
        claimId: "claim-provenance-001",
        officialProvenance: {
          displayIdentity: {
            modelId: model.id,
            benchmarkId: benchmark.id,
            metric: "accuracy",
            split: "test",
            setting: "default",
            evaluationVersion: "2026-07",
          },
          modelRaw: "Provenance Model (raw)",
          benchmarkRaw: "ProvenanceBench Raw",
          scoreRaw: "42.50 percent exactly",
          scoreUnit: "percent",
          evidenceText: "The official structured result contains the original raw score.",
          evidence: {
            type: "json_pointer",
            locator: "/results/0",
            modelLocator: "/results/0/model",
            benchmarkLocator: "/results/0/benchmark",
            scoreLocator: "/results/0/score",
          },
          source,
          claimReviewDecisionId: "claim-review-provenance-001",
          claimPublicationDecisionId: "claim-publication-provenance-001",
          captureMethod: "official_api_json",
        },
      },
    ],
    officialRelease: {
      artifactId: "official-artifact-provenance-001",
      policyVersion: "official-release-artifact-v2",
      releaseApprovalDecisionId: "release-approval-provenance-001",
      releaseApprovedAt: "2026-07-13T11:00:00.000Z",
      sourceManifest: includeManifest ? [source] : [],
    },
  };
}

function render(ui: React.ReactNode): {
  container: HTMLDivElement;
  root: Root;
  cleanup: () => void;
} {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  return {
    container,
    root,
    cleanup() {
      act(() => root.unmount());
      container.remove();
    },
  };
}

function EvidenceProbe() {
  const { models, benchmarks, getScoreEntry } = useDataset();
  const model = models[0];
  const benchmark = benchmarks[0];
  return (
    <ClaimEvidence
      entry={getScoreEntry(model.id, benchmark.id)}
      modelName={model.name}
      benchmarkName={benchmark.fullName}
    />
  );
}

function CustomTriggerProbe() {
  const { models, benchmarks, getScoreEntry } = useDataset();
  const model = models[0];
  const benchmark = benchmarks[0];
  return (
    <ClaimEvidence
      entry={getScoreEntry(model.id, benchmark.id)}
      modelName={model.name}
      benchmarkName={benchmark.fullName}
      trigger={<button type="button" aria-label="" data-custom-evidence-trigger />}
    />
  );
}

function claimEvidenceButtons(root: ParentNode = document): HTMLButtonElement[] {
  return Array.from(root.querySelectorAll("button")).filter((candidate) =>
    candidate.getAttribute("aria-label")?.startsWith("View claim evidence for")
  ) as HTMLButtonElement[];
}

describe("ClaimEvidence", () => {
  it("renders full raw claim, source, snapshot, evidence, approval, and policy details through a focusable control", () => {
    const view = render(
      <DatasetProvider data={officialFixture()}>
        <EvidenceProbe />
      </DatasetProvider>
    );
    try {
      const trigger = claimEvidenceButtons(view.container)[0];
      expect(trigger).toBeTruthy();
      expect(trigger.tabIndex).toBe(0);
      trigger.focus();
      act(() => trigger.click());

      // Base UI portals popover content to document.body rather than the render root.
      const content = document.body.textContent ?? "";
      for (const expected of [
        "42.50 percent exactly",
        "Provenance Model (raw)",
        "ProvenanceBench Raw",
        "claim-provenance-001",
        "snapshot-provenance-001",
        "2026-07-13T10:00:00.000Z",
        "official-release-artifact-v2",
        "release-approval-provenance-001",
        "claim-review-provenance-001",
        "claim-publication-provenance-001",
        "manifest-provenance-001",
        "source-revision-provenance-001",
        "source-revision-decision-provenance-001",
        "official_api",
        "accuracy",
        "2026-07",
        "/results/0/score",
      ]) {
        expect(content).toContain(expected);
      }
      const sourceLink = Array.from(document.body.querySelectorAll("a")).find(
        (anchor) => anchor.getAttribute("href") === "https://official.example.test/provenance"
      );
      expect(sourceLink?.textContent).toContain("Official provenance source");
      expect(document.activeElement).toBe(trigger);
    } finally {
      view.cleanup();
    }
  });

  it("adds an accessible name to a reusable custom score trigger and restores focus after Escape", () => {
    const view = render(
      <DatasetProvider data={officialFixture()}>
        <CustomTriggerProbe />
      </DatasetProvider>
    );
    try {
      const trigger = view.container.querySelector<HTMLButtonElement>("[data-custom-evidence-trigger]");
      expect(trigger).toBeTruthy();
      expect(trigger?.getAttribute("aria-label")).toBe(
        "View claim evidence for Provenance Model on Provenance Benchmark"
      );
      expect(trigger?.tabIndex).toBe(0);
      trigger?.focus();
      act(() => trigger?.click());
      expect(document.body.textContent).toContain("Claim evidence");
      act(() => {
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      });
      expect(document.body.textContent).not.toContain("Raw score");
      expect(document.activeElement).toBe(trigger);
    } finally {
      view.cleanup();
    }
  });

  it("fails closed for Demo-like or manifest-mismatched data", () => {
    const noManifest = render(
      <DatasetProvider data={officialFixture({ includeManifest: false })}>
        <EvidenceProbe />
      </DatasetProvider>
    );
    try {
      expect(claimEvidenceButtons(noManifest.container)).toHaveLength(0);
    } finally {
      noManifest.cleanup();
    }

    const mixed = officialFixture();
    const score = mixed.scores[0];
    if (!score.officialProvenance) throw new Error("Expected provenance fixture.");
    score.officialProvenance = {
      ...score.officialProvenance,
      source: {
        ...score.officialProvenance.source,
        sourceUrl: "https://different.example.test/stale-source",
      },
    };
    const mismatched = render(
      <DatasetProvider data={mixed}>
        <EvidenceProbe />
      </DatasetProvider>
    );
    try {
      expect(claimEvidenceButtons(mismatched.container)).toHaveLength(0);
    } finally {
      mismatched.cleanup();
    }
  });

  it("never creates an unsafe or empty source anchor when a manually supplied dataset is malformed", () => {
    const data = officialFixture();
    const source = data.officialRelease!.sourceManifest[0];
    source.sourceUrl = "javascript:alert('unsafe')";
    const view = render(
      <DatasetProvider data={data}>
        <EvidenceProbe />
      </DatasetProvider>
    );
    try {
      const trigger = claimEvidenceButtons(view.container)[0];
      expect(trigger).toBeTruthy();
      act(() => trigger.click());
      expect(document.body.textContent).toContain("Official provenance source");
      expect(
        Array.from(document.body.querySelectorAll("a")).some(
          (anchor) => anchor.getAttribute("href") === "javascript:alert('unsafe')"
        )
      ).toBe(false);
    } finally {
      view.cleanup();
    }
  });

  it("makes every individual-score surface expose a claim-evidence control without nesting buttons", () => {
    const data = officialFixture();
    const model = data.models[0];
    const benchmark = data.benchmarks[0];
    const view = render(
      <DatasetProvider data={data}>
        <TooltipProvider>
          <ScoreTable
            models={[model]}
            benchmarks={[benchmark]}
            sort={null}
            onSort={vi.fn()}
            onBenchmarkClick={vi.fn()}
            onOpenModel={vi.fn()}
            onClearSort={vi.fn()}
            onToggleModelSelect={vi.fn()}
            selectedModels={[]}
            rankMap={{ [model.id]: 1 }}
          />
          <ScoreHeatmap models={[model]} benchmarks={[benchmark]} onOpenModel={vi.fn()} />
          <ModelDetail
            model={model}
            models={[model]}
            benchmarks={[benchmark]}
            selectedModels={[]}
            onToggleModelSelect={vi.fn()}
          />
          <BenchmarkCard benchmark={benchmark} models={[model]} />
          <BenchmarkBars models={[model]} benchmarks={[benchmark]} onOpenModel={vi.fn()} />
        </TooltipProvider>
      </DatasetProvider>
    );
    try {
      expect(claimEvidenceButtons(view.container).length).toBeGreaterThanOrEqual(7);
      expect(view.container.querySelectorAll("button button")).toHaveLength(0);
      expect(view.container.querySelectorAll(".data-claim-evidence").length).toBeGreaterThanOrEqual(7);
    } finally {
      view.cleanup();
    }
  });

  it("renders a guarded keyboard-accessible release source-manifest disclosure", () => {
    const data = officialFixture();
    const release = data.officialRelease!;
    const view = render(
      <SourceManifestEvidence
        artifactId={release.artifactId}
        policyVersion={release.policyVersion}
        sourceManifest={release.sourceManifest}
      />
    );
    try {
      const trigger = view.container.querySelector<HTMLButtonElement>(
        '[aria-label^="View release source manifest"]'
      );
      expect(trigger).toBeTruthy();
      trigger!.focus();
      act(() => trigger!.click());
      expect(document.body.textContent).toContain("Release source manifest");
      expect(document.body.textContent).toContain("source-revision-provenance-001");
      expect(document.body.textContent).toContain("source-revision-decision-provenance-001");
      expect(document.body.textContent).toContain("manifest-provenance-001");
      expect(document.activeElement).toBe(trigger);
    } finally {
      view.cleanup();
    }
  });
});
