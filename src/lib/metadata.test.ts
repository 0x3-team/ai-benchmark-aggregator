import { describe, expect, it } from "vitest";
import {
  formatContextWindow,
  formatOpenWeights,
  formatPricePair,
} from "./metadata";

describe("metadata display formatting", () => {
  it("labels unknown metadata without inventing a factual value", () => {
    expect(formatContextWindow(null)).toBe("Not supplied");
    expect(formatOpenWeights(null)).toBe("Not supplied");
    expect(formatPricePair(null, 2)).toBe("in Not supplied / out $2");
  });

  it("preserves known zero-like and boolean metadata values", () => {
    expect(formatContextWindow(0)).toBe("0k");
    expect(formatOpenWeights(false)).toBe("no");
    expect(formatPricePair(0, 0)).toBe("in $0 / out $0");
  });
});
