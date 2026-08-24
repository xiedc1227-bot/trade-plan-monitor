/// <reference types="vitest/config" />

import { cpSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig, type Plugin } from "vite";

const webDistribution = fileURLToPath(new URL("./dist", import.meta.url));
const pythonDistribution = fileURLToPath(
  new URL("../src/trade_plan_monitor/web/dist", import.meta.url),
);

function packagePythonDistribution(): Plugin {
  return {
    name: "package-python-web-distribution",
    apply: "build",
    closeBundle() {
      rmSync(pythonDistribution, { recursive: true, force: true });
      cpSync(webDistribution, pythonDistribution, { recursive: true });
    },
  };
}

export default defineConfig({
  plugins: [vue(), packagePythonDistribution()],
  test: {
    environment: "jsdom",
    include: ["tests/unit/**/*.spec.ts"],
    clearMocks: true,
    restoreMocks: true,
  },
});
