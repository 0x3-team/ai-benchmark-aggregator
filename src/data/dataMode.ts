export type DataMode = "demo" | "official";

export const DATA_MODE_LABEL: Record<DataMode, string> = {
  demo: "Demo (synthetic)",
  official: "Official claims",
};

export const DATA_MODE_TRUST_NOTE =
  "Leaderboard rankings and category averages are presentation-only. Official mode shows source-backed claims from the benchmark ledger and does not recalculate scientific scores.";
