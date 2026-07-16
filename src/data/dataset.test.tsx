// @vitest-environment jsdom

import { StrictMode, useLayoutEffect } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { act } from "react";
import { describe, expect, it } from "vitest";
import { benchmarks as demoBenchmarks } from "./benchmarks";
import {
  DatasetProvider,
  createDatasetAccess,
  useDataset,
  type DatasetInput,
} from "./dataset";
import { models as demoModels } from "./models";
import { loadOfficialData, parseOfficialArtifact } from "./official";
import { getScores } from "./scores";

// React's act() uses this documented test-environment flag to surface
// asynchronous commit mistakes instead of silently accepting them.
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function demoFixture(): DatasetInput {
  const model = demoModels[0];
  const benchmark = demoBenchmarks[0];
  const score = getScores().find(
    (entry) => entry.modelId === model.id && entry.benchmarkId === benchmark.id
  );
  if (!score) throw new Error("Expected demo score fixture.");
  return { models: [model], benchmarks: [benchmark], scores: [score] };
}

// This is an in-memory provider fixture only. It is not parsed by
// loadOfficialData(), bundled into the app, or selectable as Official mode.
function alternateFixture(): DatasetInput {
  const demo = demoFixture();
  const model = { ...demo.models[0], id: "alternate-model", name: "Alternate Fixture Model" };
  const benchmark = {
    ...demo.benchmarks[0],
    id: "alternate-benchmark",
    name: "Alternate Bench",
    fullName: "Alternate Benchmark",
  };
  return {
    models: [model],
    benchmarks: [benchmark],
    scores: [
      {
        modelId: model.id,
        benchmarkId: benchmark.id,
        value: 91.2,
        date: "2026-07-13",
        scoreRaw: "91.2",
        officialSourceId: "fixture-source",
        sourceSnapshotId: "fixture-snapshot",
        evidenceLocation: { type: "fixture", path: "/scores/0", modelPath: "/scores/0/model" },
        claimId: "fixture-claim",
      },
    ],
  };
}

function DatasetProbe() {
  const { models, benchmarks, getValue, getScoreEntry } = useDataset();
  const model = models[0];
  const benchmark = benchmarks[0];
  const score = getScoreEntry(model.id, benchmark.id);
  return (
    <output
      data-benchmark={benchmark.id}
      data-model={model.id}
      data-provenance={score?.officialSourceId ?? "demo"}
    >
      {getValue(model.id, benchmark.id)}
    </output>
  );
}

function renderDataset(data: DatasetInput): string {
  return renderToStaticMarkup(
    <DatasetProvider data={data}>
      <DatasetProbe />
    </DatasetProvider>
  );
}

interface DatasetCommit {
  label: string;
  modelId: string;
  benchmarkId: string;
  value: number | null;
  provenanceSourceId: string | null;
}

function CommitProbe({ label, commits }: { label: string; commits: DatasetCommit[] }) {
  const { models, benchmarks, getValue, getScoreEntry } = useDataset();
  const model = models[0];
  const benchmark = benchmarks[0];
  const score = getScoreEntry(model.id, benchmark.id);
  const value = getValue(model.id, benchmark.id);

  useLayoutEffect(() => {
    commits.push({
      label,
      modelId: model.id,
      benchmarkId: benchmark.id,
      value,
      provenanceSourceId: score?.officialSourceId ?? null,
    });
  });

  return null;
}

