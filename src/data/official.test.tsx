// @vitest-environment jsdom

import { StrictMode, useLayoutEffect } from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { selectDataset } from "./dataSelection";
import { DatasetProvider, useDataset, type DatasetInput } from "./dataset";
import {
  loadOfficialData,
  parseOfficialArtifact,
  parsePublishedOfficialArtifact,
  publishedArtifactDigest,
  type OfficialLoadResult,
  type OfficialReleaseAuthorization,
} from "./official";
import { fixtureDataset } from "./testFixtures";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

interface PublishedArtifactFixture {
  schemaVersion: string;
  artifactKind: string;
  artifactId: string;
  availability: string;
  policyVersion: string;
  releaseApproval: {
    decisionId: string;
    policyVersion: string;
    approvedAt: string;
  };
  manifest: {
    algorithm: string;
    contentSha256: string;
    modelCount: number;
    benchmarkCount: number;
    sourceSnapshotCount: number;
    scoreCount: number;
  };
  models: Record<string, unknown>[];
  benchmarks: Record<string, unknown>[];
  sourceManifest: Record<string, unknown>[];
  scores: Record<string, unknown>[];
  [key: string]: unknown;
}

type MalformedPublishedArtifactFixture = Omit<
  PublishedArtifactFixture,
  "releaseApproval"
> & {
  releaseApproval?: PublishedArtifactFixture["releaseApproval"];
};

function demoFixture(): DatasetInput {
  return fixtureDataset();
}

function publishedArtifactFixture(): PublishedArtifactFixture {
  const sourceManifest = {
    sourceManifestKey: "source-manifest-001",
    officialSourceId: "official-source-001",
    sourceRevisionId: "source-revision-001",
    sourceRevisionDecisionId: "source-revision-decision-001",
    sourceName: "Official structured benchmark source",
    sourceUrl: "https://official.example.test/benchmarks",
    sourceType: "official_api",
    sourceRevisionDefinitionSha256: "1".repeat(64),
    sourceSnapshotId: "snapshot-001",
    snapshotContentSha256: "2".repeat(64),
    snapshotCapturedAt: "2026-07-13T10:00:00.000Z",
  };
  return {
    schemaVersion: "2.0.0",
    artifactKind: "official-release-artifact",
    artifactId: "official-release-001",
    availability: "published",
    policyVersion: "official-release-artifact-v2",
    releaseApproval: {
      decisionId: "publication-decision-001",
      policyVersion: "official-release-artifact-v2",
      approvedAt: "2026-07-13T11:00:00.000Z",
    },
    manifest: {
      algorithm: "sha256-canonical-json-v1",
      contentSha256: "0".repeat(64),
      modelCount: 1,
      benchmarkCount: 1,
      sourceSnapshotCount: 1,
      scoreCount: 1,
    },
    models: [
      {
        id: "official-model-001",
        name: "Official Model",
        vendor: "Official Vendor",
        family: "Official Family",
        releaseDate: "2026-01-01",
        contextWindowK: 128,
        paramsB: null,
        modalities: ["text"],
        openWeights: false,
        priceInPer1M: null,
        priceOutPer1M: null,
      },
    ],
    benchmarks: [
      {
        id: "official-benchmark-001",
        name: "OfficialBench",
        fullName: "Official Benchmark",
        category: "reasoning",
        higherIsBetter: true,
        scaleMax: 100,
        description: "A fully described official benchmark.",
        methodology: "The release artifact preserves the approved methodology.",
        sourceUrl: "https://official.example.test/benchmarks/official-bench",
      },
    ],
    sourceManifest: [sourceManifest],
    scores: [
      {
        cell: {
          modelId: "official-model-001",
          benchmarkId: "official-benchmark-001",
          metric: "accuracy",
          split: "test",
          setting: "default",
          evaluationVersion: "2026-07",
        },
        claimId: "claim-001",
        // Zero is valid and must not be mistaken for missing data.
        value: 0,
        modelRaw: "Official Model Raw",
        benchmarkRaw: "OfficialBench Raw",
        scoreRaw: "0",
        scoreUnit: "percent",
        reportedAt: "2026-07-13T10:00:00.000Z",
        evidenceText: "Official Model Raw scored 0 on OfficialBench Raw.",
        evidence: {
          type: "json_pointer",
          locator: "/results/0",
          modelLocator: "/results/0/model",
          benchmarkLocator: "/results/0/benchmark",
          scoreLocator: "/results/0/score",
        },
        provenance: {
          ...sourceManifest,
          claimReviewDecisionId: "review-decision-001",
          claimPublicationDecisionId: "claim-publication-decision-001",
          captureMethod: "official_api_json",
        },
      },
    ],
  };
}

