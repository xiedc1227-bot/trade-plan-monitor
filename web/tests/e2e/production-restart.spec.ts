import {
  execFileSync,
  spawn,
  type ChildProcessWithoutNullStreams,
} from "node:child_process";
import { existsSync, lstatSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

import { expect, test } from "@playwright/test";

const READY_TIMEOUT_MS = 20_000;
const PROCESS_TOOL_TIMEOUT_MS = 3_000;
const MAX_DIAGNOSTIC_CHARACTERS = 20_000;

interface InstalledServer {
  launcher: ChildProcessWithoutNullStreams;
  serverProcessId: number;
}

let server: InstalledServer | null = null;
let stateDirectory = "";
let ownedStateDirectory = "";
let configPath = "";
let diagnostics = "";
let port = 0;
let baseUrl = "";

test.describe("installed production restart", () => {
  test.describe.configure({ mode: "serial", timeout: 60_000 });

  test.beforeAll(async () => {
    port = await allocateLoopbackPort();
    baseUrl = `http://127.0.0.1:${port}`;
    stateDirectory = mkdtempSync(join(tmpdir(), "trade-plan-monitor-production-e2e-"));
    ownedStateDirectory = realpathSync(stateDirectory);
    configPath = join(stateDirectory, "app.yaml");
    writeFileSync(configPath, "{}\n", { encoding: "utf8" });
    server = await startInstalledServer();
  });

  test.afterAll(async () => {
    let stopError: unknown;
    try {
      await stopInstalledServer();
    } catch (error) {
      stopError = error;
    }
    if (server === null && ownedStateDirectory !== "") {
      requireOwnedStateDirectory();
      prepareTestCursorKeysForCleanup();
      rmSync(stateDirectory, {
        force: true,
        maxRetries: 10,
        recursive: true,
        retryDelay: 100,
      });
      expect(existsSync(stateDirectory), "test-owned state directory cleanup").toBe(false);
      console.log("installed restart cleanup: test-owned state directory removed");
    }
    if (stopError !== undefined) {
      throw stopError;
    }
  });

  test("serves the packaged SPA and keeps typed availability across process restart", async ({
    context,
    request,
  }) => {
    const beforeRestart = await context.newPage();
    const beforeAudit = auditPage(beforeRestart);

    const headers = { "X-Monitor-Contract-Version": "2" };
    expect((await request.get(`${baseUrl}/api/v1/health`)).status()).toBe(409);
    const first = await request.get(`${baseUrl}/api/v1/dashboard`, { headers });
    expect(first.status()).toBe(200);
    expect(await first.json()).toMatchObject({
      monitorContractVersion: 2,
      runtimeStatus: { lifecycle: "RUNNING", mode: "BLOCKED" },
      symbols: [],
      sequence: 0,
    });
    const firstGeneration = (await first.json()).runtimeGeneration;
    expect(firstGeneration).toMatch(/^[0-9a-f-]{36}$/);

    await beforeRestart.goto(baseUrl);
    await expect(beforeRestart.getByRole("heading", { name: "监控总览" })).toBeVisible();
    await expect(beforeRestart.getByText("没有活动计划。可前往计划工作台核对并启用计划。")).toBeVisible();
    expect(existsSync(join(stateDirectory, "data", "monitor.sqlite3"))).toBe(true);
    await beforeRestart.close();
    expect(beforeAudit.consoleFailures).toEqual([]);
    expect(beforeAudit.requestFailures).toEqual([]);
    console.log("installed restart before stop: browser console=0, failed requests=0");

    await stopInstalledServer();
    const offlineError: unknown = await fetch(`${baseUrl}/api/v1/health`).then(
      () => null,
      (error: unknown) => error,
    );
    expect(offlineError).toBeInstanceOf(TypeError);
    expect((offlineError as { cause?: NodeJS.ErrnoException }).cause?.code).toBe("ECONNREFUSED");
    console.log("installed restart intentional offline probe: ECONNREFUSED");
    server = await startInstalledServer();

    const afterRestart = await context.newPage();
    const afterAudit = auditPage(afterRestart);
    await afterRestart.goto(baseUrl);
    await expect(afterRestart.getByRole("heading", { name: "监控总览" })).toBeVisible();
    await expect(afterRestart.getByText("没有活动计划。可前往计划工作台核对并启用计划。")).toBeVisible();
    const restarted = await request.get(`${baseUrl}/api/v1/dashboard`, { headers });
    expect(restarted.status()).toBe(200);
    expect(await restarted.json()).toMatchObject({
      monitorContractVersion: 2,
      runtimeStatus: { lifecycle: "RUNNING", mode: "BLOCKED" },
      symbols: [],
      sequence: 0,
    });
    expect((await restarted.json()).runtimeGeneration).not.toBe(firstGeneration);
    await afterRestart.close();
    expect(afterAudit.consoleFailures).toEqual([]);
    expect(afterAudit.requestFailures).toEqual([]);
    console.log("installed restart after recovery: browser console=0, failed requests=0");
  });
});

interface PageAudit {
  consoleFailures: string[];
  requestFailures: string[];
}

function auditPage(page: import("@playwright/test").Page): PageAudit {
  const audit: PageAudit = { consoleFailures: [], requestFailures: [] };
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      audit.consoleFailures.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on("requestfailed", (request) => {
    audit.requestFailures.push(`${request.method()} ${request.url()} (${request.failure()?.errorText ?? "unknown"})`);
  });
  return audit;
}

async function startInstalledServer(): Promise<InstalledServer> {
  diagnostics = "";
  const executable = resolve(process.cwd(), "..", ".venv", "Scripts", "trade-plan-monitor.exe");
  if (!existsSync(executable)) {
    throw new Error("installed trade-plan-monitor console entry is unavailable");
  }
  const environment = { ...process.env };
  delete environment.TRADE_PLAN_MONITOR_ALLOW_TUSHARE_LIVE;
  delete environment.TRADE_PLAN_MONITOR_TUSHARE_LIVE_CHILD;
  const child = spawn(
    executable,
    ["web", "--config", configPath, "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: stateDirectory,
      env: environment,
      windowsHide: true,
    },
  );
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", appendDiagnostic);
  child.stderr.on("data", appendDiagnostic);

  try {
    const deadline = Date.now() + READY_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (child.exitCode !== null) {
        throw new Error(`installed server exited before readiness: ${diagnostics}`);
      }
      const serverProcessId = tryParseUvicornProcessId();
      if (serverProcessId !== null) {
        try {
          const response = await fetch(`${baseUrl}/api/v1/health`, {
            headers: { "X-Monitor-Contract-Version": "2" },
          });
          if (response.ok && child.exitCode === null) {
            return { launcher: child, serverProcessId };
          }
        } catch {
          // The test-owned loopback listener is not ready yet.
        }
      }
      await delay(100);
    }
    throw new Error(`installed server readiness timed out: ${diagnostics}`);
  } catch (error) {
    const serverProcessId = tryParseUvicornProcessId();
    await terminateInstalledProcess(child, serverProcessId);
    throw error;
  }
}

