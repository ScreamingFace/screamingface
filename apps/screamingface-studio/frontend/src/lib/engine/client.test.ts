import { createEngineClient } from "./client";
import { EngineError } from "./errors";

const BASE = "http://127.0.0.1:9108";
const KEY = "sk-or-secret-value-123";

type Call = { url: string; init: RequestInit };

function fakeFetch(
  respond: (call: Call) => Response | Promise<Response>,
): { fetch: typeof fetch; calls: Call[] } {
  const calls: Call[] = [];
  const impl = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const call = { url: String(input), init };
    calls.push(call);
    return respond(call);
  }) as typeof fetch;
  return { fetch: impl, calls };
}

function json(body: unknown, status = 200, type = "application/json") {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": type },
  });
}

function problem(status: number, detail: string) {
  return json(
    { type: "about:blank", title: "x", status, detail },
    status,
    "application/problem+json",
  );
}

const connection = {
  object: "connection",
  provider: "openrouter",
  display_name: "OpenRouter",
  auth_methods: ["api_key"],
  status: "connected",
  auth_method: "api_key",
  account_label: null,
};

function headersOf(call: Call): Headers {
  return new Headers(call.init.headers);
}

describe("createEngineClient", () => {
  it("lists connections", async () => {
    const { fetch, calls } = fakeFetch(() =>
      json({ object: "list", data: [connection] }),
    );
    const client = createEngineClient(BASE, fetch);

    await expect(client.listConnections()).resolves.toEqual([connection]);
    expect(calls[0].url).toBe(`${BASE}/v1/connections`);
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.cache).toBe("no-store");
  });

  it("connects an API key with a JSON PUT", async () => {
    const { fetch, calls } = fakeFetch(() => json(connection));
    const client = createEngineClient(BASE, fetch);

    await expect(client.connectApiKey("openrouter", KEY)).resolves.toEqual(
      connection,
    );
    expect(calls[0].url).toBe(`${BASE}/v1/connections/openrouter`);
    expect(calls[0].init.method).toBe("PUT");
    expect(headersOf(calls[0]).get("content-type")).toBe("application/json");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ api_key: KEY });
  });

  it("starts OAuth", async () => {
    const authorization = {
      object: "oauth_authorization",
      provider: "codex",
      authorize_url: "https://auth.example/authorize?x=1",
      expires_in: 600,
    };
    const { fetch, calls } = fakeFetch(() => json(authorization, 201));
    const client = createEngineClient(BASE, fetch);

    await expect(client.startOAuth("codex")).resolves.toEqual(authorization);
    expect(calls[0].url).toBe(`${BASE}/v1/connections/codex/oauth`);
    expect(calls[0].init.method).toBe("POST");
  });

  it("disconnects", async () => {
    const { fetch, calls } = fakeFetch(() =>
      json({ ...connection, status: "not_connected" }),
    );
    const client = createEngineClient(BASE, fetch);

    const result = await client.disconnect("openrouter");
    expect(result.status).toBe("not_connected");
    expect(calls[0].init.method).toBe("DELETE");
  });

  it("lists models", async () => {
    const model = {
      id: "openrouter/x",
      object: "model",
      owned_by: "openrouter",
      supported_parameters: ["max_tokens"],
      supported_tools: [],
    };
    const { fetch, calls } = fakeFetch(() =>
      json({ object: "list", data: [model] }),
    );
    const client = createEngineClient(BASE, fetch);

    await expect(client.listModels()).resolves.toEqual([model]);
    expect(calls[0].url).toBe(`${BASE}/v1/models`);
  });

  it("checks health", async () => {
    const { fetch, calls } = fakeFetch(() => json({ status: "ok" }));
    await createEngineClient(BASE, fetch).health();
    expect(calls[0].url).toBe(`${BASE}/healthz`);
  });

  it("encodes provider ids and tolerates a trailing slash on the base URL", async () => {
    const { fetch, calls } = fakeFetch(() => json(connection));
    await createEngineClient(`${BASE}/`, fetch).disconnect("a/b c");
    expect(calls[0].url).toBe(`${BASE}/v1/connections/a%2Fb%20c`);
  });

  it("never sends an X-Profile header", async () => {
    const { fetch, calls } = fakeFetch(() => json({ object: "list", data: [] }));
    const client = createEngineClient(BASE, fetch);
    await client.listConnections();
    await client.listModels();
    for (const call of calls) {
      expect(headersOf(call).has("x-profile")).toBe(false);
    }
  });

  it.each([
    [400, "invalid"],
    [422, "invalid"],
    [401, "unauthenticated"],
    [403, "unauthenticated"],
    [404, "not_found"],
    [502, "unavailable"],
    [503, "unavailable"],
    [504, "unavailable"],
    [500, "unknown"],
  ] as const)("maps a %i problem to %s", async (status, kind) => {
    const { fetch } = fakeFetch(() => problem(status, "the detail"));
    const error = await createEngineClient(BASE, fetch)
      .listConnections()
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(EngineError);
    expect(error).toMatchObject({ kind, status, detail: "the detail" });
  });

  it("uses a generic detail when the error body is not JSON", async () => {
    const { fetch } = fakeFetch(
      () => new Response("<html>bad gateway</html>", { status: 502 }),
    );
    const error = await createEngineClient(BASE, fetch)
      .listModels()
      .catch((caught: unknown) => caught);

    expect(error).toMatchObject({ kind: "unavailable", status: 502 });
    expect((error as EngineError).detail).not.toContain("<html>");
  });

  it("reports a network failure as unreachable", async () => {
    const { fetch } = fakeFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const error = await createEngineClient(BASE, fetch)
      .listConnections()
      .catch((caught: unknown) => caught);

    expect(error).toMatchObject({ kind: "unreachable" });
    expect((error as EngineError).status).toBeUndefined();
  });

  it("rejects a success body that is not the expected shape", async () => {
    const { fetch } = fakeFetch(() => json({ nope: true }));
    const error = await createEngineClient(BASE, fetch)
      .listConnections()
      .catch((caught: unknown) => caught);

    expect(error).toMatchObject({ kind: "unknown" });
  });

  it("never leaks the API key, even when the server echoes it back", async () => {
    const { fetch } = fakeFetch(() => problem(401, `bad key ${KEY}`));
    const error = (await createEngineClient(BASE, fetch)
      .connectApiKey("openrouter", KEY)
      .catch((caught: unknown) => caught)) as EngineError;

    expect(error).toMatchObject({ kind: "unauthenticated" });
    expect(error.detail).not.toContain(KEY);
    expect(error.message).not.toContain(KEY);
    expect(JSON.stringify(error)).not.toContain(KEY);
  });
});

