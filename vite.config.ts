import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  build: {
    // Emit .vite/manifest.json so the bundle-budget gate can distinguish the
    // eager (isEntry + static `imports` closure) JS from deferred
    // (dynamicImports) chunks using the authoritative module graph — an
    // HTML-script-tag-only eager count can miss a statically-imported shared
    // chunk that Vite hoists out of the entry.
    manifest: true,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
      "@/registry": path.resolve(__dirname, "./src/components/evilcharts"),
    },
  },
});
