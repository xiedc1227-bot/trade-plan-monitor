# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: production-restart.spec.ts >> installed production restart >> serves the packaged SPA and keeps typed availability across process restart
- Location: tests\e2e\production-restart.spec.ts:63:3

# Error details

```
Error: expect(received).toEqual(expected) // deep equality

- Expected  - 1
+ Received  + 3

- Array []
+ Array [
+   "error: Failed to load resource: net::ERR_CONNECTION_REFUSED",
+ ]
```

```
Error: EPERM, Permission denied: \\?\C:\Users\xiedc\AppData\Local\Temp\trade-plan-monitor-production-e2e-rSDS7N '\\?\C:\Users\xiedc\AppData\Local\Temp\trade-plan-monitor-production-e2e-rSDS7N'
```

# Test source

```ts
  1   | import {
  2   |   execFileSync,
  3   |   spawn,
  4   |   type ChildProcessWithoutNullStreams,
  5   | } from "node:child_process";
  6   | import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
  7   | import { createServer } from "node:net";
  8   | import { tmpdir } from "node:os";
  9   | import { join, resolve } from "node:path";
  10  | import { setTimeout as delay } from "node:timers/promises";
  11  | 
  12  | import { expect, test } from "@playwright/test";
  13  | 
  14  | const READY_TIMEOUT_MS = 20_000;
  15  | const PROCESS_TOOL_TIMEOUT_MS = 3_000;
  16  | const MAX_DIAGNOSTIC_CHARACTERS = 20_000;
  17  | 
  18  | interface InstalledServer {
  19  |   launcher: ChildProcessWithoutNullStreams;
  20  |   serverProcessId: number;
  21  | }
  22  | 
  23  | let server: InstalledServer | null = null;
  24  | let stateDirectory = "";
  25  | let configPath = "";
  26  | let diagnostics = "";
  27  | let port = 0;
  28  | let baseUrl = "";
  29  | 
  30  | test.describe("installed production restart", () => {
  31  |   test.describe.configure({ mode: "serial", timeout: 60_000 });
  32  | 
  33  |   test.beforeAll(async () => {
  34  |     port = await allocateLoopbackPort();
  35  |     baseUrl = `http://127.0.0.1:${port}`;
  36  |     stateDirectory = mkdtempSync(join(tmpdir(), "trade-plan-monitor-production-e2e-"));
  37  |     configPath = join(stateDirectory, "app.yaml");
  38  |     writeFileSync(configPath, "{}\n", { encoding: "utf8" });
  39  |     server = await startInstalledServer();
  40  |   });
  41  | 
  42  |   test.afterAll(async () => {
  43  |     let stopError: unknown;
  44  |     try {
  45  |       await stopInstalledServer();
  46  |     } catch (error) {
  47  |       stopError = error;
  48  |     }
  49  |     if (server === null && stateDirectory.startsWith(tmpdir())) {
  50  |       resetWindowsCursorKeyAcl();
> 51  |       rmSync(stateDirectory, {
      |       ^ Error: EPERM, Permission denied: \\?\C:\Users\xiedc\AppData\Local\Temp\trade-plan-monitor-production-e2e-rSDS7N '\\?\C:\Users\xiedc\AppData\Local\Temp\trade-plan-monitor-production-e2e-rSDS7N'
  52  |         force: true,
  53  |         maxRetries: 10,
  54  |         recursive: true,
  55  |         retryDelay: 100,
  56  |       });
  57  |     }
  58  |     if (stopError !== undefined) {
  59  |       throw stopError;
  60  |     }
  61  |   });
  62  | 
  63  |   test("serves the packaged SPA and keeps typed availability across process restart", async ({
  64  |     page,
  65  |   }) => {
  66  |     const browserConsoleFailures: string[] = [];
  67  |     const requestFailures: string[] = [];
  68  |     page.on("console", (message) => {
  69  |       if (message.type() === "error" || message.type() === "warning") {
  70  |         browserConsoleFailures.push(`${message.type()}: ${message.text()}`);
  71  |       }
  72  |     });
  73  |     page.on("requestfailed", (request) => {
  74  |       requestFailures.push(`${request.method()} ${request.url()}`);
  75  |     });
  76  | 
  77  |     const first = await page.request.get(`${baseUrl}/api/v1/dashboard`);
  78  |     expect(first.status()).toBe(200);
  79  |     expect(await first.json()).toMatchObject({
  80  |       availability: "UNAVAILABLE",
  81  |       reason: "EMPTY_DATABASE",
  82  |       sequence: 0,
  83  |     });
  84  | 
  85  |     await page.goto(baseUrl);
  86  |     await expect(page.getByRole("heading", { name: "监控总览" })).toBeVisible();
  87  |     await expect(page.getByText(/EMPTY_DATABASE/)).toBeVisible();
  88  |     expect(existsSync(join(stateDirectory, "data", "monitor.sqlite3"))).toBe(true);
  89  | 
  90  |     await stopInstalledServer();
  91  |     server = await startInstalledServer();
  92  | 
  93  |     await page.reload();
  94  |     await expect(page.getByRole("heading", { name: "监控总览" })).toBeVisible();
  95  |     await expect(page.getByText(/EMPTY_DATABASE/)).toBeVisible();
  96  |     const restarted = await page.request.get(`${baseUrl}/api/v1/dashboard`);
  97  |     expect(await restarted.json()).toMatchObject({
  98  |       availability: "UNAVAILABLE",
  99  |       reason: "EMPTY_DATABASE",
  100 |       sequence: 0,
  101 |     });
  102 |     expect(browserConsoleFailures).toEqual([]);
  103 |     expect(requestFailures).toEqual([]);
  104 |   });
  105 | });
  106 | 
  107 | async function startInstalledServer(): Promise<InstalledServer> {
  108 |   diagnostics = "";
  109 |   const executable = resolve(process.cwd(), "..", ".venv", "Scripts", "trade-plan-monitor.exe");
  110 |   if (!existsSync(executable)) {
  111 |     throw new Error("installed trade-plan-monitor console entry is unavailable");
  112 |   }
  113 |   const environment = { ...process.env };
  114 |   delete environment.TRADE_PLAN_MONITOR_ALLOW_TUSHARE_LIVE;
  115 |   delete environment.TRADE_PLAN_MONITOR_TUSHARE_LIVE_CHILD;
  116 |   const child = spawn(
  117 |     executable,
  118 |     ["web", "--config", configPath, "--host", "127.0.0.1", "--port", String(port)],
  119 |     {
  120 |       cwd: stateDirectory,
  121 |       env: environment,
  122 |       windowsHide: true,
  123 |     },
  124 |   );
  125 |   child.stdout.setEncoding("utf8");
  126 |   child.stderr.setEncoding("utf8");
  127 |   child.stdout.on("data", appendDiagnostic);
  128 |   child.stderr.on("data", appendDiagnostic);
  129 | 
  130 |   try {
  131 |     const deadline = Date.now() + READY_TIMEOUT_MS;
  132 |     while (Date.now() < deadline) {
  133 |       if (child.exitCode !== null) {
  134 |         throw new Error(`installed server exited before readiness: ${diagnostics}`);
  135 |       }
  136 |       const serverProcessId = tryParseUvicornProcessId();
  137 |       if (serverProcessId !== null) {
  138 |         try {
  139 |           const response = await fetch(`${baseUrl}/api/v1/health`);
  140 |           if (response.ok && child.exitCode === null) {
  141 |             return { launcher: child, serverProcessId };
  142 |           }
  143 |         } catch {
  144 |           // The test-owned loopback listener is not ready yet.
  145 |         }
  146 |       }
  147 |       await delay(100);
  148 |     }
  149 |     throw new Error(`installed server readiness timed out: ${diagnostics}`);
  150 |   } catch (error) {
  151 |     const serverProcessId = tryParseUvicornProcessId();
```