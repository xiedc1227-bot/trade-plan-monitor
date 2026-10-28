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
const SOURCE_RESPONSE_BYTES = 1024 * 1024;

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

describe("per-request raw response byte limits", () => {
  it("accepts exactly 1 MiB and rejects the next raw byte", async () => {
    for (const extra of [0, 1]) {
      const body = `"${"a".repeat(SOURCE_RESPONSE_BYTES - 2 + extra)}"`;
      const result = requestJson(
        fetchResponse(new Response(body)), "/api/test", undefined,
        { maxResponseBytes: SOURCE_RESPONSE_BYTES },
      );
      if (extra === 0) await expect(result).resolves.toHaveProperty("body", JSON.parse(body));
      else await expect(result).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
    }
  });

  it("cancels an excessive declared length without acquiring a reader", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({
      cancel,
      start(controller) {
        controller.enqueue(new TextEncoder().encode("null"));
        controller.close();
      },
    });
    const getReader = vi.spyOn(stream, "getReader");
    await expect(requestJson(
      fetchResponse(new Response(stream, {
        headers: { "Content-Length": String(SOURCE_RESPONSE_BYTES + 1) },
      })), "/api/test", undefined, { maxResponseBytes: SOURCE_RESPONSE_BYTES },
    )).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
    expect(getReader).not.toHaveBeenCalled();
    expect(cancel).toHaveBeenCalledOnce();
    expect(stream.locked).toBe(false);
  });

  it.each([undefined, "0", "1", "invalid"])(
    "bounds actual streamed bytes even with Content-Length %s", async (contentLength) => {
      const body = new TextEncoder().encode(`"${"a".repeat(SOURCE_RESPONSE_BYTES - 1)}"`);
      const cancel = vi.fn();
      let index = 0;
      const chunks = [body.slice(0, SOURCE_RESPONSE_BYTES), body.slice(SOURCE_RESPONSE_BYTES)];
      const stream = new ReadableStream<Uint8Array>({
        cancel,
        pull(controller) {
          const chunk = chunks[index++];
          if (chunk === undefined) controller.close();
          else controller.enqueue(chunk);
        },
      }, { highWaterMark: 0 });
      await expect(requestJson(
        fetchResponse(new Response(stream, {
          ...(contentLength === undefined ? {} : { headers: { "Content-Length": contentLength } }),
        })), "/api/test", undefined, { maxResponseBytes: SOURCE_RESPONSE_BYTES },
      )).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
      expect(cancel).toHaveBeenCalledOnce();
      expect(index).toBe(2);
      expect(stream.locked).toBe(false);
    },
  );

  it.each([
    ["whitespace", `null${" ".repeat(SOURCE_RESPONSE_BYTES - 3)}`],
    ["JSON escapes", `"${"\\u0061".repeat(Math.floor((SOURCE_RESPONSE_BYTES - 2) / 6) + 1)}"`],
  ])("counts original %s rather than a re-serialized JSON value", async (_name, raw) => {
    expect(new TextEncoder().encode(raw).byteLength).toBeGreaterThan(SOURCE_RESPONSE_BYTES);
    expect(new TextEncoder().encode(JSON.stringify(JSON.parse(raw))).byteLength)
      .toBeLessThan(SOURCE_RESPONSE_BYTES);
    await expect(requestJson(
      fetchResponse(new Response(raw)), "/api/test", undefined,
      { maxResponseBytes: SOURCE_RESPONSE_BYTES },
    )).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it("accepts a byte-exact multibyte response split inside UTF-8 characters", async () => {
    const value = `${"😀".repeat((SOURCE_RESPONSE_BYTES - 4) / 4)}ab`;
    const bytes = new TextEncoder().encode(JSON.stringify(value));
    expect(bytes.byteLength).toBe(SOURCE_RESPONSE_BYTES);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, 3));
        controller.enqueue(bytes.slice(3, SOURCE_RESPONSE_BYTES - 5));
        controller.enqueue(bytes.slice(SOURCE_RESPONSE_BYTES - 5));
        controller.close();
      },
    });
    const result = await requestJson(fetchResponse(new Response(stream)), "/api/test", undefined,
      { maxResponseBytes: SOURCE_RESPONSE_BYTES });
    expect(result.body).toBe(value);
    expect(stream.locked).toBe(false);
  });

  it("rejects multibyte content one byte above the cap despite its smaller UTF-16 length", async () => {
    const raw = JSON.stringify(`${"😀".repeat((SOURCE_RESPONSE_BYTES - 4) / 4)}abc`);
    expect(raw.length).toBeLessThan(SOURCE_RESPONSE_BYTES);
    expect(new TextEncoder().encode(raw).byteLength).toBe(SOURCE_RESPONSE_BYTES + 1);
    await expect(requestJson(fetchResponse(new Response(raw)), "/api/test", undefined,
      { maxResponseBytes: SOURCE_RESPONSE_BYTES }))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
  });

  it("still cancels and releases a malformed UTF-8 stream under the smaller cap", async () => {
    const cancel = vi.fn();
    const stream = new ReadableStream<Uint8Array>({
      cancel,
      start(controller) {
        controller.enqueue(new Uint8Array([0x22, 0xc3, 0x28, 0x22]));
      },
    });
    await expect(requestJson(fetchResponse(new Response(stream)), "/api/test", undefined,
      { maxResponseBytes: SOURCE_RESPONSE_BYTES }))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
    expect(cancel).toHaveBeenCalledOnce();
    expect(stream.locked).toBe(false);
  });

  it("keeps overflow secret-safe and releases the reader even when cancellation fails", async () => {
    let sent = false;
    const stream = new ReadableStream<Uint8Array>({
      cancel() { throw new Error("cancel-secret"); },
      pull(controller) {
        if (sent) controller.close();
        else {
          sent = true;
          controller.enqueue(new TextEncoder().encode('"response-secret"'));
        }
      },
    }, { highWaterMark: 0 });
    const result = requestJson(fetchResponse(new Response(stream)), "/api/test", undefined,
      { maxResponseBytes: 4 });
    await expect(result).rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 200 });
    await expect(result).rejects.not.toThrow(/secret/);
    expect(stream.locked).toBe(false);
  });

  it.each([0, -1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY,
    1.5, MAX_RESPONSE_BYTES + 1, Number.MAX_SAFE_INTEGER + 1, "1024", null])(
    "rejects invalid cap %s before invoking fetch", async (maxResponseBytes) => {
      const fetchImplementation = vi.fn(async () => new Response("null"));
      await expect(requestJson(fetchImplementation, "/api/test", undefined,
        { maxResponseBytes: maxResponseBytes as number }))
        .rejects.toMatchObject({ code: "INVALID_RESPONSE", status: 0 });
      expect(fetchImplementation).not.toHaveBeenCalled();
    },
  );

  it("does not persist a smaller cap across requests or alter omitted/undefined defaults", async () => {
    const fetchImplementation = vi.fn(async () => new Response('"1234567"'));
    await expect(requestJson(fetchImplementation, "/api/test", undefined, { maxResponseBytes: 8 }))
      .rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    for (const options of [undefined, {}, { maxResponseBytes: undefined },
      { maxResponseBytes: MAX_RESPONSE_BYTES }]) {
      await expect(requestJson(fetchImplementation, "/api/test", undefined, options))
        .resolves.toHaveProperty("body", "1234567");
    }
  });

  it("preserves the exact RequestInit and AbortSignal without leaking transport options", async () => {
    const controller = new AbortController();
    const init = { method: "GET", signal: controller.signal, headers: { Accept: "application/json" } };
    const fetchImplementation = vi.fn<typeof fetch>(async () => new Response('{"ok":[true]}'));
    const result = await requestJson(fetchImplementation, "/api/test", init,
      { maxResponseBytes: SOURCE_RESPONSE_BYTES });
    expect(fetchImplementation).toHaveBeenCalledExactlyOnceWith("/api/test", init);
    expect(fetchImplementation.mock.calls[0]?.[1]).toBe(init);
    expect(Object.isFrozen(result)).toBe(true);
    expect(Object.isFrozen(result.body)).toBe(true);
    expect(Object.isFrozen((result.body as { ok: boolean[] }).ok)).toBe(true);
  });

  it("preserves sanitized network classification for an already aborted request", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchImplementation = vi.fn<typeof fetch>(async (_input, init) => {
      expect(init?.signal).toBe(controller.signal);
      throw new DOMException("abort-secret", "AbortError");
    });
    const result = requestJson(fetchImplementation, "/api/test", { signal: controller.signal },
      { maxResponseBytes: SOURCE_RESPONSE_BYTES });
    await expect(result).rejects.toMatchObject({ code: "NETWORK_ERROR", status: 0 });
    await expect(result).rejects.not.toThrow("abort-secret");
  });

  it.each([[409, "CONFLICT"], [422, "VALIDATION_ERROR"], [500, "INTERNAL_ERROR"]] as const)(
    "preserves structured API error %s under a smaller cap", async (status, code) => {
      const response = new Response(JSON.stringify({ error: {
        code, details: [], message: "provider-secret", requestId: "1".repeat(32),
      } }), { status });
      const result = requestJson(fetchResponse(response), "/api/test", undefined,
        { maxResponseBytes: SOURCE_RESPONSE_BYTES });
      await expect(result).rejects.toMatchObject({ code, status });
      await expect(result).rejects.not.toThrow("provider-secret");
    },
  );
});
