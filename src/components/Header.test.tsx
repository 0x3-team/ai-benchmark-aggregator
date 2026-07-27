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
    dataModeLabel: "Awaiting data",
    dataMode: "demo" as const,
    onDataModeChange: vi.fn(),
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

function buttonByText(container: HTMLElement, text: string): HTMLButtonElement {
  const button = Array.from(container.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.trim() === text
  );
  if (!button) throw new Error("Expected source button.");
  return button;
}

describe("Header trust status", () => {
  it("keeps unavailable Official focusable, described, and explicit about visible Demo data", () => {
    const onDataModeChange = vi.fn();
    const view = renderHeader({
      onDataModeChange,
      officialUnavailableReason: "No release artifact is authorized for this build.",
    });
    try {
      const status = view.container.querySelector("#official-data-status");
      const official = buttonByText(view.container, "Official unavailable");
      expect(status?.getAttribute("role")).toBe("status");
      expect(status?.textContent).toContain("Official claims unavailable.");
      expect(status?.textContent).toContain("No benchmark data is currently published");
      expect(official.getAttribute("aria-disabled")).toBeNull();
      expect(official.getAttribute("aria-label")).toContain("Official claims unavailable");
      expect(official.getAttribute("aria-describedby")).toBe("official-data-status");

      act(() => official.click());
      expect(onDataModeChange).toHaveBeenCalledWith("official");
    } finally {
      view.cleanup();
    }
  });

  it("shows exact artifact, approval, timestamp, and policy without a verification color cue", () => {
    const view = renderHeader({
      dataMode: "official",
      dataModeLabel: "Official claims",
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
      dataMode: "official",
      dataModeLabel: "Official claims",
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

  it("restores focus to the newly active data-source control after a mode switch", () => {
    const view = renderHeader({ officialArtifact: artifact });
    try {
      view.rerender({
        dataMode: "official",
        dataModeLabel: "Official claims",
        officialArtifact: artifact,
      });
      expect(document.activeElement).toBe(buttonByText(view.container, "Official"));
    } finally {
      view.cleanup();
    }
  });
});
