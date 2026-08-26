export type DataMode = "demo" | "official";

export const DATA_MODE_LABEL: Record<DataMode, string> = {
  demo: "Demo (synthetic)",
  official: "Official claims",
};

export const DATA_MODE_TRUST_NOTE =
  "Official claims are unavailable. Synthetic Demo data remains visible until a governed Official release is published.";
