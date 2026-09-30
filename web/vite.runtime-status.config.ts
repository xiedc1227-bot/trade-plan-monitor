import { fileURLToPath } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig, type Plugin } from "vite";

function previewContract(): Plugin {
  return {
    name: "runtime-status-preview-contract",
    apply: "build",
    generateBundle: {
      order: "post",
      handler(_options, bundle) {
        const entry = bundle["runtime-status-preview.html"];
        if (entry === undefined || entry.type !== "asset") throw new Error("Missing runtime-status preview entry");
        this.emitFile({ type: "asset", fileName: "index.html", source: entry.source });
        delete bundle["runtime-status-preview.html"];
        this.emitFile({ type: "asset", fileName: "monitor-contract.json", source: '{"monitorContractVersion":2}\n' });
      },
    },
  };
}

// Deliberately independent from vite.config.ts and its installed-asset copy hook.
export default defineConfig({
  plugins: [vue(), previewContract()],
  publicDir: false,
  build: {
    outDir: fileURLToPath(new URL("./dist-runtime-status", import.meta.url)),
    rollupOptions: {
      input: fileURLToPath(new URL("./runtime-status-preview.html", import.meta.url)),
    },
  },
});
