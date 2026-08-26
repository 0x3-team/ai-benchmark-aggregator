import { createRoot } from "react-dom/client";
import { AppWithDataSources } from "../src/App";
import "../src/index.css";
import type { OfficialLoadResult } from "../src/data/official";
import {
  fixtureBenchmark,
  fixtureModel,
  fixtureScore,
} from "../src/data/testFixtures";

const models = [
  {
    ...fixtureModel,
    id: "p11-alpha",
    name: "P11 Alpha",
    vendor: "Northstar",
    openWeights: true,
  },
  {
    ...fixtureModel,
    id: "p11-beta",
    name: "P11 Beta",
    vendor: "Southstar",
    openWeights: true,
  },
];

const benchmarks = [
  {
    ...fixtureBenchmark,
    id: "p11-reasoning",
    name: "P11 Reasoning",
    fullName: "P11 Reasoning Benchmark",
    category: "reasoning" as const,
  },
  {
    ...fixtureBenchmark,
    id: "p11-coding",
    name: "P11 Coding",
    fullName: "P11 Coding Benchmark",
    category: "coding" as const,
  },
];

const scores = models.flatMap((model, modelIndex) =>
  benchmarks.map((benchmark, benchmarkIndex) => ({
    ...fixtureScore,
    modelId: model.id,
    benchmarkId: benchmark.id,
    value: 70 + modelIndex * 10 + benchmarkIndex,
  }))
);

const publishedFixture: OfficialLoadResult = {
  availability: "published",
  artifact: {
    artifactId: "p11-permalink-browser-fixture",
    policyVersion: "official-release-artifact-v2",
    releaseApproval: {
      decisionId: "p11-permalink-browser-approval",
      policyVersion: "official-release-artifact-v2",
      approvedAt: "2026-08-26T00:00:00.000Z",
    },
    manifest: {
      algorithm: "sha256-canonical-json-v1",
      contentSha256: "a".repeat(64),
      modelCount: models.length,
      benchmarkCount: benchmarks.length,
      sourceSnapshotCount: 1,
      scoreCount: scores.length,
    },
    sourceManifest: [],
  },
  data: { models, benchmarks, scores },
};

createRoot(document.getElementById("root")!).render(
  <AppWithDataSources officialLoadResult={publishedFixture} />
);
