/**
 * UI-only formatting for optional model metadata.  A null value means the
 * selected dataset did not make that fact available; it must never be
 * rendered as a numeric or boolean value.
 */
export const NOT_SUPPLIED = "Not supplied";

export function formatContextWindow(value: number | null): string {
  return value === null ? NOT_SUPPLIED : `${value}k`;
}

export function formatOpenWeights(value: boolean | null): string {
  if (value === null) return NOT_SUPPLIED;
  return value ? "yes" : "no";
}

export function formatPricePair(
  inputPrice: number | null,
  outputPrice: number | null
): string {
  const format = (value: number | null) => (value === null ? NOT_SUPPLIED : `$${value}`);
  return `in ${format(inputPrice)} / out ${format(outputPrice)}`;
}
