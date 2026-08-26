import test from "node:test";
import { verifyPagesWorkflows } from "./verify-pages-workflows.mjs";

test("Cloudflare Pages workflow candidates remain static and least-privilege", async () => {
  await verifyPagesWorkflows();
});