async function seal(
  artifact: PublishedArtifactFixture
): Promise<PublishedArtifactFixture> {
  artifact.manifest.contentSha256 = await publishedArtifactDigest(artifact);
  return artifact;
}

function authorizationFor(
  artifact: PublishedArtifactFixture
): OfficialReleaseAuthorization {
  return {
    artifactId: artifact.artifactId,
    releaseApprovalDecisionId: artifact.releaseApproval.decisionId,
    policyVersion: artifact.policyVersion,
    contentSha256: artifact.manifest.contentSha256,
  };
}

async function parsedPublishedFixture(
  mutate?: (artifact: PublishedArtifactFixture) => void
): Promise<OfficialLoadResult> {
  const artifact = publishedArtifactFixture();
  mutate?.(artifact);
  try {
    await seal(artifact);
  } catch {
    // A non-finite value cannot be canonicalized; the parser still needs to
    // demonstrate its fail-closed result for that malformed in-memory input.
  }
  return parsePublishedOfficialArtifact(artifact, {
    artifactId: artifact.artifactId,
    releaseApprovalDecisionId: artifact.releaseApproval?.decisionId ?? "missing-approval",
    policyVersion: artifact.policyVersion,
    contentSha256: artifact.manifest.contentSha256,
  });
}

function expectUnavailable(result: OfficialLoadResult) {
  expect(result.availability).toBe("unavailable");
}

