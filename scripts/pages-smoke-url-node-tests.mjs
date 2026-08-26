import assert from "node:assert/strict";
import test from "node:test";
import { parsePagesSmokeUrl } from "./pages-smoke-url.mjs";

test("Pages smoke URL parser accepts only approved HTTPS origins", () => {
  assert.equal(parsePagesSmokeUrl("https://benchmark.0x3.dev"), "https://benchmark.0x3.dev");
  assert.equal(parsePagesSmokeUrl("https://preview.branch.pages.dev/"), "https://preview.branch.pages.dev");
});

for (const invalidUrl of [
  "http://benchmark.0x3.dev",
  "https://user@benchmark.0x3.dev",
  "https://benchmark.0x3.dev:8443",
  "https://benchmark.0x3.dev:443",
  "https://benchmark.0x3.dev/path",
  "https://benchmark.0x3.dev/.",
  "https://benchmark.0x3.dev/?query=1",
  "https://benchmark.0x3.dev/#fragment",
  "https://benchmark.0x3.dev.evil.example",
  "https://pages.dev",
]) {
  test(`Pages smoke URL parser rejects ${invalidUrl}`, () => {
    assert.throws(() => parsePagesSmokeUrl(invalidUrl));
  });
}