async function stopInstalledServer(): Promise<void> {
  const owned = server;
  if (owned === null) {
    return;
  }
  try {
    await terminateInstalledProcess(owned.launcher, owned.serverProcessId);
  } catch (error) {
    if (installedProcessExited(owned.launcher, owned.serverProcessId)) {
      server = null;
    }
    throw error;
  }
  server = null;
}

function appendDiagnostic(chunk: string): void {
  diagnostics = `${diagnostics}${chunk}`.slice(-MAX_DIAGNOSTIC_CHARACTERS);
}

function tryParseUvicornProcessId(): number | null {
  const match = /Started server process \[(\d+)\]/u.exec(diagnostics);
  return match?.[1] === undefined ? null : Number(match[1]);
}

async function terminateInstalledProcess(
  launcher: ChildProcessWithoutNullStreams,
  serverProcessId: number | null,
): Promise<void> {
  if (serverProcessId !== null && isProcessAlive(serverProcessId)) {
    signalProcess(serverProcessId, "SIGTERM");
  } else if (launcher.exitCode === null) {
    launcher.kill("SIGTERM");
  }
  if (await waitForInstalledProcessExit(launcher, serverProcessId, 5_000)) {
    return;
  }

  forceTerminateProcessTree(launcher, serverProcessId);
  if (await waitForInstalledProcessExit(launcher, serverProcessId, 5_000)) {
    return;
  }
  throw new Error(`installed server did not stop: ${diagnostics}`);
}