describe("DatasetProvider", () => {
  it("creates immutable, isolated score accessors instead of module-global active data", () => {
    const demo = createDatasetAccess(demoFixture());
    const alternate = createDatasetAccess(alternateFixture());

    expect(Object.isFrozen(demo)).toBe(true);
    expect(Object.isFrozen(demo.models)).toBe(true);
    expect(Object.isFrozen(demo.benchmarks)).toBe(true);
    expect(Object.isFrozen(demo.models[0])).toBe(true);
    expect(Object.isFrozen(demo.models[0].modalities)).toBe(true);
    expect(demo.getValue(demo.models[0].id, demo.benchmarks[0].id)).not.toBeNull();
    expect(alternate.getValue("alternate-model", "alternate-benchmark")).toBe(91.2);
    expect(alternate.getScoreEntry("alternate-model", "alternate-benchmark")?.officialSourceId).toBe(
      "fixture-source"
    );
    const provenance = alternate.getScoreEntry("alternate-model", "alternate-benchmark");
    expect(provenance).toBeDefined();
    expect(Object.isFrozen(provenance)).toBe(true);
    expect(Object.isFrozen(provenance?.evidenceLocation)).toBe(true);
    expect(provenance).not.toHaveProperty("value");
    expect(demo.officialRelease).toBeNull();

    // Constructing/reading an independent snapshot cannot replace demo values.
    expect(demo.getValue(demo.models[0].id, demo.benchmarks[0].id)).not.toBeNull();
    expect(demo.getScoreEntry(demo.models[0].id, demo.benchmarks[0].id)?.officialSourceId).toBeUndefined();
  });

  it("renders complete data and provenance from the selected snapshot on each first render", () => {
    const demo = renderDataset(demoFixture());
    const alternate = renderDataset(alternateFixture());
    const demoAgain = renderDataset(demoFixture());

    expect(demo).toContain('data-model="gpt-4o"');
    expect(demo).toContain('data-provenance="demo"');
    expect(alternate).toContain('data-model="alternate-model"');
    expect(alternate).toContain('data-benchmark="alternate-benchmark"');
    expect(alternate).toContain('data-provenance="fixture-source"');
    expect(alternate).toContain(">91.2</output>");
    expect(demoAgain).toBe(demo);
  });

  it("freezes release context and nested governed provenance without exposing its value", () => {
    const base = alternateFixture();
    const source = {
      sourceManifestKey: "fixture-manifest",
      officialSourceId: "fixture-source",
      sourceRevisionId: "fixture-revision",
      sourceRevisionDecisionId: "fixture-revision-decision",
      sourceName: "Fixture official source",
      sourceUrl: "https://official.example.test/fixture",
      sourceType: "official_api",
      sourceRevisionDefinitionSha256: "1".repeat(64),
      sourceSnapshotId: "fixture-snapshot",
      snapshotContentSha256: "2".repeat(64),
      snapshotCapturedAt: "2026-07-13T10:00:00.000Z",
    };
    const input: DatasetInput = {
      ...base,
      scores: [
        {
          ...base.scores[0],
          officialProvenance: {
            displayIdentity: {
              modelId: "alternate-model",
              benchmarkId: "alternate-benchmark",
              metric: "accuracy",
              split: "test",
              setting: "default",
              evaluationVersion: "fixture",
            },
            modelRaw: "Alternate Fixture Model",
            benchmarkRaw: "Alternate Benchmark",
            scoreRaw: "91.2",
            scoreUnit: null,
            evidenceText: null,
            evidence: {
              type: "json_pointer",
              locator: "/scores/0",
              modelLocator: "/scores/0/model",
              benchmarkLocator: "/scores/0/benchmark",
              scoreLocator: "/scores/0/value",
            },
            source,
            claimReviewDecisionId: "fixture-review",
            claimPublicationDecisionId: "fixture-publication",
            captureMethod: "fixture",
          },
        },
      ],
      officialRelease: {
        artifactId: "fixture-artifact",
        policyVersion: "fixture-policy",
        releaseApprovalDecisionId: "fixture-release-approval",
        releaseApprovedAt: "2026-07-13T11:00:00.000Z",
        sourceManifest: [source],
      },
    };
    const access = createDatasetAccess(input);
    const entry = access.getScoreEntry("alternate-model", "alternate-benchmark");

    expect(Object.isFrozen(access.officialRelease)).toBe(true);
    expect(Object.isFrozen(access.officialRelease?.sourceManifest)).toBe(true);
    expect(Object.isFrozen(access.officialRelease?.sourceManifest[0])).toBe(true);
    expect(Object.isFrozen(entry?.officialProvenance)).toBe(true);
    expect(Object.isFrozen(entry?.officialProvenance?.displayIdentity)).toBe(true);
    expect(Object.isFrozen(entry?.officialProvenance?.evidence)).toBe(true);
    expect(Object.isFrozen(entry?.officialProvenance?.source)).toBe(true);
    expect(entry).not.toHaveProperty("value");
  });

  it("commits only matching values and provenance when one React tree switches Demo → fixture → Demo", () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    const commits: DatasetCommit[] = [];
    const demo = demoFixture();
    const fixture = alternateFixture();

    function render(data: DatasetInput, label: string) {
      act(() => {
        root.render(
          <StrictMode>
            <DatasetProvider data={data}>
              <CommitProbe label={label} commits={commits} />
            </DatasetProvider>
          </StrictMode>
        );
      });
    }

    render(demo, "demo-initial");
    const initialCommits = [...commits];
    render(fixture, "fixture");
    const fixtureCommits = commits.slice(initialCommits.length);
    render(demo, "demo-returned");
    const returnedCommits = commits.slice(initialCommits.length + fixtureCommits.length);
    act(() => root.unmount());

    const expectSnapshot = (
      entries: DatasetCommit[],
      expected: Omit<DatasetCommit, "label">
    ) => {
      expect(entries.length).toBeGreaterThan(0);
      for (const entry of entries) expect(entry).toMatchObject(expected);
    };

    expectSnapshot(initialCommits, {
      modelId: "gpt-4o",
      benchmarkId: demo.benchmarks[0].id,
      value: getScores().find(
        (score) =>
          score.modelId === "gpt-4o" && score.benchmarkId === demo.benchmarks[0].id
      )?.value ?? null,
      provenanceSourceId: null,
    });
    expectSnapshot(fixtureCommits, {
      modelId: "alternate-model",
      benchmarkId: "alternate-benchmark",
      value: 91.2,
      provenanceSourceId: "fixture-source",
    });
    expectSnapshot(returnedCommits, {
      modelId: "gpt-4o",
      benchmarkId: demo.benchmarks[0].id,
      value: getScores().find(
        (score) =>
          score.modelId === "gpt-4o" && score.benchmarkId === demo.benchmarks[0].id
      )?.value ?? null,
      provenanceSourceId: null,
    });
  });

  it("fails closed outside the provider, for orphan scores, and for duplicate score cells", () => {
    expect(() => renderToStaticMarkup(<DatasetProbe />)).toThrow(
      "useDataset must be used inside DatasetProvider"
    );

    const duplicate = demoFixture();
    expect(() =>
      createDatasetAccess({ ...duplicate, scores: [...duplicate.scores, duplicate.scores[0]] })
    ).toThrow("duplicate score cell");
    expect(() =>
      createDatasetAccess({
        ...duplicate,
        scores: [
          ...duplicate.scores,
          { ...duplicate.scores[0], modelId: "unknown-model" },
        ],
      })
    ).toThrow("unknown model or benchmark");
  });

  it("keeps colon-containing ids distinct instead of using a collision-prone string key", () => {
    const fixture = demoFixture();
    const firstModel = { ...fixture.models[0], id: "model:one" };
    const secondModel = { ...fixture.models[0], id: "model" };
    const firstBenchmark = { ...fixture.benchmarks[0], id: "benchmark" };
    const secondBenchmark = { ...fixture.benchmarks[0], id: "one:benchmark" };
    const access = createDatasetAccess({
      models: [firstModel, secondModel],
      benchmarks: [firstBenchmark, secondBenchmark],
      scores: [
        {
          ...fixture.scores[0],
          modelId: firstModel.id,
          benchmarkId: firstBenchmark.id,
          value: 11,
        },
        {
          ...fixture.scores[0],
          modelId: secondModel.id,
          benchmarkId: secondBenchmark.id,
          value: 22,
        },
      ],
    });

    expect(access.getValue("model:one", "benchmark")).toBe(11);
    expect(access.getValue("model", "one:benchmark")).toBe(22);
  });
});

