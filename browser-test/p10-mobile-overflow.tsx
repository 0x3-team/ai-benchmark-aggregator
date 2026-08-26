import { createRoot } from "react-dom/client";
import { AppWithDataSources } from "../src/App";
import "../src/index.css";
import type { OfficialLoadResult } from "../src/data/official";
import { fixtureBenchmark, fixtureModel, fixtureScore } from "../src/data/testFixtures";

const models = [
  { ...fixtureModel, id: "p10-complete", name: "Complete Model" },
  { ...fixtureModel, id: "p10-eligible", name: "Eligible Sparse Model" },
  { ...fixtureModel, id: "p10-ineligible", name: "Ineligible Sparse Model" },
  { ...fixtureModel, id: "p10-zero", name: "No Published Scores Model" },
];
const benchmarks = Array.from({ length: 5 }, (_, index) => ({
  ...fixtureBenchmark,
  id: `p10-benchmark-${index + 1}`,
  name: `Sparse Bench ${index + 1}`,
  fullName: `Sparse Benchmark ${index + 1}`,
}));
const score = (modelId: string, benchmarkIndex: number, value: number) => ({
  ...fixtureScore,
  modelId,
  benchmarkId: benchmarks[benchmarkIndex].id,
  value,
});
const publishedFixture: OfficialLoadResult = {
  availability: "published",
  artifact: {
    artifactId: "p10-mobile-overflow-fixture",
    policyVersion: "official-release-artifact-v2",
    releaseApproval: {
      decisionId: "p10-mobile-overflow-approval",
      policyVersion: "official-release-artifact-v2",
      approvedAt: "2026-08-26T00:00:00.000Z",
    },
    manifest: {
      algorithm: "sha256-canonical-json-v1",
      contentSha256: "f".repeat(64),
      modelCount: models.length,
      benchmarkCount: benchmarks.length,
      sourceSnapshotCount: 1,
      scoreCount: 10,
    },
    sourceManifest: [],
  },
  data: {
    models,
    benchmarks,
    scores: [
      score("p10-complete", 0, 50),
      score("p10-complete", 1, 80),
      score("p10-complete", 2, 80),
      score("p10-complete", 3, 80),
      score("p10-complete", 4, 80),
      score("p10-eligible", 0, 99),
      score("p10-eligible", 1, 99),
      score("p10-eligible", 2, 99),
      score("p10-ineligible", 0, 100),
      score("p10-ineligible", 1, 100),
    ],
  },
};

createRoot(document.getElementById("root")!).render(
  <AppWithDataSources officialLoadResult={publishedFixture} />
);
