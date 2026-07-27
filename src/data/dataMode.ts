export type DataMode = "demo" | "official";

export const DATA_MODE_LABEL: Record<DataMode, string> = {
  demo: "Awaiting data",
  official: "Official claims",
};

export const DATA_MODE_TRUST_NOTE =
  "Benchmark data will appear once official source captures are published. The platform does not display synthetic or placeholder data.";
