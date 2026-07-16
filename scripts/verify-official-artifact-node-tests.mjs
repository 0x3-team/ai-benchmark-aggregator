import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";
import test from "node:test";

import {
  OfficialArtifactValidationError,
  REPOSITORY_ROOT,
  TRACKED_OFFICIAL_ARTIFACT_PATH,
  canonicalOfficialArtifactJson,
  officialArtifactDigest,
  validateOfficialArtifactContractSchema,
  validateOfficialReleaseArtifact,
  verifyTrackedOfficialArtifactContract,
  verifyTrackedOfficialArtifact,
} from "./verify-official-artifact.mjs";

const execFileAsync = promisify(execFile);

async function trackedArtifact() {
  return JSON.parse(await readFile(TRACKED_OFFICIAL_ARTIFACT_PATH, "utf8"));
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

test("the containment CLI cannot be redirected to a local candidate or write an artifact", async () => {
  await assert.rejects(
    execFileAsync(process.execPath, ["scripts/verify-official-artifact.mjs", "--input", "candidate.json"], {
      cwd: REPOSITORY_ROOT,
    }),
    (error) => {
      assert.equal(error.code, 2);
      assert.match(error.stderr, /accepts no path or output arguments/);
      return true;
    }
  );
});
