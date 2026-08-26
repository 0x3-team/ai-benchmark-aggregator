import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import test from "node:test";

import {
  OfficialArtifactValidationError,
  OFFICIAL_RELEASE_AUTHORIZATION_CONTRACT_PATH,
  PUBLISHED_OFFICIAL_ARTIFACT_CONTRACT_PATH,
  REPOSITORY_ROOT,
  TRACKED_OFFICIAL_ARTIFACT_PATH,
  canonicalOfficialArtifactJson,
  officialArtifactDigest,
  validateOfficialArtifactContractSchema,
  validateOfficialReleaseAuthorization,
  validateOfficialReleaseAuthorizationContractSchema,
  validatePublishedOfficialArtifactContractSchema,
  validatePublishedOfficialReleaseArtifact,
  validateOfficialReleaseArtifact,
  verifyPublishedOfficialArtifactBytes,
  verifyPublishedOfficialArtifactFiles,
  verifyTrackedOfficialArtifactContract,
  verifyTrackedOfficialArtifact,
} from "./verify-official-artifact.mjs";

const execFileAsync = promisify(execFile);

async function trackedArtifact() {
  return JSON.parse(await readFile(TRACKED_OFFICIAL_ARTIFACT_PATH, "utf8"));
}

function publishedArtifact() {
  const sourceManifest = {
    sourceManifestKey: "source-manifest-001",
    officialSourceId: "official-source-001",
    sourceRevisionId: "source-revision-001",
    sourceRevisionDecisionId: "source-decision-001",
    sourceName: "Official source",
    sourceUrl: "https://official.example.test/results",
    sourceType: "official_api",
    sourceRevisionDefinitionSha256: "1".repeat(64),
    sourceSnapshotId: "snapshot-001",
    snapshotContentSha256: "2".repeat(64),
    snapshotCapturedAt: "2026-08-26T10:00:00.000Z",
  };
  const artifact = {
    schemaVersion: "2.0.0",
    artifactKind: "official-release-artifact",
    artifactId: "official-release-test-001",
    availability: "published",
    policyVersion: "official-release-artifact-v2",
    releaseApproval: {
      decisionId: "release-approval-test-001",
      policyVersion: "official-release-artifact-v2",
      approvedAt: "2026-08-26T11:00:00.000Z",
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
        id: "model-001",
        name: "Model 001",
        vendor: "Vendor",
        family: "Family",
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
        id: "benchmark-001",
        name: "Bench",
        fullName: "Benchmark",
        category: "reasoning",
        higherIsBetter: true,
        scaleMax: 100,
        description: "Description",
        methodology: "Methodology",
        sourceUrl: "https://official.example.test/benchmark",
      },
    ],
    sourceManifest: [sourceManifest],
    scores: [
      {
        cell: {
          modelId: "model-001",
          benchmarkId: "benchmark-001",
          metric: "accuracy",
          split: "test",
          setting: "default",
          evaluationVersion: "v1",
        },
        claimId: "claim-001",
        value: 91.25,
        modelRaw: "Model raw",
        benchmarkRaw: "Benchmark raw",
        scoreRaw: "91.2500",
        scoreUnit: "percent",
        reportedAt: "2026-08-26T09:00:00.000Z",
        evidenceText: "Model raw scored 91.2500.",
        evidence: {
          type: "json_pointer",
          locator: "/results/0",
          modelLocator: "/results/0/model",
          benchmarkLocator: "/results/0/benchmark",
          scoreLocator: "/results/0/score",
        },
        provenance: {
          ...sourceManifest,
          claimReviewDecisionId: "review-001",
          claimPublicationDecisionId: "publication-001",
          captureMethod: "official_api_json",
        },
      },
    ],
  };
  artifact.manifest.contentSha256 = officialArtifactDigest(artifact);
  return artifact;
}

function authorizationFor(artifact) {
  return {
    artifactId: artifact.artifactId,
    contentSha256: artifact.manifest.contentSha256,
    releaseApprovalDecisionId: artifact.releaseApproval.decisionId,
    policyVersion: artifact.policyVersion,
  };
}

test("the tracked containment artifact is canonical, unavailable, and immutable by digest", async () => {
  const artifact = await verifyTrackedOfficialArtifact();
  const reordered = Object.fromEntries(Object.entries(artifact).reverse());

  assert.equal(artifact.availability, "unavailable");
  assert.equal(artifact.manifest.contentSha256, officialArtifactDigest(artifact));
  assert.equal(canonicalOfficialArtifactJson(artifact), canonicalOfficialArtifactJson(reordered));
});

test("the tracked JSON Schema stays in parity with the executable containment contract", async () => {
  const contract = await verifyTrackedOfficialArtifactContract();
  const drifted = structuredClone(contract);
  drifted.properties.availability.const = "published";

  assert.equal(contract.properties.availability.const, "unavailable");
  assert.throws(() => validateOfficialArtifactContractSchema(drifted), /availability schema/);
});

test("the v2 artifact and external authorization schemas stay closed and version-pinned", async () => {
  const [artifactContract, authorizationContract] = await Promise.all([
    readFile(PUBLISHED_OFFICIAL_ARTIFACT_CONTRACT_PATH, "utf8").then(JSON.parse),
    readFile(OFFICIAL_RELEASE_AUTHORIZATION_CONTRACT_PATH, "utf8").then(JSON.parse),
  ]);
  assert.equal(
    validatePublishedOfficialArtifactContractSchema(artifactContract).properties.availability.const,
    "published"
  );
  assert.equal(
    validateOfficialReleaseAuthorizationContractSchema(authorizationContract).additionalProperties,
    false
  );

  const drifted = structuredClone(authorizationContract);
  drifted.required.pop();
  assert.throws(
    () => validateOfficialReleaseAuthorizationContractSchema(drifted),
    /required keys/
  );
});

