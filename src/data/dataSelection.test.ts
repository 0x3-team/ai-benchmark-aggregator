import { describe, expect, it } from "vitest";
import type { OfficialLoadResult } from "./official";
import { createDatasetAccess } from "./dataset";
import {
  AWAITING_PUBLICATION_DATASET,
  selectOfficialDataset,
} from "./dataSelection";
import { fixtureDataset } from "./testFixtures";

describe("real-only Official dataset selection", () => {
  it("uses one immutable empty snapshot when publication is unavailable", () => {
    const selection = selectOfficialDataset({
      availability: "unavailable",
      artifactId: "unavailable-fixture",
      reason: "No release is published.",
    });

    expect(selection.status).toBe("awaiting-publication");
    expect(selection.data).toBe(AWAITING_PUBLICATION_DATASET);
    expect(selection.data).toEqual({ models: [], benchmarks: [], scores: [] });
    expect(Object.isFrozen(selection.data)).toBe(true);
    expect(Object.isFrozen(selection.data.models)).toBe(true);
  });

  it("selects only a published result and preserves getValue-only access", () => {
    const data = fixtureDataset();
    const published: OfficialLoadResult = {
      availability: "published",
      artifact: {
        artifactId: "published-fixture",
        policyVersion: "official-release-artifact-v2",
        releaseApproval: {
          decisionId: "published-fixture-approval",
          policyVersion: "official-release-artifact-v2",
          approvedAt: "2026-08-25T00:00:00.000Z",
        },
        manifest: {
          algorithm: "sha256-canonical-json-v1",
          contentSha256: "a".repeat(64),
          modelCount: 1,
          benchmarkCount: 1,
          sourceSnapshotCount: 0,
          scoreCount: 1,
        },
        sourceManifest: [],
      },
      data,
    };

    const selection = selectOfficialDataset(published);
    expect(selection.status).toBe("official");
    const access = createDatasetAccess(selection.data);
    expect(access.getValue(data.models[0].id, data.benchmarks[0].id)).toBe(
      data.scores[0].value
    );
  });
});
