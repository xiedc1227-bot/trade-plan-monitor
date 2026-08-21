/// <reference types="vitest/config" />

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  build: {
    lib: {
      entry: "src/main.ts",
      formats: ["es"],
      name: "TradePlanMonitor",
      fileName: "trade-plan-monitor",
    },
    rolldownOptions: {
      external: ["vue"],
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.spec.ts"],
    clearMocks: true,
    restoreMocks: true,
  },
});

