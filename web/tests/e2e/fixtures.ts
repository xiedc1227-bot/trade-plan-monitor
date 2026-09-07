import { expect, test as base } from "@playwright/test";
import type { Page } from "@playwright/test";

type BrowserAudit = {
  consoleFailures: string[];
  failedRequests: string[];
};

function attachAudit(page: Page, audit: BrowserAudit): void {
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") {
      audit.consoleFailures.push(
        `${message.type()}: ${message.text()} @ ${message.location().url}`,
      );
    }
  });
  page.on("requestfailed", (request) => {
    audit.failedRequests.push(
      `${request.method()} ${request.url()} (${request.failure()?.errorText ?? "unknown"})`,
    );
  });
}

export const test = base.extend<{ browserAudit: void }>({
  browserAudit: [
    async ({ context }, use) => {
      const audit: BrowserAudit = { consoleFailures: [], failedRequests: [] };
      for (const page of context.pages()) {
        attachAudit(page, audit);
      }
      context.on("page", (page) => attachAudit(page, audit));

      await use();

      expect(audit.consoleFailures, "browser console errors/warnings").toEqual([]);
      expect(audit.failedRequests, "browser request failures").toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
