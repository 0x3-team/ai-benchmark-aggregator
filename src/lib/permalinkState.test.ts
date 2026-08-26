import { describe, expect, it } from "vitest";
import {
  decodePermalink,
  DEFAULT_PERMALINK_STATE,
  encodePermalink,
  PERMALINK_MAX_COMPARE,
  type PermalinkState,
} from "./permalinkState";

const FULL_STATE: PermalinkState = {
  view: "compare",
  q: "hello world",
  vendor: ["OpenAI", "Anthropic"],
  category: "coding",
  open: true,
  sort: { benchmarkId: "bench-sort", dir: "asc" },
  compare: ["m1", "m2", "m3", "m4", "m5", "m6"],
  model: "model-sheet",
  benchmark: null,
  all: true,
  zero: true,
};

const FULL_STATE_BENCHMARK: PermalinkState = {
  ...FULL_STATE,
  model: null,
  benchmark: "benchmark-sheet",
};

describe("permalinkState codec", () => {
  it("round-trips a fully populated state", () => {
    const encoded = encodePermalink(FULL_STATE);
    const decoded = decodePermalink(encoded);
    expect(decoded).toEqual(FULL_STATE);
  });

  it("round-trips a state with the benchmark sheet open", () => {
    const encoded = encodePermalink(FULL_STATE_BENCHMARK);
    const decoded = decodePermalink(encoded);
    expect(decoded).toEqual(FULL_STATE_BENCHMARK);
  });

  it("round-trips the default state through encode/decode", () => {
    const encoded = encodePermalink(DEFAULT_PERMALINK_STATE);
    expect(encoded).toBe("?v=1");
    expect(decodePermalink(encoded)).toEqual(DEFAULT_PERMALINK_STATE);
  });

  it("emits a canonical, deterministic order and omits defaults", () => {
    const state: PermalinkState = {
      ...DEFAULT_PERMALINK_STATE,
      view: "table",
      q: "",
      category: null,
      open: false,
      sort: null,
      all: false,
      zero: false,
    };
    expect(encodePermalink(state)).toBe("?v=1");

    const active: PermalinkState = {
      view: "compare",
      q: "query here",
      vendor: ["A", "B"],
      category: "reasoning",
      open: true,
      sort: { benchmarkId: "sort-b", dir: "desc" },
      compare: ["x", "y"],
      model: "mod",
      benchmark: null,
      all: true,
      zero: true,
    };
    expect(encodePermalink(active)).toBe(
      "?v=1&view=compare&q=query%20here&vendor=A&vendor=B&category=reasoning&open=1&sort=sort-b&dir=desc&compare=x&compare=y&model=mod&all=1&zero=1"
    );
  });

  it("caps compare at six and preserves order while deduping", () => {
    const encoded =
      "?v=1&compare=a&compare=b&compare=a&compare=c&compare=d&compare=e&compare=f&compare=g&compare=h";
    const decoded = decodePermalink(encoded);
    expect(decoded.compare).toEqual(["a", "b", "c", "d", "e", "f"]);
  });

  it("dedupes repeated vendor while preserving first-occurrence order", () => {
    const encoded = "?v=1&vendor=z&vendor=y&vendor=z&vendor=x";
    const decoded = decodePermalink(encoded);
    expect(decoded.vendor).toEqual(["z", "y", "x"]);
  });

  it("fails closed on duplicate singleton parameters", () => {
    expect(decodePermalink("?v=1&view=table&view=compare")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
    expect(decodePermalink("?v=1&q=a&q=b")).toEqual(DEFAULT_PERMALINK_STATE);
    expect(decodePermalink("?v=1&sort=s1&sort=s2&dir=asc")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
    expect(decodePermalink("?v=1&dir=asc&dir=desc")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
    expect(decodePermalink("?v=1&model=m&model=m2")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
    expect(decodePermalink("?v=1&v=1&v=1")).toEqual(DEFAULT_PERMALINK_STATE);
  });

  it("fails closed on control characters and overlong input", () => {
    expect(decodePermalink("?v=1&q=%00")).toEqual(DEFAULT_PERMALINK_STATE);
    expect(decodePermalink("?v=1&compare=a%0Ab")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
    expect(decodePermalink("?v=1&unknown=%00")).toEqual(
      DEFAULT_PERMALINK_STATE
    );

    const longValue = "a".repeat(257);
    expect(decodePermalink(`?v=1&q=${longValue}`)).toEqual(
      DEFAULT_PERMALINK_STATE
    );

    const manyCompare = Array.from(
      { length: 100 },
      (_, i) => `compare=m${i}`
    ).join("&");
    expect(decodePermalink(`?v=1&${manyCompare}`).compare.length).toBe(
      PERMALINK_MAX_COMPARE
    );
  });

  it("fails closed on invalid percent input as URLSearchParams exposes it", () => {
    const malformed = new URLSearchParams("?sort=%&dir=asc");
    expect(decodePermalink(malformed)).toEqual(DEFAULT_PERMALINK_STATE);

    expect(decodePermalink("?v=1&sort=%&dir=asc")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
    expect(decodePermalink("?v=1&q=%ZZ")).toEqual(DEFAULT_PERMALINK_STATE);
    expect(decodePermalink("?v=1&model=%G0")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
  });

  it("fails closed on invalid enums and coupled sort", () => {
    expect(decodePermalink("?v=1&view=notaview")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
    expect(decodePermalink("?v=1&category=notacategory")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
    expect(decodePermalink("?v=1&sort=bench")).toEqual(DEFAULT_PERMALINK_STATE);
    expect(decodePermalink("?v=1&dir=asc")).toEqual(DEFAULT_PERMALINK_STATE);
    expect(decodePermalink("?v=1&sort=bench&dir=up")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
  });

  it("fails closed when both model and benchmark sheets are open", () => {
    expect(decodePermalink("?v=1&model=m&benchmark=b")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
  });

  it("resets to defaults for unknown versions and missing version", () => {
    expect(decodePermalink("?v=2&view=compare")).toEqual(
      DEFAULT_PERMALINK_STATE
    );
    expect(decodePermalink("?view=compare")).toEqual(DEFAULT_PERMALINK_STATE);
  });

  it("drops unknown parameters without failing", () => {
    const decoded = decodePermalink("?v=1&unknown=value&view=compare&foo=bar");
    expect(decoded).toEqual({
      ...DEFAULT_PERMALINK_STATE,
      view: "compare",
    });
  });

  it("treats an empty q as the default empty search", () => {
    const encoded = encodePermalink({ ...DEFAULT_PERMALINK_STATE, q: "" });
    expect(encoded).toBe("?v=1");
    expect(decodePermalink("?v=1&q=")).toEqual(DEFAULT_PERMALINK_STATE);
  });

  it("rejects malformed boolean values and accepts only 1", () => {
    expect(decodePermalink("?v=1&open=true")).toEqual(DEFAULT_PERMALINK_STATE);
    expect(decodePermalink("?v=1&open=0")).toEqual(DEFAULT_PERMALINK_STATE);
    expect(decodePermalink("?v=1&open=")).toEqual(DEFAULT_PERMALINK_STATE);
    expect(decodePermalink("?v=1&all=1&zero=1")).toEqual({
      ...DEFAULT_PERMALINK_STATE,
      all: true,
      zero: true,
    });
  });

  it("preserves the search query when it contains an encoded percent sign", () => {
    const state = { ...DEFAULT_PERMALINK_STATE, q: "50% off" };
    const encoded = encodePermalink(state);
    expect(encoded).toBe("?v=1&q=50%25%20off");
    expect(decodePermalink(encoded)).toEqual(state);
  });
});
