// @vitest-environment node
import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { build, loadConfigFromFile, type Plugin } from "vite";
import { expect, it } from "vitest";

async function directoryDigest(root: string): Promise<string> {
  const entries = await readdir(root, { recursive: true, withFileTypes: true });
  const hash = createHash("sha256");
  for (const entry of entries.filter((item) => item.isFile()).sort((a, b) => join(a.parentPath, a.name).localeCompare(join(b.parentPath, b.name)))) {
    hash.update(join(entry.parentPath, entry.name).slice(root.length));
    hash.update(await readFile(join(entry.parentPath, entry.name)));
  }
  return hash.digest("hex");
}

it("builds isolated v2 index/manifest/hashed assets without rewriting installed assets", async () => {
  const destination = await mkdtemp(join(tmpdir(), "tpm-runtime-status-build-"));
  const installed = resolve("../src/trade_plan_monitor/web/dist");
  const before = await directoryDigest(installed);
  try {
    await build({ configFile: resolve("vite.runtime-status.config.ts"), logLevel: "silent", build: { outDir: destination } });
    expect(JSON.parse(await readFile(join(destination, "monitor-contract.json"), "utf8"))).toEqual({ monitorContractVersion: 2 });
    const html = await readFile(join(destination, "index.html"), "utf8");
    expect(html).toContain("监控协议 2 离线预览");
    expect(html).toMatch(/\/assets\/[^" ]+-[\w-]+\.js/);
    expect(await readdir(destination)).not.toContain("runtime-status-preview.html");
    expect(await directoryDigest(installed)).toBe(before);
    const manifest = JSON.parse(await readFile("package.json", "utf8")) as { scripts: Record<string, string> };
    expect(manifest.scripts["build:runtime-status-preview"]).toBe("vite build --config vite.runtime-status.config.ts");
    expect(manifest.scripts.build).toBe("vite build");
  } finally {
    await rm(destination, { recursive: true, force: true });
  }
}, 20_000);

it("builds explicit v1 fixture assets without changing the installed v2 distribution", async () => {
  const destination = await mkdtemp(join(tmpdir(), "tpm-legacy-test-build-"));
  const installed = resolve("../src/trade_plan_monitor/web/dist");
  const before = await directoryDigest(installed);
  try {
    await build({ configFile: resolve("vite.legacy-test.config.ts"), logLevel: "silent", build: { outDir: destination } });
    expect(JSON.parse(await readFile(join(destination, "monitor-contract.json"), "utf8"))).toEqual({ monitorContractVersion: 1 });
    const html = await readFile(join(destination, "index.html"), "utf8");
    expect(html).toMatch(/\/assets\/[^" ]+-[\w-]+\.js/);
    expect(html).not.toContain("离线预览");
    expect(await directoryDigest(installed)).toBe(before);
  } finally {
    await rm(destination, { recursive: true, force: true });
  }
}, 20_000);

it("selects the installed v2 entry and declares version 2 in the normal build", async () => {
  const config = await loadConfigFromFile({ command: "build", mode: "production" }, resolve("vite.config.ts"));
  const manifestPlugin = config?.config.plugins?.flat().find((plugin) => plugin && typeof plugin === "object" && "name" in plugin && plugin.name === "monitor-contract-v2") as Plugin | undefined;
  expect(manifestPlugin).toBeDefined();
  const source = await readFile("index.html", "utf8");
  expect(source).toContain('src="/src/runtime-status/main.ts"');
  expect(source).not.toContain('src="/src/main.ts"');
  const destination = await mkdtemp(join(tmpdir(), "tpm-installed-manifest-build-"));
  try {
    const input = join(destination, "fixture.html");
    await writeFile(input, '<!doctype html><title>Manifest fixture</title>');
    await build({ root: destination, configFile: false, plugins: [manifestPlugin!], publicDir: false, logLevel: "silent",
      build: { outDir: join(destination, "out"), rollupOptions: { input } } });
    expect(JSON.parse(await readFile(join(destination, "out", "monitor-contract.json"), "utf8"))).toEqual({ monitorContractVersion: 2 });
  } finally {
    await rm(destination, { recursive: true, force: true });
  }
}, 20_000);
