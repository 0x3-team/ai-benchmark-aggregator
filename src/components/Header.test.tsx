// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { Header } from "./Header";
import type { PublishedArtifactMetadata } from "../data/official";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const artifact: PublishedArtifactMetadata = {
  artifactId: "official-release-001",
  policyVersion: "official-release-artifact-v2",
  releaseApproval: {
    decisionId: "publication-decision-001",
    policyVersion: "official-release-artifact-v2",
    approvedAt: "2026-07-13T11:00:00.000Z",
  },
  manifest: {
    algorithm: "sha256-canonical-json-v1",
    contentSha256: "a".repeat(64),
    modelCount: 1,
    benchmarkCount: 1,
    sourceSnapshotCount: 1,
    scoreCount: 1,
  },
  sourceManifest: [],
};

const artifactWithSourceManifest: PublishedArtifactMetadata = {
  ...artifact,
  sourceManifest: [
    {
      sourceManifestKey: "header-manifest-001",
      officialSourceId: "header-source-001",
      sourceRevisionId: "header-revision-001",
      sourceRevisionDecisionId: "header-revision-decision-001",
      sourceName: "Header official source",
      sourceUrl: "https://official.example.test/header-source",
      sourceType: "official_api",
      sourceRevisionDefinitionSha256: "a".repeat(64),
      sourceSnapshotId: "header-snapshot-001",
      snapshotContentSha256: "b".repeat(64),
      snapshotCapturedAt: "2026-07-13T10:00:00.000Z",
    },
  ],
};

interface HeaderHarness {
  container: HTMLDivElement;
  root: Root;
  rerender: (props: Partial<Parameters<typeof Header>[0]>) => void;
  cleanup: () => void;
}

function renderHeader(
  overrides: Partial<Parameters<typeof Header>[0]> = {}
): HeaderHarness {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const base = {
    totalModels: 1,
    totalBenchmarks: 1,
    view: "table" as const,
    onViewChange: vi.fn(),
    selectedCount: 0,
    onOpenGlossary: vi.fn(),
    dataStatus: "awaiting-publication" as const,
  };

  function render(next: Partial<Parameters<typeof Header>[0]>) {
    act(() => {
      root.render(<Header {...base} {...next} />);
    });
  }

  render(overrides);
  return {
    container,
    root,
    rerender: render,
    cleanup() {
      act(() => root.unmount());
      container.remove();
    },
  };
}

describe("Header trust status", () => {
  it("states that the unavailable build is awaiting publication and shows no source toggle", () => {
    const view = renderHeader({
      officialUnavailableReason: "No release artifact is authorized for this build.",
    });
    try {
      const status = view.container.querySelector("#official-data-status");
      expect(status?.getAttribute("role")).toBe("status");
      expect(status?.textContent).toContain("Awaiting Official publication.");
      expect(status?.textContent).toContain("No benchmark data is currently published");
      expect(status?.textContent).not.toContain("Synthetic");
      expect(view.container.querySelector('[aria-label="Data source"]')).toBeNull();
      expect(view.container.textContent).toContain("Awaiting publication");
    } finally {
      view.cleanup();
    }
  });

  it("shows exact artifact, approval, timestamp, and policy without a verification color cue", () => {
    const view = renderHeader({
      dataStatus: "official",
      officialArtifact: artifact,
    });
    try {
      const status = view.container.querySelector("#official-data-status");
      expect(status?.textContent).toContain("Values are source-reported ledger claims");
      expect(status?.textContent).toContain(artifact.artifactId);
      expect(status?.textContent).toContain(artifact.releaseApproval.decisionId);
      expect(status?.textContent).toContain(artifact.releaseApproval.approvedAt);
      expect(status?.textContent).toContain(artifact.policyVersion);
      expect(status?.className).not.toContain("emerald");
      expect(status?.className).not.toContain("animate-pulse");
    } finally {
      view.cleanup();
    }
  });

  it("consumes the governed source manifest through a keyboard-operable disclosure", () => {
    const view = renderHeader({
      dataStatus: "official",
      officialArtifact: artifactWithSourceManifest,
    });
    try {
      const trigger = view.container.querySelector<HTMLButtonElement>(
        '[aria-label^="View release source manifest"]'
      );
      expect(trigger).toBeTruthy();
      expect(trigger?.tabIndex).toBe(0);
      trigger?.focus();
      act(() => trigger?.click());
      expect(document.body.textContent).toContain("Header official source");
      expect(document.body.textContent).toContain("header-revision-decision-001");
      expect(document.activeElement).toBe(trigger);
    } finally {
      view.cleanup();
    }
  });
});
