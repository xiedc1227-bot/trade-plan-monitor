import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { ApiClientError, requestJson } from "../../src/api/transport";

it("permits only the editor's documented occurrence policy, never a credential field", async () => {
  const response = (value: object) => fetchResponse(new Response(JSON.stringify(value), { status: 200 }));
  const definition = { exceptionPolicyDefinitions: { authorization: "Plan permission is not occurrence approval" } };
  await expect(requestJson(response(definition), "/api/v1/plan-editor-schema")).resolves.toHaveProperty("body", definition);
  for (const [url, value] of [
    ["/api/test", definition],
    ["/api/v1/plan-editor-schema", { authorization: "Bearer credential" }],
    ["/api/v1/plan-editor-schema", { other: definition }],
    ["/api/v1/plan-editor-schema", { exceptionPolicyDefinitions: { authorization: { token: "credential" } } }],
  ] as const) {
    await expect(requestJson(response(value), url)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  }
});

const MAX_RESPONSE_BYTES = 4 * 1024 * 1024;

function fetchResponse(response: Response): typeof fetch {
  return vi.fn(async () => response);
}

function nestedArray(depth: number): unknown {
  let value: unknown = null;
  for (let index = 0; index < depth; index += 1) {
    value = [value];
  }
  return value;
}

describe("shared JSON transport", () => {
  it("accepts an exact 4 MiB JSON response", async () => {
    const body = `"${"a".repeat(MAX_RESPONSE_BYTES - 2)}"`;

    const result = await requestJson(
      fetchResponse(new Response(body, { status: 200 })),
      "/api/test",
    );

    expect(result.body).toBe("a".repeat(MAX_RESPONSE_BYTES - 2));
    expect(result.status).toBe(200);
  });

  it("cancels a response whose declared length exceeds 4 MiB", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
    });

    await expect(
      requestJson(
        fetchResponse(
          new Response(stream, {
            headers: { "Content-Length": String(MAX_RESPONSE_BYTES + 1) },
            status: 200,
          }),
        ),
        "/api/test",
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
    expect(cancelled).toBe(true);
  });

  it("cancels a chunked response on the first chunk above 4 MiB", async () => {
    let cancelled = false;
    let pulls = 0;
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
      pull(controller) {
        pulls += 1;
        controller.enqueue(new Uint8Array(1024 * 1024).fill(0x20));
        if (pulls === 10) {
          controller.close();
        }
      },
    });

    await expect(
      requestJson(fetchResponse(new Response(stream, { status: 200 })), "/api/test"),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
    expect(cancelled).toBe(true);
    expect(pulls).toBeLessThan(10);
  });

  it.each([
    ["empty", "", undefined],
    ["malformed", '{"message":"response-secret-malformed"', "response-secret-malformed"],
    ["trailing", '{"ok":true} response-secret-trailing', "response-secret-trailing"],
  ])("rejects %s JSON without exposing its body", async (_name, body, secret) => {
    try {
      await requestJson(fetchResponse(new Response(body, { status: 502 })), "/api/test");
      throw new Error("expected requestJson to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiClientError);
      if (typeof secret === "string") {
        expect(String(error)).not.toContain(secret);
        expect(JSON.stringify(error)).not.toContain(secret);
      }
      expect(error).toMatchObject({ code: "INVALID_RESPONSE", status: 502 });
    }
  });

  it("rejects JSON numbers that overflow JavaScript finite range", async () => {
    await expect(
      requestJson(fetchResponse(new Response("1e400", { status: 200 })), "/api/test"),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it("uses fatal UTF-8 decoding and cancels invalid byte streams", async () => {
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
      start(controller) {
        controller.enqueue(new Uint8Array([0x22, 0xc3, 0x28, 0x22]));
      },
    });

    await expect(
      requestJson(fetchResponse(new Response(stream, { status: 200 })), "/api/test"),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
    expect(cancelled).toBe(true);
  });

  it("accepts depth 32 and rejects depth above 32", async () => {
    await expect(
      requestJson(
        fetchResponse(new Response(JSON.stringify(nestedArray(32)), { status: 200 })),
        "/api/test",
      ),
    ).resolves.toMatchObject({ body: nestedArray(32) });

    await expect(
      requestJson(
        fetchResponse(new Response(JSON.stringify(nestedArray(33)), { status: 200 })),
        "/api/test",
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it("accepts 50,000 JSON nodes and rejects the next node", async () => {
    const maximum = Array.from({ length: 49_999 }, () => null);
    const oversized = [...maximum, null];

    await expect(
      requestJson(
        fetchResponse(new Response(JSON.stringify(maximum), { status: 200 })),
        "/api/test",
      ),
    ).resolves.toMatchObject({ body: maximum });

    await expect(
      requestJson(
        fetchResponse(new Response(JSON.stringify(oversized), { status: 200 })),
        "/api/test",
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it("returns only closed fixed-copy API errors", async () => {
    const rawMessage = "provider token must never escape";
    const result = requestJson(
      fetchResponse(
        new Response(
          JSON.stringify({
            error: {
              code: "CONFLICT",
              details: [
                {
                  code: "REVISION_CONFLICT",
                  location: ["body", "expectedRevision"],
                  message: rawMessage,
                },
              ],
              message: rawMessage,
              requestId: "1".repeat(32),
            },
          }),
          { status: 409 },
        ),
      ),
      "/api/test",
    );

    await expect(result).rejects.toMatchObject({
      code: "CONFLICT",
      details: [
        {
          code: "REVISION_CONFLICT",
          location: ["body", "expectedRevision"],
          message: "请求字段无效",
        },
      ],
      message: "请求与当前状态冲突",
      requestId: "1".repeat(32),
      status: 409,
    });
    await expect(result).rejects.not.toThrow(rawMessage);
  });

  it("rejects sensitive keys without re-emitting names or values", async () => {
    const secret = "transport-secret-value";

    try {
      await requestJson(
        fetchResponse(
          new Response(JSON.stringify({ nested: { apiKey: secret } }), { status: 200 }),
        ),
        "/api/test",
      );
      throw new Error("expected requestJson to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiClientError);
      expect(String(error)).not.toContain(secret);
      expect(JSON.stringify(error)).not.toContain(secret);
      expect(error).toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
    }
  });

  it.each([
    ["abort", Object.assign(new Error("abort secret"), { name: "AbortError" })],
    ["network", new Error("network secret")],
  ])(
    "classifies %s failures as typed secret-safe network errors",
    async (_name, failure) => {
      const fetchImplementation = vi.fn<typeof fetch>(async () => {
        throw failure;
      });

      try {
        await requestJson(fetchImplementation, "/api/test");
        throw new Error("expected requestJson to reject");
      } catch (error) {
        expect(error).toBeInstanceOf(ApiClientError);
        expect(String(error)).not.toContain(failure.message);
        expect(JSON.stringify(error)).not.toContain(failure.message);
        expect(error).toMatchObject({
          code: "NETWORK_ERROR",
          message: "无法连接本地监控服务",
          status: 0,
        });
      }
    },
  );

  it("keeps the live client free of a second response reader or error parser", () => {
    const clientSource = readFileSync(resolve(process.cwd(), "src/api/client.ts"), "utf8");

    expect(clientSource).toContain('from "./transport"');
    expect(clientSource).not.toMatch(/JSON\.parse|TextDecoder|getReader|safeErrorMessages/);
  });
});
