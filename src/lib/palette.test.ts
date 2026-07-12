import { describe, expect, it } from "vitest";
import { MODEL_PALETTE, modelColor } from "./palette";

describe("modelColor", () => {
  it("cycles through MODEL_PALETTE", () => {
    expect(modelColor(0)).toBe(MODEL_PALETTE[0]);
    expect(modelColor(MODEL_PALETTE.length)).toBe(MODEL_PALETTE[0]);
    expect(modelColor(1)).toBe(MODEL_PALETTE[1]);
  });
});