describe("loadOfficialData", () => {
  it("uses a tracked unavailable artifact instead of a generated or sample export", () => {
    expect(loadOfficialData()).toMatchObject({ availability: "unavailable" });
  });

  it("fails closed for malformed, stale, or data-bearing unavailable artifacts", () => {
    const validUnavailableArtifact = {
      schemaVersion: "1.0.0",
      artifactKind: "official-release-artifact",
      artifactId: "fixture-unavailable-v1",
      availability: "unavailable",
      policyVersion: "official-release-artifact-v1",
      manifest: {
        algorithm: "sha256-canonical-json-v1",
        contentSha256: "0".repeat(64),
        modelCount: 0,
        benchmarkCount: 0,
        sourceSnapshotCount: 0,
        scoreCount: 0,
      },
      reason: "Fixture containment.",
      models: [],
      benchmarks: [],
      sourceManifest: [],
      scores: [],
    };
    for (const artifact of [
      null,
      { schemaVersion: "0.1.0", availability: "unavailable", reason: "old", models: [], benchmarks: [], scores: [] },
      { ...validUnavailableArtifact, availability: "published" },
      { ...validUnavailableArtifact, models: [{ id: "fake" }] },
      { ...validUnavailableArtifact, claims: [{ id: "hidden" }] },
      { ...validUnavailableArtifact, manifest: { ...validUnavailableArtifact.manifest, scoreCount: 1 } },
      {
        schemaVersion: "1.0.0",
        policyVersion: "official-feed-projection-v1",
        availability: "candidate",
        manifest: { algorithm: "sha256-canonical-json-v1", contentSha256: "0".repeat(64) },
        models: [], benchmarks: [], sourceManifest: [], scores: [], excludedClaims: [],
      },
      {
        schemaVersion: "1.0.0", policyVersion: "legacy-inventory-v1", availability: "report_only",
        manifest: {}, summary: {}, claims: [], snapshots: [], conflicts: [],
      },
    ]) {
      expect(parseOfficialArtifact(artifact)).toMatchObject({ availability: "unavailable" });
    }
  });
});
