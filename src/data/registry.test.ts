import { afterEach, describe, expect, it } from "vitest";
import { loadOfficialData } from "./official";
import { setActiveData, getValue, getScoreEntry } from "./registry";
import { models as demoModels } from "./models";
import { benchmarks as demoBenchmarks } from "./benchmarks";
import { getScores } from "./scores";
const demoScores = getScores();

// Registry holds module-level state; reset to the demo dataset after every test
// so mutations never leak across tests.
function resetDemo() {
  setActiveData({
    models: demoModels,
    benchmarks: demoBenchmarks,
    scores: demoScores,
  });
}

describe("loadOfficialData", () => {
  it("maps the ledger export to app types with provenance preserved", () => {
    const off = loadOfficialData();
    // Real export now carries many source-backed models/benchmarks/scores.
    expect(off.models.length).toBeGreaterThan(1);
    expect(off.benchmarks.length).toBeGreaterThan(1);
    expect(off.scores.length).toBeGreaterThan(1);

    // At least one score must carry provenance (source-backed claim).
    const provenanced = off.scores.find((s) => s.officialSourceId);
    expect(provenanced).toBeTruthy();
    expect(provenanced?.captureStatus).toBeTruthy();
    expect(provenanced?.claimId).toBeTruthy();

    // Unknown ledger category is bucketed safely (never crashes the layout).
    for (const b of off.benchmarks) {
      expect(["reasoning", "knowledge", "coding", "math", "agentic", "instruction", "chat", "vision", "embedding", "other", "unknown"]).toContain(b.category);
    }
  });
});

describe("registry dual-mode switching", () => {
  afterEach(resetDemo);

  it("getValue reads the active dataset and is the sole score path", () => {
    // Official mode: source-backed claim value (real export).
    const off = loadOfficialData();
    setActiveData({
      models: off.models,
      benchmarks: off.benchmarks,
      scores: off.scores,
    });
    // Pick a real score with provenance and verify it round-trips.
    const s = off.scores.find((x) => x.officialSourceId);
    expect(s).toBeTruthy();
    if (s) {
      expect(getValue(s.modelId, s.benchmarkId)).toBe(s.value);
      const entry = getScoreEntry(s.modelId, s.benchmarkId);
      expect(entry?.officialSourceId).toBe(s.officialSourceId);
    }

    // Missing cells render as no-data (null), not zero.
    expect(getValue("__no_such_model__", "__no_such_bench__")).toBeNull();
    expect(getScoreEntry("__no_such_model__", "__no_such_bench__")).toBeNull();

    // Switching back to demo: getValue reflects demo data and carries no
    // provenance (demo scores must not look like official claims).
    resetDemo();
    const demoVal = getValue("gpt-4o", "mmlu");
    expect(typeof demoVal).toBe("number");
    expect(demoVal).not.toBeNull();
    const demoEntry = getScoreEntry("gpt-4o", "mmlu");
    expect(demoEntry?.officialSourceId).toBeUndefined();
    expect(demoEntry?.scoreRaw).toBeUndefined();
  });
});