function forceTerminateProcessTree(
  launcher: ChildProcessWithoutNullStreams,
  serverProcessId: number | null,
): void {
  if (process.platform === "win32" && launcher.pid !== undefined) {
    try {
      execFileSync(
        "taskkill.exe",
        ["/PID", String(launcher.pid), "/T", "/F"],
        { stdio: "ignore", timeout: PROCESS_TOOL_TIMEOUT_MS },
      );
    } catch {
      // Fall through to exact test-owned PID termination.
    }
  }
  if (serverProcessId !== null && isProcessAlive(serverProcessId)) {
    signalProcess(serverProcessId, "SIGKILL");
  }
  if (launcher.exitCode === null) {
    launcher.kill("SIGKILL");
  }
}

function signalProcess(processId: number, signal: NodeJS.Signals): void {
  try {
    process.kill(processId, signal);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ESRCH") {
      throw error;
    }
  }
}

function isProcessAlive(processId: number): boolean {
  try {
    process.kill(processId, 0);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") {
      return false;
    }
    throw error;
  }
}

function installedProcessExited(
  launcher: ChildProcessWithoutNullStreams,
  serverProcessId: number | null,
): boolean {
  return (
    launcher.exitCode !== null &&
    (serverProcessId === null || !isProcessAlive(serverProcessId))
  );
}

async function waitForInstalledProcessExit(
  launcher: ChildProcessWithoutNullStreams,
  serverProcessId: number | null,
  timeoutMs: number,
): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (installedProcessExited(launcher, serverProcessId)) {
      return true;
    }
    await delay(50);
  }
  return installedProcessExited(launcher, serverProcessId);
}

async function allocateLoopbackPort(): Promise<number> {
  const reservation = createServer();
  await new Promise<void>((resolveListen, rejectListen) => {
    reservation.once("error", rejectListen);
    reservation.listen({ exclusive: true, host: "127.0.0.1", port: 0 }, resolveListen);
  });
  const address = reservation.address();
  await new Promise<void>((resolveClose, rejectClose) => {
    reservation.close((error) => {
      if (error === undefined) resolveClose();
      else rejectClose(error);
    });
  });
  if (address === null || typeof address === "string") {
    throw new Error("loopback port reservation did not return a TCP address");
  }
  return address.port;
}

function requireOwnedStateDirectory(): void {
  const resolved = resolve(stateDirectory);
  const temporaryRoot = realpathSync(tmpdir());
  if (
    resolved !== ownedStateDirectory ||
    dirname(ownedStateDirectory).toLowerCase() !== temporaryRoot.toLowerCase() ||
    !/^trade-plan-monitor-production-e2e-[A-Za-z0-9]{6}$/u.test(basename(ownedStateDirectory)) ||
    realpathSync(stateDirectory) !== ownedStateDirectory ||
    !lstatSync(stateDirectory).isDirectory() ||
    lstatSync(stateDirectory).isSymbolicLink()
  ) {
    throw new Error("refusing cleanup outside the owned production test directory");
  }
  const dataDirectory = join(stateDirectory, "data");
  if (existsSync(dataDirectory) && (
    !lstatSync(dataDirectory).isDirectory() ||
    lstatSync(dataDirectory).isSymbolicLink() ||
    realpathSync(dataDirectory) !== resolve(dataDirectory)
  )) {
    throw new Error("refusing cleanup through a substituted test data directory");
  }
}

function prepareTestCursorKeysForCleanup(): void {
  if (process.platform !== "win32") {
    return;
  }
  for (const name of ["monitor.cursor.key", "backtest-cursor.key"]) {
    const cursorKey = join(stateDirectory, "data", name);
    if (!existsSync(cursorKey)) continue;
    if (
      dirname(resolve(cursorKey)) !== resolve(stateDirectory, "data") ||
      !lstatSync(cursorKey).isFile() ||
      lstatSync(cursorKey).isSymbolicLink() ||
      realpathSync(cursorKey) !== resolve(cursorKey)
    ) {
      throw new Error(`refusing ACL change outside the test-generated ${name}`);
    }
    execFileSync("icacls.exe", [cursorKey, "/reset"], {
      stdio: "ignore",
      timeout: PROCESS_TOOL_TIMEOUT_MS,
    });
  }
}
