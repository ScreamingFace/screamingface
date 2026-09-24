/**
 * The BFF client is the only thing in this app that talks to the gateway, so it is where the
 * console's security properties actually live: which identity is forwarded, and what URL is built.
 *
 * The path-encoding block below is a REGRESSION test. An earlier version of this module encoded
 * the profile `name` and not `accountId`/`provider`, and the inconsistency inside a single template
 * literal read as deliberate rather than as the oversight it was. `../..` in an account id
 * normalizes the request out of `/v1/admin/` entirely, under the admin's forwarded identity.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// `server-only` throws outside the react-server condition, which is where vitest runs. Stubbing it
// does NOT weaken the real guarantee: that is enforced by `next build`, not by the test runner.
vi.mock("server-only", () => ({}));

const headerStore = { value: null as string | null };
vi.mock("next/headers", () => ({
  headers: async () => ({ get: () => headerStore.value }),
}));

const {
  AdminApiError,
  callerEmail,
  createAccount,
  deleteProfile,
  getAccount,
  listAccounts,
  listProviders,
  setApiKey,
} = await import("./client");

const BASE = "http://gateway.test:9105";
let fetchMock: ReturnType<typeof vi.fn>;

function respond(status: number, body?: unknown) {
  return Promise.resolve(
    // 204 must carry a null body — the Response constructor rejects even an empty string.
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

function requestedUrl(): string {
  return String(fetchMock.mock.calls[0][0]);
}

function requestedHeaders(): Record<string, string> {
  return (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
}

beforeEach(() => {
  headerStore.value = "admin@openmined.org";
  process.env.AIGATEWAY_ADMIN_BASE_URL = BASE;
  delete process.env.AIGATEWAY_DEV_USER_EMAIL;
  fetchMock = vi.fn(() => respond(200, { accounts: [], total: 0 }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// --- identity ---------------------------------------------------------------------------------

describe("the forwarded identity", () => {
  it("is read from the incoming request", async () => {
    await listAccounts();

    expect(requestedHeaders()["x-user-email"]).toBe("admin@openmined.org");
  });

  it("is omitted entirely when no identity arrived", async () => {
    headerStore.value = null;

    await listAccounts();

    // Absent, not blank. aigateway treats a blank header as no identity either, but sending the
    // key at all would suggest to a reader that one was supplied.
    expect(requestedHeaders()).not.toHaveProperty("x-user-email");
  });

  it("trims surrounding whitespace", async () => {
    headerStore.value = "  admin@openmined.org  ";

    expect(await callerEmail()).toBe("admin@openmined.org");
  });

  it("treats a blank header as absent", async () => {
    headerStore.value = "   ";

    expect(await callerEmail()).toBeNull();
  });
});

describe("the local-development fallback", () => {
  it("supplies an identity when none arrived and this is not production", async () => {
    headerStore.value = null;
    process.env.AIGATEWAY_DEV_USER_EMAIL = "dev@openmined.org";

    expect(await callerEmail()).toBe("dev@openmined.org");
  });

  it("never overrides a real verified identity", async () => {
    headerStore.value = "real@openmined.org";
    process.env.AIGATEWAY_DEV_USER_EMAIL = "dev@openmined.org";

    expect(await callerEmail()).toBe("real@openmined.org");
  });

  it("is unreachable in a production build", async () => {
    // THE point of the fallback's gate. `next build` sets NODE_ENV=production, so the escape hatch
    // cannot be switched on in the shipped image by setting an environment variable.
    headerStore.value = null;
    process.env.AIGATEWAY_DEV_USER_EMAIL = "dev@openmined.org";
    vi.stubEnv("NODE_ENV", "production");

    expect(await callerEmail()).toBeNull();

    vi.unstubAllEnvs();
  });
});

// --- path construction (regression) ------------------------------------------------------------

describe("path segments are encoded", () => {
  it("keeps a traversal attempt inside /v1/admin/", async () => {
    // Unencoded, `new URL()` normalizes this to /v1/v1/models before the request is sent — the
    // console would issue an arbitrary gateway call carrying the admin's identity.
    await getAccount("../../v1/models");

    const path = new URL(requestedUrl()).pathname;
    expect(path.startsWith("/v1/admin/accounts/")).toBe(true);
    expect(path).not.toContain("/v1/v1/");
  });

  it("does not let an account id splice on a query string", async () => {
    await getAccount("abc?q=1");

    expect(new URL(requestedUrl()).search).toBe("");
  });

  it("encodes the provider segment", async () => {
    // `provider` is free text whenever discovery fails and the form falls back to a typed id.
    await deleteProfile("acc-1", "../..", "default");

    // `encodeURIComponent("../..")` is `..%2F..` — what matters is that no literal `/` survives
    // inside the segment, so the path cannot grow a level.
    expect(new URL(requestedUrl()).pathname).toContain("/profiles/..%2F../default");
  });

  it("encodes the profile name segment", async () => {
    await setApiKey("acc-1", "anthropic", "with space", { api_key: "k" });

    expect(new URL(requestedUrl()).pathname).toContain("with%20space");
  });
});

describe("query parameters", () => {
  it("are omitted when no filters are given", async () => {
    await listAccounts();

    expect(new URL(requestedUrl()).search).toBe("");
  });

  it("carry the search term and paging", async () => {
    await listAccounts({ q: "alice", limit: 10, offset: 20 });

    const params = new URL(requestedUrl()).searchParams;
    expect([params.get("q"), params.get("limit"), params.get("offset")]).toEqual([
      "alice",
      "10",
      "20",
    ]);
  });
});

// --- error taxonomy ----------------------------------------------------------------------------

describe("failures are classified by what the operator must do", () => {
  it.each([
    [401, "unauthenticated"],
    [403, "forbidden"],
    [404, "not_found"],
    [409, "conflict"],
    [422, "invalid"],
    [418, "unknown"],
  ])("maps status %i to kind %s", async (status, kind) => {
    fetchMock.mockReturnValueOnce(respond(status, {}));

    await expect(listAccounts()).rejects.toMatchObject({ kind });
  });

  it("separates the two meanings of 503", async () => {
    // A lost CAS on a concurrent profile write is genuinely retryable; a bare 503 means the admin
    // API is switched off at the deployment level and retrying will never help. Same status code,
    // opposite advice — which is the entire reason this branch exists.
    fetchMock.mockReturnValueOnce(respond(503, { detail: { code: "profile_index_conflict" } }));
    await expect(listAccounts()).rejects.toMatchObject({ kind: "conflict" });

    fetchMock.mockReturnValueOnce(respond(503, { detail: "Admin API is disabled" }));
    await expect(listAccounts()).rejects.toMatchObject({ kind: "unavailable" });
  });

  it("surfaces the gateway's own message when it has one", async () => {
    fetchMock.mockReturnValueOnce(
      respond(422, { detail: { message: "The provider rejected this API key." } }),
    );

    await expect(listAccounts()).rejects.toThrow("The provider rejected this API key.");
  });

  it("reports an unreachable gateway distinctly from one that refused", async () => {
    // Different action: check the URL and whether the process is up, versus fix a request.
    fetchMock.mockRejectedValueOnce(new TypeError("connect ECONNREFUSED"));

    await expect(listAccounts()).rejects.toMatchObject({ kind: "unreachable" });
  });

  it("refuses to guess a gateway address", async () => {
    delete process.env.AIGATEWAY_ADMIN_BASE_URL;

    await expect(listAccounts()).rejects.toBeInstanceOf(AdminApiError);
  });
});

describe("provider discovery", () => {
  it("reads owned_by rather than parsing the model id", async () => {
    // REGRESSION. Splitting the id on "/" dropped every provider whose models are advertised
    // bare — which is `anthropic`, the one this repo defaults to. The list still looked plausible
    // with four other providers in it, so nothing surfaced until someone opened the dropdown.
    fetchMock.mockReturnValueOnce(
      respond(200, {
        data: [
          { id: "claude-opus-4-8", owned_by: "anthropic" },
          { id: "claude-haiku-4-5", owned_by: "anthropic" },
          { id: "antigravity/gemini-3-flash", owned_by: "antigravity" },
        ],
      }),
    );

    await expect(listProviders()).resolves.toEqual(["anthropic", "antigravity"]);
  });

  it("skips a model that names no owner", async () => {
    fetchMock.mockReturnValueOnce(
      respond(200, { data: [{ id: "x" }, { id: "y", owned_by: "  " }, { id: "z", owned_by: "ok" }] }),
    );

    await expect(listProviders()).resolves.toEqual(["ok"]);
  });
});

describe("responses", () => {
  it("parses a body", async () => {
    fetchMock.mockReturnValueOnce(respond(200, { accounts: [{ username: "a@b.test" }], total: 1 }));

    await expect(listAccounts()).resolves.toMatchObject({ total: 1 });
  });

  it("tolerates an empty 204", async () => {
    fetchMock.mockReturnValueOnce(respond(204));

    await expect(deleteProfile("a", "p", "n")).resolves.toBeUndefined();
  });

  it("is never served from cache", async () => {
    // An operator editing state must not be shown a list they already changed.
    await listAccounts();

    expect((fetchMock.mock.calls[0][1] as RequestInit).cache).toBe("no-store");
  });

  it("sends JSON content-type only when there is a body", async () => {
    await createAccount({ email: "new@openmined.org" });

    expect(requestedHeaders()["content-type"]).toBe("application/json");
  });
});

// --- the key write carries no saved defaults (OME-1322) -----------------------------------------

describe("setApiKey", () => {
  // INVARIANT (OME-1138 Stage C, UI-first): the console never authors saved Profile defaults. The
  // body is exactly `{ "api_key": … }` — no `defaults` property, not even `null` — so the gateway's
  // later rejection of defaults-carrying writes cannot trip on this console.
  it("sends a body whose only key is api_key, on the unchanged legacy endpoint", async () => {
    fetchMock.mockImplementation(() => respond(200, { id: "p1" }));
    // WHY a non-literal: a stale caller object can still carry the old property at runtime, and
    // the wire must not follow it.
    const stale = { api_key: "sk-live-secret-value", defaults: null };

    await setApiKey("acc-1", "openai", "default", stale);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url).pathname).toBe("/v1/admin/accounts/acc-1/profiles/openai/default/api-key");
    expect(init.method).toBe("PUT");
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(Object.keys(body)).toEqual(["api_key"]);
    expect(body).toEqual({ api_key: "sk-live-secret-value" });
  });
});