describe("createEngineClient.listBenchmarks", () => {
  const benchmark = {
    object: "benchmark",
    id: "ifeval",
    title: "IFEval",
    description: "Verifiable instruction following.",
    revision: "r1",
    case_count: 541,
    origin: "inspect_evals",
    focus: "Instruction following",
    difficulty: "standard",
    interaction: "single_shot",
    failure_policy: "withhold",
    href: "/v1/benchmarks/ifeval",
  };

  it("lists the Engine's installed benchmarks", async () => {
    const { fetch, calls } = fakeFetch(() =>
      json({ object: "list", data: [benchmark] }),
    );

    await expect(createEngineClient(BASE, fetch).listBenchmarks()).resolves.toEqual([
      benchmark,
    ]);
    expect(calls[0].url).toBe(`${BASE}/v1/benchmarks`);
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.cache).toBe("no-store");
  });

  it("maps a problem+json answer to an EngineError kind", async () => {
    const { fetch } = fakeFetch(() => problem(503, "catalog is loading"));
    const error = await createEngineClient(BASE, fetch)
      .listBenchmarks()
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(EngineError);
    expect(error).toMatchObject({
      kind: "unavailable",
      status: 503,
      detail: "catalog is loading",
    });
  });

  it("reports a network failure as unreachable", async () => {
    const { fetch } = fakeFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const error = await createEngineClient(BASE, fetch)
      .listBenchmarks()
      .catch((caught: unknown) => caught);

    expect(error).toMatchObject({ kind: "unreachable" });
  });
});