describe("future governed v2 Official artifact parser", () => {
  it("parses an authorization-pinned artifact without normalizing raw score/provenance fields", async () => {
    const result = await parsedPublishedFixture();
    expect(result.availability).toBe("published");
    if (result.availability !== "published") throw new Error("Expected a published fixture.");

    expect(result.artifact).toMatchObject({
      artifactId: "official-release-001",
      policyVersion: "official-release-artifact-v2",
      releaseApproval: { decisionId: "publication-decision-001" },
      manifest: { scoreCount: 1 },
    });
    expect(result.data.models[0]).toMatchObject({
      id: "official-model-001",
      paramsB: null,
      priceInPer1M: null,
      priceOutPer1M: null,
    });
    expect(result.data.scores[0]).toMatchObject({
      modelId: "official-model-001",
      benchmarkId: "official-benchmark-001",
      value: 0,
      scoreRaw: "0",
      claimId: "claim-001",
      officialProvenance: {
        modelRaw: "Official Model Raw",
        benchmarkRaw: "OfficialBench Raw",
        scoreRaw: "0",
        evidence: { scoreLocator: "/results/0/score" },
        source: {
          sourceManifestKey: "source-manifest-001",
          sourceSnapshotId: "snapshot-001",
        },
      },
    });
    expect(result.data.officialRelease).toMatchObject({
      artifactId: "official-release-001",
      policyVersion: "official-release-artifact-v2",
      releaseApprovalDecisionId: "publication-decision-001",
      sourceManifest: [
        {
          sourceManifestKey: "source-manifest-001",
          sourceSnapshotId: "snapshot-001",
        },
      ],
    });
  });

  it("preserves explicit not-supplied model metadata without inventing values", async () => {
    const result = await parsedPublishedFixture((artifact) => {
      artifact.models[0].contextWindowK = null;
      artifact.models[0].openWeights = null;
    });

    expect(result.availability).toBe("published");
    if (result.availability !== "published") throw new Error("Expected a published fixture.");
    expect(result.data.models[0]).toMatchObject({
      contextWindowK: null,
      openWeights: null,
    });
  });

  it("requires an independently pinned release authorization and an unmodified canonical digest", async () => {
    const artifact = await seal(publishedArtifactFixture());
    const authorization = authorizationFor(artifact);
    expectUnavailable(
      await parsePublishedOfficialArtifact(artifact, {
        ...authorization,
        contentSha256: "f".repeat(64),
      })
    );

    artifact.scores[0].scoreRaw = "tampered after approval";
    expectUnavailable(await parsePublishedOfficialArtifact(artifact, authorization));
  });

  it("rejects every current containment, candidate, report, sample-like, and extra-key shape", async () => {
    const authorization = authorizationFor(await seal(publishedArtifactFixture()));
    const unavailableV1 = {
      schemaVersion: "1.0.0",
      artifactKind: "official-release-artifact",
      artifactId: "unavailable-v1",
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
      reason: "Containment",
      models: [],
      benchmarks: [],
      sourceManifest: [],
      scores: [],
    };
    const candidate = {
      schemaVersion: "1.0.0",
      policyVersion: "official-feed-projection-v1",
      availability: "candidate",
      manifest: {},
      models: [],
      benchmarks: [],
      sourceManifest: [],
      scores: [],
      excludedClaims: [],
    };
    const legacyReport = {
      schemaVersion: "1.0.0",
      policyVersion: "legacy-inventory-v1",
      availability: "report_only",
      manifest: {},
      summary: {},
      claims: [],
      snapshots: [],
      conflicts: [],
    };
    const sampleLike = {
      schemaVersion: "0.1.0",
      models: [{ id: "sample" }],
      benchmarks: [],
      scores: [],
    };

    for (const input of [unavailableV1, candidate, legacyReport, sampleLike]) {
      expectUnavailable(await parsePublishedOfficialArtifact(input, authorization));
    }
    expectUnavailable(
      await parsedPublishedFixture((artifact) => {
        artifact.untrackedLocalFallback = true;
      })
    );
    expectUnavailable(
      await parsedPublishedFixture((artifact) => {
        delete (artifact as MalformedPublishedArtifactFixture).releaseApproval;
      })
    );
  });

  it("fails closed for structural, numeric, identity, metadata, and provenance mutations even with a fresh digest", async () => {
    const cases: Array<[
      string,
      (artifact: PublishedArtifactFixture) => void
    ]> = [
      [
        "unsupported policy",
        (artifact) => {
          artifact.policyVersion = "official-feed-projection-v1";
        },
      ],
      [
        "published artifact without a matching approval policy",
        (artifact) => {
          artifact.releaseApproval.policyVersion = "other-policy";
        },
      ],
      [
        "manifest count mismatch",
        (artifact) => {
          artifact.manifest.scoreCount = 2;
        },
      ],
      [
        "null published numeric value",
        (artifact) => {
          artifact.scores[0].value = null;
        },
      ],
      [
        "string published numeric value",
        (artifact) => {
          artifact.scores[0].value = "0";
        },
      ],
      [
        "non-finite published numeric value",
        (artifact) => {
          artifact.scores[0].value = Number.NaN;
        },
      ],
      [
        "missing raw score",
        (artifact) => {
          artifact.scores[0].scoreRaw = "";
        },
      ],
      [
        "missing closed evidence field",
        (artifact) => {
          const evidence = artifact.scores[0].evidence as Record<string, unknown>;
          delete evidence.scoreLocator;
        },
      ],
      [
        "provenance mismatch",
        (artifact) => {
          const provenance = artifact.scores[0].provenance as Record<string, unknown>;
          provenance.snapshotContentSha256 = "9".repeat(64);
        },
      ],
      [
        "orphan model reference",
        (artifact) => {
          const cell = artifact.scores[0].cell as Record<string, unknown>;
          cell.modelId = "unresolved-model";
        },
      ],
      [
        "duplicate model id",
        (artifact) => {
          artifact.models.push({ ...artifact.models[0] });
          artifact.manifest.modelCount = 2;
        },
      ],
      [
        "two display variants for one UI cell",
        (artifact) => {
          const duplicate = structuredClone(artifact.scores[0]) as Record<string, unknown>;
          duplicate.claimId = "claim-002";
          (duplicate.cell as Record<string, unknown>).metric = "z-score";
          artifact.scores.push(duplicate);
          artifact.manifest.scoreCount = 2;
        },
      ],
      [
        "incomplete model display metadata",
        (artifact) => {
          artifact.models[0].vendor = "";
        },
      ],
      [
        "unsafe source url",
        (artifact) => {
          artifact.sourceManifest[0].sourceUrl = "http://official.example.test/unsafe";
          (artifact.scores[0].provenance as Record<string, unknown>).sourceUrl =
            "http://official.example.test/unsafe";
        },
      ],
    ];

    for (const [label, mutate] of cases) {
      const result = await parsedPublishedFixture(mutate);
      expect(result.availability, label).toBe("unavailable");
    }
  });

  it("admits only public canonical HTTPS URLs for governed benchmark and source links", async () => {
    const unsafeUrls = [
      "https://official.example.test/benchmarks?token=secret",
      "https://official.example.test/benchmarks?api_key=secret",
      "https://official.example.test/benchmarks?X-Amz-Signature=secret",
      "https://official.example.test/benchmarks?view=full",
      "https://user:password@official.example.test/benchmarks",
      "https://official.example.test/benchmarks#results",
    ];

    const targets: Array<[
      string,
      (artifact: PublishedArtifactFixture, url: string) => void
    ]> = [
      [
        "benchmark source",
        (artifact, url) => {
          artifact.benchmarks[0].sourceUrl = url;
        },
      ],
      [
        "source manifest",
        (artifact, url) => {
          artifact.sourceManifest[0].sourceUrl = url;
          (artifact.scores[0].provenance as Record<string, unknown>).sourceUrl = url;
        },
      ],
    ];

    for (const [target, mutate] of targets) {
      for (const unsafeUrl of unsafeUrls) {
        const result = await parsedPublishedFixture((artifact) => mutate(artifact, unsafeUrl));
        expect(result.availability, `${target}: ${unsafeUrl}`).toBe("unavailable");
      }
    }

    const validUrl = "https://official.example.test/benchmarks/public";
    const valid = await parsedPublishedFixture((artifact) => {
      artifact.benchmarks[0].sourceUrl = validUrl;
      artifact.sourceManifest[0].sourceUrl = validUrl;
      (artifact.scores[0].provenance as Record<string, unknown>).sourceUrl = validUrl;
    });
    expect(valid.availability).toBe("published");
  });

  it("keeps the containment loader separate from the dormant published parser", () => {
    expect(loadOfficialData()).toMatchObject({ availability: "unavailable" });
    expect(parseOfficialArtifact(publishedArtifactFixture())).toMatchObject({
      availability: "unavailable",
    });
  });

  it("contains no runtime import or glob fallback for sample, ignored local, candidate, or report data", async () => {
    const source = await readFile(resolve(process.cwd(), "src/data/official.ts"), "utf8");
    expect(source).toContain('import unavailableArtifact from "./official/export.unavailable.json"');
    expect(source).not.toContain("export.sample.json");
    expect(source).not.toContain("export.from-ledger.json");
    expect(source).not.toContain("import.meta.glob");
    expect(source).not.toContain("as OfficialExport");
  });
});

