import { fileURLToPath } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// Explicit compatibility fixtures retain their v1 UI and wire schemas. This
// configuration neither packages assets nor changes the installed v2 entry.
export default defineConfig({
  plugins: [vue(), {
    name: "legacy-test-contract",
    transformIndexHtml: {
      order: "pre",
      handler(html) {
        const installedEntry = 'src="/src/runtime-status/main.ts"';
        if (!html.includes(installedEntry)) throw new Error("Missing installed v2 entry");
        return html.replace(installedEntry, 'src="/src/main.ts"');
      },
    },
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "monitor-contract.json", source: '{"monitorContractVersion":1}\n' });
    },
  }],
  build: { outDir: fileURLToPath(new URL("./dist-legacy-test", import.meta.url)) },
});