test("canonical v2 bytes require one exact external authorization", () => {
  const artifact = publishedArtifact();
  const authorization = authorizationFor(artifact);
  const raw = canonicalOfficialArtifactJson(artifact);

  assert.equal(
    verifyPublishedOfficialArtifactBytes(raw, authorization).artifactId,
    artifact.artifactId
  );
  assert.equal(
    validatePublishedOfficialReleaseArtifact(artifact, authorization).manifest.contentSha256,
    authorization.contentSha256
  );
  assert.equal(validateOfficialReleaseAuthorization(authorization), authorization);

  assert.throws(
    () => verifyPublishedOfficialArtifactBytes(`${raw}\n`, authorization),
    /not the canonical JSON representation/
  );
  const contentTamper = raw.replace("91.2500", "91.2501");
  assert.throws(
    () => verifyPublishedOfficialArtifactBytes(contentTamper, authorization),
    /digest/
  );
  for (const mutation of [
    { ...authorization, artifactId: "other-artifact" },
    { ...authorization, releaseApprovalDecisionId: "other-approval" },
    { ...authorization, policyVersion: "other-policy" },
    { ...authorization, contentSha256: "f".repeat(64) },
    { ...authorization, localOverride: true },
  ]) {
    assert.throws(
      () => verifyPublishedOfficialArtifactBytes(raw, mutation),
      OfficialArtifactValidationError
    );
  }

  for (const mutate of [
    (value) => {
      value.artifactId = "other-artifact";
    },
    (value) => {
      value.releaseApproval.decisionId = "other-approval";
    },
    (value) => {
      value.policyVersion = "other-policy";
    },
  ]) {
    const changed = structuredClone(artifact);
    mutate(changed);
    changed.manifest.contentSha256 = officialArtifactDigest(changed);
    assert.throws(
      () =>
        verifyPublishedOfficialArtifactBytes(
          canonicalOfficialArtifactJson(changed),
          authorization
        ),
      OfficialArtifactValidationError
    );
  }

  const mismatchedProvenance = structuredClone(artifact);
  mismatchedProvenance.scores[0].provenance.sourceUrl = "https://wrong.example.test/results";
  mismatchedProvenance.manifest.contentSha256 = officialArtifactDigest(mismatchedProvenance);
  assert.throws(
    () =>
      verifyPublishedOfficialArtifactBytes(
        canonicalOfficialArtifactJson(mismatchedProvenance),
        authorizationFor(mismatchedProvenance)
      ),
    /does not match its source manifest/
  );
});

test("the v2 CLI verifies supplied files without creating or authorizing them", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "official-release-verifier-"));
  try {
    const artifact = publishedArtifact();
    const artifactPath = path.join(directory, "artifact.json");
    const authorizationPath = path.join(directory, "authorization.json");
    await Promise.all([
      writeFile(artifactPath, canonicalOfficialArtifactJson(artifact), "utf8"),
      writeFile(authorizationPath, JSON.stringify(authorizationFor(artifact)), "utf8"),
    ]);

    assert.equal(
      (await verifyPublishedOfficialArtifactFiles(artifactPath, authorizationPath)).artifactId,
      artifact.artifactId
    );
    const result = await execFileAsync(
      process.execPath,
      [
        "scripts/verify-official-artifact.mjs",
        "--published-artifact",
        artifactPath,
        "--authorization",
        authorizationPath,
      ],
      { cwd: REPOSITORY_ROOT }
    );
    assert.match(result.stdout, /"availability":"published"/);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("candidate and legacy-report shapes cannot masquerade as a release artifact", async () => {
  const artifact = await trackedArtifact();
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

  for (const input of [candidate, legacyReport]) {
    assert.throws(
      () => validateOfficialReleaseArtifact(input),
      OfficialArtifactValidationError
    );
  }
  assert.throws(
    () => validateOfficialReleaseArtifact({ ...artifact, availability: "published" }),
    OfficialArtifactValidationError
  );
});

test("tampering, data-bearing unavailable artifacts, and missing provenance manifest are rejected", async () => {
  const artifact = await trackedArtifact();
  const tampered = structuredClone(artifact);
  tampered.reason = "tampered";
  assert.throws(() => validateOfficialReleaseArtifact(tampered), /digest/);

  const dataBearing = structuredClone(artifact);
  dataBearing.scores = [{ claimId: "not-allowed" }];
  dataBearing.manifest.contentSha256 = officialArtifactDigest(dataBearing);
  assert.throws(() => validateOfficialReleaseArtifact(dataBearing), /must not contain/);

  const missingManifest = structuredClone(artifact);
  delete missingManifest.sourceManifest;
  assert.throws(() => validateOfficialReleaseArtifact(missingManifest), /contract shape/);
});

test("the verifier CLI rejects incomplete candidate and output argument shapes", async () => {
  await assert.rejects(
    execFileAsync(process.execPath, ["scripts/verify-official-artifact.mjs", "--input", "candidate.json"], {
      cwd: REPOSITORY_ROOT,
    }),
    (error) => {
      assert.equal(error.code, 2);
      assert.match(error.stderr, /accepts either no arguments or --published-artifact/);
      return true;
    }
  );
});
