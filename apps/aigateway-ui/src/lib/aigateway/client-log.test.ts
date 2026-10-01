/**
 * FEATURE: BFF error traceability (OME-943).
 * STORY: as an operator debugging a console failure, I find exactly one server-side log line per
 * failed admin call — method, path, error kind, status and the mesh's request id — instead of a
 * failure that reached the browser and left nothing behind.
 *
 * Lives in its own file because `client.test.ts` stubs `headers()` to answer every header name
 * with the caller's email — fine for identity tests, but it would make every request id an email
 * address here. That file is append-only, so the header-aware stub lives here instead.
 *
 * INVARIANT: the upstream response body is never logged. It can carry provider text, and an
 * error body from a key write could echo the key.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const incoming = new Map<string, string>();
vi.mock("next/headers", () => ({
  headers: async () => ({ get: (name: string) => incoming.get(name.toLowerCase()) ?? null }),
}));

const { listAccounts, setApiKey, uploadCacheSnapshot } = await import("./client");

const BASE = "http://gateway.test:9105";
const SECRET = "sk-live-0123456789abcdef";
let fetchMock: ReturnType<typeof vi.fn>;
let warn: ReturnType<typeof vi.spyOn>;
let error: ReturnType<typeof vi.spyOn>;

function respond(status: number, body?: unknown) {
  return Promise.resolve(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

/** Every line the BFF wrote, at any level, parsed. */
function records(): Record<string, unknown>[] {
  return [...warn.mock.calls, ...error.mock.calls].map((call: unknown[]) =>
    JSON.parse(String(call[0])),
  );
}

function rawLines(): string {
  return [...warn.mock.calls, ...error.mock.calls].map((call: unknown[]) => String(call[0])).join("\n");
}

beforeEach(() => {
  incoming.clear();
  incoming.set("x-user-email", "admin@openmined.org");
  incoming.set("x-request-id", "req-7f3a");
  process.env.AIGATEWAY_ADMIN_BASE_URL = BASE;
  delete process.env.LOG_LEVEL;
  fetchMock = vi.fn(() => respond(200, { accounts: [], total: 0 }));
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(console, "debug").mockImplementation(() => {});
  vi.spyOn(console, "info").mockImplementation(() => {});
  warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  error = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  delete process.env.LOG_LEVEL;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("a failing admin call", () => {
  it("writes exactly one structured server log line", async () => {
    fetchMock.mockReturnValueOnce(respond(500, { detail: "boom" }));

    await expect(listAccounts()).rejects.toMatchObject({ kind: "unknown" });

    expect(records()).toHaveLength(1);
    expect(records()[0]).toMatchObject({
      level: "error",
      msg: "bff_admin_error",
      method: "GET",
      path: "/v1/admin/accounts",
      kind: "unknown",
      status: 500,
      requestId: "req-7f3a",
    });
  });

  it("logs a request-level refusal at warn, not error", async () => {
    fetchMock.mockReturnValueOnce(respond(403, { detail: "not an admin" }));

    await expect(listAccounts()).rejects.toMatchObject({ kind: "forbidden" });

    expect(error).not.toHaveBeenCalled();
    expect(records()).toEqual([expect.objectContaining({ level: "warn", kind: "forbidden", status: 403 })]);
  });

  it("logs an unreachable gateway at error with status 0", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("connect ECONNREFUSED"));

    await expect(listAccounts()).rejects.toMatchObject({ kind: "unreachable" });

    expect(records()).toEqual([
      expect.objectContaining({ level: "error", kind: "unreachable", status: 0 }),
    ]);
  });

  it("drops the query string, which carries operator-typed search text", async () => {
    fetchMock.mockReturnValueOnce(respond(500, {}));

    await expect(listAccounts({ q: "someone@example.com", limit: 5 })).rejects.toBeTruthy();

    expect(records()[0].path).toBe("/v1/admin/accounts");
    expect(rawLines()).not.toContain("someone@example.com");
  });

  it("names the method of a write", async () => {
    fetchMock.mockReturnValueOnce(respond(422, { detail: { message: "bad key" } }));

    await expect(setApiKey("acct-1", "anthropic", "default", { api_key: SECRET })).rejects.toBeTruthy();

    expect(records()[0]).toMatchObject({
      method: "PUT",
      path: "/v1/admin/accounts/acct-1/profiles/anthropic/default/api-key",
      kind: "invalid",
    });
  });

  it("never logs the upstream body, its detail, or the message derived from it", async () => {
    // A provider that echoes the submitted key in its refusal — the worst case for a log line.
    fetchMock.mockReturnValueOnce(
      respond(422, { detail: { message: `Provider said: invalid key ${SECRET}` } }),
    );

    await expect(setApiKey("acct-1", "anthropic", "default", { api_key: SECRET })).rejects.toBeTruthy();

    expect(records()).toHaveLength(1);
    expect(rawLines()).not.toContain(SECRET);
    expect(rawLines()).not.toContain("Provider said");
  });

  it("records a null request id when the mesh supplied none", async () => {
    incoming.delete("x-request-id");
    fetchMock.mockReturnValueOnce(respond(500, {}));

    await expect(listAccounts()).rejects.toBeTruthy();

    expect(records()[0].requestId).toBeNull();
  });

  it("is silenced at warn when LOG_LEVEL=error, while errors still log", async () => {
    process.env.LOG_LEVEL = "error";
    fetchMock.mockReturnValueOnce(respond(404, {}));
    fetchMock.mockReturnValueOnce(respond(503, {}));

    await expect(listAccounts()).rejects.toMatchObject({ kind: "not_found" });
    await expect(listAccounts()).rejects.toMatchObject({ kind: "unavailable" });

    expect(records()).toEqual([expect.objectContaining({ level: "error", kind: "unavailable" })]);
  });
});

describe("a successful admin call", () => {
  it("logs nothing", async () => {
    await listAccounts();

    expect(records()).toEqual([]);
  });
});

describe("the snapshot upload", () => {
  const archive = () => new File(["x"], "snap.sql.gz");

  it("logs its failure exactly once, too", async () => {
    fetchMock.mockReturnValueOnce(respond(409, { detail: "busy" }));

    await expect(
      uploadCacheSnapshot({
        mode: "merge",
        force: false,
        acknowledgeLoss: false,
        snapshot: archive(),
        manifest: null,
      }),
    ).rejects.toMatchObject({ kind: "conflict" });

    expect(records()).toEqual([
      expect.objectContaining({
        level: "warn",
        method: "POST",
        path: "/v1/admin/cache/snapshots",
        kind: "conflict",
        status: 409,
        requestId: "req-7f3a",
      }),
    ]);
  });

  it("logs an unreachable gateway", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));

    await expect(
      uploadCacheSnapshot({
        mode: "replace",
        force: true,
        acknowledgeLoss: true,
        snapshot: archive(),
        manifest: null,
      }),
    ).rejects.toMatchObject({ kind: "unreachable" });

    expect(records()).toEqual([
      expect.objectContaining({ level: "error", kind: "unreachable", path: "/v1/admin/cache/snapshots" }),
    ]);
  });
});
