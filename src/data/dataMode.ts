export type DataMode = "demo" | "official";

export const DATA_MODE_LABEL: Record<DataMode, string> = {
  demo: "Demo (synthetic)",
  official: "Official claims",
};

export const DATA_MODE_TRUST_NOTE =
  "Leaderboard rankings and category averages are presentation-only. Official publication stays unavailable until a governed release artifact is approved; it never falls back to demo or sample data.";
