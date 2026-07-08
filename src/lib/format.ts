// Shared score formatting. Returns "—" for missing values, one decimal for
// /10 scales (e.g. MT-Bench), rounded integers for everything else.
export function fmtScore(value: number | null, scaleMax: number): string {
  if (value == null) return "—";
  return scaleMax === 10 ? value.toFixed(1) : Math.round(value).toString();
}