interface SelectionCommit {
  mode: string;
  modelId: string;
  benchmarkId: string;
  value: number | null;
  provenanceSource: string | null;
}

function SelectionProbe({
  mode,
  commits,
}: {
  mode: string;
  commits: SelectionCommit[];
}) {
  const { models, benchmarks, getValue, getScoreEntry } = useDataset();
  const model = models[0];
  const benchmark = benchmarks[0];
  const entry = getScoreEntry(model.id, benchmark.id);
  useLayoutEffect(() => {
    commits.push({
      mode,
      modelId: model.id,
      benchmarkId: benchmark.id,
      value: getValue(model.id, benchmark.id),
      provenanceSource: entry?.officialProvenance?.source.officialSourceId ?? null,
    });
  });
  return null;
}

function SelectionHarness({
  requestedMode,
  demo,
  official,
  commits,
}: {
  requestedMode: "demo" | "official";
  demo: DatasetInput;
  official: OfficialLoadResult;
  commits: SelectionCommit[];
}) {
  const selection = selectDataset(requestedMode, demo, official);
  return (
    <DatasetProvider data={selection.data}>
      <SelectionProbe mode={selection.mode} commits={commits} />
    </DatasetProvider>
  );
}

describe("atomic Official dataset selection", () => {
  it("retains Demo data and mode when the tracked artifact is unavailable", () => {
    const demo = demoFixture();
    const selection = selectDataset("official", demo, loadOfficialData());
    expect(selection.mode).toBe("demo");
    expect(selection.data).toBe(demo);
    expect(selection.official.availability).toBe("unavailable");
  });

  it("commits matching mode, values, and provenance across Demo → parsed Official → Demo", async () => {
    const official = await parsedPublishedFixture();
    expect(official.availability).toBe("published");
    const demo = demoFixture();
    const container = document.createElement("div");
    const root = createRoot(container);
    const commits: SelectionCommit[] = [];

    function render(requestedMode: "demo" | "official") {
      act(() => {
        root.render(
          <StrictMode>
            <SelectionHarness
              requestedMode={requestedMode}
              demo={demo}
              official={official}
              commits={commits}
            />
          </StrictMode>
        );
      });
    }

    render("demo");
    const demoInitial = [...commits];
    render("official");
    const officialCommits = commits.slice(demoInitial.length);
    render("demo");
    const demoReturned = commits.slice(demoInitial.length + officialCommits.length);
    act(() => root.unmount());

    const demoScore = demo.scores[0];
    for (const entry of demoInitial) {
      expect(entry).toMatchObject({
        mode: "demo",
        modelId: demo.models[0].id,
        benchmarkId: demo.benchmarks[0].id,
        value: demoScore.value,
        provenanceSource: null,
      });
    }
    for (const entry of officialCommits) {
      expect(entry).toMatchObject({
        mode: "official",
        modelId: "official-model-001",
        benchmarkId: "official-benchmark-001",
        value: 0,
        provenanceSource: "official-source-001",
      });
    }
    for (const entry of demoReturned) {
      expect(entry).toMatchObject({
        mode: "demo",
        modelId: demo.models[0].id,
        benchmarkId: demo.benchmarks[0].id,
        value: demoScore.value,
        provenanceSource: null,
      });
    }
  });
});
