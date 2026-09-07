import {
  execFileSync,
  spawn,
  type ChildProcessWithoutNullStreams,
} from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
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
    if (server === null && stateDirectory.startsWith(tmpdir())) {
      resetWindowsCursorKeyAcl();
      rmSync(stateDirectory, {
        force: true,
        maxRetries: 10,
        recursive: true,
        retryDelay: 100,
      });
    }
    if (stopError !== undefined) {
      throw stopError;
    }
  });

  test("serves the packaged SPA and keeps typed availability across process restart", async ({
    page,
  }) => {
    const browserConsoleFailures: string[] = [];
    const requestFailures: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error" || message.type() === "warning") {
        browserConsoleFailures.push(`${message.type()}: ${message.text()}`);
      }
    });
    page.on("requestfailed", (request) => {
      requestFailures.push(`${request.method()} ${request.url()}`);
    });

    const first = await page.request.get(`${baseUrl}/api/v1/dashboard`);
    expect(first.status()).toBe(200);
    expect(await first.json()).toMatchObject({
      availability: "UNAVAILABLE",
      reason: "EMPTY_DATABASE",
      sequence: 0,
    });

    await page.goto(baseUrl);
    await expect(page.getByRole("heading", { name: "监控总览" })).toBeVisible();
    await expect(page.getByText(/EMPTY_DATABASE/)).toBeVisible();
    expect(existsSync(join(stateDirectory, "data", "monitor.sqlite3"))).toBe(true);

    await stopInstalledServer();
    server = await startInstalledServer();

    await page.reload();
    await expect(page.getByRole("heading", { name: "监控总览" })).toBeVisible();
    await expect(page.getByText(/EMPTY_DATABASE/)).toBeVisible();
    const restarted = await page.request.get(`${baseUrl}/api/v1/dashboard`);
    expect(await restarted.json()).toMatchObject({
      availability: "UNAVAILABLE",
      reason: "EMPTY_DATABASE",
      sequence: 0,
    });
    expect(browserConsoleFailures).toEqual([]);
    expect(requestFailures).toEqual([]);
  });
});

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
          const response = await fetch(`${baseUrl}/api/v1/health`);
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

function resetWindowsCursorKeyAcl(): void {
  const cursorKey = join(stateDirectory, "data", "backtest-cursor.key");
  if (process.platform !== "win32" || !existsSync(cursorKey)) {
    return;
  }
  execFileSync("icacls.exe", [cursorKey, "/reset"], {
    stdio: "ignore",
    timeout: PROCESS_TOOL_TIMEOUT_MS,
  });
}
