import frames from "./__fixtures__/frames.json";
import type { RunEvent } from "./run-types";
import { RunError, type RunSocket, isRunError, startRun } from "./run";
import { linkCandidate } from "./url4";

vi.mock("../runtime", () => ({
  getEngineUrl: vi.fn(async () => "http://127.0.0.1:9108"),
}));

const BASE = "http://127.0.0.1:9108";
const TOPIC = "3f1c2a9e8b7d4c6f9a0b1c2d3e4f5a6b";
const NOW = Date.UTC(2026, 9, 9, 12, 0, 0);
const CANDIDATE = "(model_1:0.0:/openai/gpt-4o($input)!'Answer.')!'$model_1'";
const BENCHMARK = "(case:0.0:/sf/case-1($candidate)!'grade')!'$case'";

function base64url(value: string) {
  return btoa(value).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// A capability JWT shaped like the Engine's (HS256, `sub` = the run's topic).
const TOKEN = [
  base64url(JSON.stringify({ alg: "HS256", typ: "JWT" })),
  base64url(JSON.stringify({ sub: TOPIC, iat: 1791201600, exp: 1791260400 })),
  "c2lnbmF0dXJlLW5vdC1jaGVja2VkLWJ5LXN0dWRpbw",
].join(".");

type Reply = {
  ok: boolean;
  status: number;
  headers: Headers;
  json: () => Promise<unknown>;
  arrayBuffer: () => Promise<ArrayBuffer>;
};

function reply(status: number, body?: unknown, type = "application/json"): Reply {
  const raw = typeof body === "string" ? body : JSON.stringify(body ?? null);
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": type }),
    json: async () => JSON.parse(raw),
    arrayBuffer: async () => new TextEncoder().encode(raw).buffer as ArrayBuffer,
  };
}

function problem(status: number, detail: string) {
  return reply(status, { type: "about:blank", title: "x", status, detail }, "application/problem+json");
}

const ATTACHING = () =>
  problem(428, "attach a WebSocket to the topic before starting the run");

type Call = { url: string; method: string; headers: Record<string, string> };

type EngineRoutes = {
  benchmark?: () => Reply;
  start?: (() => Reply)[];
  artifact?: () => Reply;
};

function fakeEngine(routes: EngineRoutes = {}) {
  const calls: Call[] = [];
  const start = [...(routes.start ?? [])];
  const fetchImpl = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input);
    const method = init.method ?? "GET";
    calls.push({ url, method, headers: (init.headers ?? {}) as Record<string, string> });
    if (url.startsWith(`${BASE}/v1/benchmarks/`)) {
      return (routes.benchmark ?? (() => reply(200, { id: "ifeval", url4: BENCHMARK })))();
    }
    if (url === `${BASE}/token` && method === "POST") return reply(200, { token: TOKEN });
    if (url.startsWith(`${BASE}/?q=`)) return (start.shift() ?? (() => reply(202, "")))();
    if (url.startsWith(`${BASE}/artifacts/`) && routes.artifact) return routes.artifact();
    if (method === "DELETE") return reply(204, "");
    throw new Error(`unexpected request ${method} ${url}`);
  }) as unknown as typeof globalThis.fetch;
  const startCalls = () => calls.filter((call) => call.url.startsWith(`${BASE}/?q=`));
  return { fetch: fetchImpl, calls, startCalls };
}

class FakeSocket implements RunSocket {
  static instances: FakeSocket[] = [];
  sent: Record<string, unknown>[] = [];
  closed = false;
  onopen: RunSocket["onopen"] = null;
  onmessage: RunSocket["onmessage"] = null;
  onerror: RunSocket["onerror"] = null;
  onclose: RunSocket["onclose"] = null;

  constructor(
    readonly url: string,
    readonly protocols: string[],
  ) {
    FakeSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(JSON.parse(data));
  }

  close() {
    this.closed = true;
  }

  open() {
    this.onopen?.({});
  }

  receive(...items: unknown[]) {
    for (const item of items) this.onmessage?.({ data: JSON.stringify(item) });
  }
}

async function flush() {
  for (let i = 0; i < 30; i += 1) await Promise.resolve();
}

const HAPPY = frames.happyPath;

type LaunchOptions = {
  routes?: EngineRoutes;
  useCache?: boolean;
  signal?: AbortSignal;
};

async function launch({ routes, useCache = true, signal }: LaunchOptions = {}) {
  FakeSocket.instances = [];
  const engine = fakeEngine(routes);
  const events: RunEvent[] = [];
  const run = startRun({
    candidateUrl4: CANDIDATE,
    benchmarkId: "ifeval",
    limit: 1,
    useCache,
    onEvent: (event) => events.push(event),
    signal,
    deps: { fetch: engine.fetch, WebSocket: FakeSocket, now: () => NOW, engineUrl: `${BASE}/` },
  });
  // Observed here so a rejection a test inspects later is never "unhandled".
  const outcome = run.then(
    (value) => ({ value }),
    (error: unknown) => ({ error }),
  );
  await flush();
  return { run, outcome, engine, events, socket: () => FakeSocket.instances.at(-1) as FakeSocket };
}

async function started(options: LaunchOptions = {}) {
  const launched = await launch(options);
  launched.socket().open();
  await flush();
  return launched;
}

async function rejection(outcome: Promise<{ value?: unknown; error?: unknown }>) {
  const settled = await outcome;
  if (!("error" in settled) || !isRunError(settled.error)) {
    throw new Error(`expected a RunError, got ${JSON.stringify(settled)}`);
  }
  return settled.error;
}

const EXPECTED_EVENTS: RunEvent[] = [
  { type: "started" },
  { type: "activity", kind: "case_loading", state: "started", body: "Loading cases started" },
  { type: "activity", kind: "case_loading", state: "completed", body: "Loading cases completed" },
  { type: "activity", kind: "answering", state: "started", caseId: 1000, body: "Answering started" },
  {
    type: "activity",
    kind: "model_call",
    state: "started",
    caseId: 1000,
    modelId: "openai/gpt-4o",
    body: "Model call started",
  },
  {
    type: "activity",
    kind: "model_call",
    state: "completed",
    caseId: 1000,
    modelId: "openai/gpt-4o",
    body: "Model call completed",
  },
  {
    type: "activity",
    kind: "answering",
    state: "completed",
    caseId: 1000,
    body: "Answering completed",
  },
  { type: "progress", completed: 1, graded: 1, score: 1 },
  { type: "cost", totalUsd: 0.0002675 },
];

afterEach(() => {
  vi.useRealTimers();
});

describe("startRun", () => {
  it("resolves the CandidateResult and reports events in stream order", async () => {
    const { outcome, events, socket } = await started();

    socket().receive(...HAPPY.slice(0, 5), frames.heartbeat, ...HAPPY.slice(5));

    expect(await outcome).toEqual({ value: frames.candidateResult });
    expect(events).toEqual(EXPECTED_EVENTS);
    expect(socket().closed).toBe(true);
  });

  it("fetches the benchmark, mints a token, attaches, then starts the linked run", async () => {
    const { engine, socket } = await started();

    expect(engine.calls[0].url).toBe(`${BASE}/v1/benchmarks/ifeval?limit=1`);
    expect(engine.calls[1]).toMatchObject({ url: `${BASE}/token`, method: "POST" });
    expect(socket().url).toBe(`ws://127.0.0.1:9108/ws?ticket=${encodeURIComponent(TOKEN)}`);
    expect(socket().protocols).toEqual(["cloudevents.json"]);
    expect(socket().sent[0]).toEqual({
      specversion: "1.0",
      id: expect.any(String),
      source: "/screamingface/studio",
      time: new Date(NOW).toISOString(),
      type: "ai.url4.attach",
      datacontenttype: "application/json",
      data: { from_sequence: null, cache: { participate: true } },
    });

    const [startCall] = engine.startCalls();
    expect(new URL(startCall.url).searchParams.get("q")).toBe(linkCandidate(CANDIDATE, BENCHMARK));
    expect(startCall.headers).toEqual({ "URL4-Capability": TOKEN, Prefer: "respond-async" });
  });

  it("opts out of the cache with no-store and participate: false", async () => {
    const { engine, socket } = await started({ useCache: false });

    expect(socket().sent[0]).toMatchObject({ data: { cache: { participate: false } } });
    expect(engine.startCalls()[0].headers["Cache-Control"]).toBe("no-store");
  });

  it("re-sends the start while the socket attach is still registering", async () => {
    vi.useFakeTimers();
    const { engine, outcome, socket } = await started({
      routes: { start: [ATTACHING, ATTACHING, () => reply(202, "")] },
    });

    await vi.advanceTimersByTimeAsync(100);
    expect(engine.startCalls()).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(100);
    expect(engine.startCalls()).toHaveLength(3);

    socket().receive(...HAPPY);
    expect(await outcome).toEqual({ value: frames.candidateResult });
  });

  it("gives up after five re-sends", async () => {
    vi.useFakeTimers();
    const { engine, outcome } = await started({ routes: { start: Array(6).fill(ATTACHING) } });

    await vi.advanceTimersByTimeAsync(500);

    const error = await rejection(outcome);
    expect(engine.startCalls()).toHaveLength(6);
    expect(error).toMatchObject({ kind: "failed", code: "http_428" });
  });

  it("rejects any other 428 at once", async () => {
    const { engine, outcome } = await started({
      routes: { start: [() => problem(428, "precondition: something else")] },
    });

    const error = await rejection(outcome);
    expect(engine.startCalls()).toHaveLength(1);
    expect(error).toMatchObject({
      kind: "failed",
      code: "http_428",
      message: "precondition: something else",
    });
  });

  it("fetches an artifact result with the capability and verifies it", async () => {
    const { outcome, engine, socket } = await started({
      routes: { artifact: () => reply(200, frames.artifactBody) },
    });

    socket().receive(...HAPPY.slice(0, 10), frames.artifactResult, HAPPY[11]);

    expect(await outcome).toEqual({ value: frames.candidateResult });
    const artifactCall = engine.calls.find((call) => call.url.includes("/artifacts/"));
    expect(artifactCall?.url).toBe(
      `${BASE}/artifacts/${frames.artifactResult.data.artifact?.id}`,
    );
    expect(artifactCall?.headers["URL4-Capability"]).toBe(TOKEN);
  });

  it("refuses an artifact that fails its integrity check", async () => {
    const tampered = frames.artifactBody.replace('"score":1.0', '"score":0.9');
    const { outcome, socket } = await started({
      routes: { artifact: () => reply(200, tampered) },
    });

    socket().receive(...HAPPY.slice(0, 10), frames.artifactResult, HAPPY[11]);

    expect(await rejection(outcome)).toMatchObject({ kind: "stream_failed" });
  });

  it("rejects an artifact the Engine will not hand over", async () => {
    const { outcome, socket } = await started({
      routes: { artifact: () => problem(404, "no such artifact") },
    });

    socket().receive(...HAPPY.slice(0, 10), frames.artifactResult, HAPPY[11]);

    expect(await rejection(outcome)).toMatchObject({
      kind: "stream_failed",
      code: "http_404",
      message: "no such artifact",
    });
  });

  it("rejects a failed run with the Engine's code and message", async () => {
    const { outcome, socket } = await started();

    socket().receive(HAPPY[0], HAPPY[1], frames.terminatedBenchmarkUnavailable);

    expect(await rejection(outcome)).toMatchObject({
      kind: "failed",
      code: "benchmark_unavailable",
      message: "Benchmark 'ifeval' is not prepared on this Engine",
    });
  });

  it("rejects a run the Engine timed out", async () => {
    const { outcome, socket } = await started();
    const timedOut = {
      ...frames.terminatedStopped,
      sequence: "1",
      data: { status: "timed_out", error: { code: "run_timeout", message: "Too slow", permanent: false } },
    };

    socket().receive(timedOut);

    expect(await rejection(outcome)).toMatchObject({ kind: "timed_out", code: "run_timeout" });
  });

  it("reorders frames, drops duplicates, and reports a gap that never fills", async () => {
    const { outcome, events, socket } = await started();
    const shuffled = [HAPPY[1], HAPPY[0], HAPPY[3], HAPPY[2], HAPPY[2], HAPPY[0]];

    socket().receive(...shuffled, ...HAPPY.slice(4, 9), HAPPY[5], ...HAPPY.slice(9));

    expect(await outcome).toEqual({ value: frames.candidateResult });
    expect(events).toEqual(EXPECTED_EVENTS);
  });

  it("waits for a missing frame, then reports stream_failed", async () => {
    vi.useFakeTimers();
    const { outcome, events, socket } = await started();

    socket().receive(HAPPY[0], HAPPY[2]);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(events).toEqual([{ type: "started" }]);
    // Filling the first gap restarts the wait for the next one (event 2 is a span: no event).
    socket().receive(HAPPY[1], HAPPY[4]);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(events).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);

    expect(await rejection(outcome)).toMatchObject({
      kind: "stream_failed",
      message: "The Engine's event stream skipped event 4.",
    });
  });

  it("reports 120 seconds of silence as stream_failed, heartbeats included", async () => {
    vi.useFakeTimers();
    const { outcome, socket } = await started();

    await vi.advanceTimersByTimeAsync(119_000);
    socket().receive(frames.heartbeat);
    await vi.advanceTimersByTimeAsync(119_000);
    socket().receive(HAPPY[0]);
    await vi.advanceTimersByTimeAsync(119_999);
    expect(socket().closed).toBe(false);
    await vi.advanceTimersByTimeAsync(1);

    expect(await rejection(outcome)).toMatchObject({ kind: "stream_failed" });
  });

  it("stops on abort and settles on the Engine's terminated frame", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const { outcome, engine, socket } = await started({ signal: controller.signal });
    socket().receive(HAPPY[0], HAPPY[1], HAPPY[2]);

    controller.abort();

    expect(socket().sent[1]).toMatchObject({
      specversion: "1.0",
      type: "ai.url4.stop",
      data: { reason: "cancelled by user" },
    });
    socket().receive(frames.terminatedStopped);
    expect(await rejection(outcome)).toMatchObject({ kind: "stopped" });
    await vi.advanceTimersByTimeAsync(10_000);
    expect(engine.calls.some((call) => call.method === "DELETE")).toBe(false);
  });

  it("falls back to DELETE when no terminated frame arrives within 5 seconds", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const { outcome, engine } = await started({ signal: controller.signal });

    controller.abort();
    await vi.advanceTimersByTimeAsync(4_999);
    expect(engine.calls.some((call) => call.method === "DELETE")).toBe(false);
    await vi.advanceTimersByTimeAsync(1);

    expect(await rejection(outcome)).toMatchObject({ kind: "stopped" });
    const remove = engine.calls.find((call) => call.method === "DELETE");
    expect(remove?.url).toBe(`${BASE}/?topic=${TOPIC}`);
    expect(remove?.headers["URL4-Capability"]).toBe(TOKEN);
  });

  it("deletes the run at once when the socket closes while stopping", async () => {
    const controller = new AbortController();
    const { outcome, engine, socket } = await started({ signal: controller.signal });

    controller.abort();
    socket().onclose?.({});

    expect(await rejection(outcome)).toMatchObject({ kind: "stopped" });
    expect(engine.calls.at(-1)?.method).toBe("DELETE");
  });

  it("stops a run whose start was in flight when aborted", async () => {
    const controller = new AbortController();
    const { outcome, socket } = await launch({ signal: controller.signal });
    socket().open();
    controller.abort();
    await flush();

    expect(socket().sent[1]).toMatchObject({ type: "ai.url4.stop" });
    socket().receive(HAPPY[0], HAPPY[1], HAPPY[2], frames.terminatedStopped);
    expect(await rejection(outcome)).toMatchObject({ kind: "stopped" });
  });

  it("stops before starting when aborted while the socket connects", async () => {
    const controller = new AbortController();
    const { outcome, engine } = await launch({ signal: controller.signal });

    controller.abort();

    expect(await rejection(outcome)).toMatchObject({ kind: "stopped" });
    expect(engine.startCalls()).toHaveLength(0);
  });

  it("never starts when already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const { outcome, engine } = await launch({ signal: controller.signal });

    expect(await rejection(outcome)).toMatchObject({ kind: "stopped" });
    expect(engine.calls).toHaveLength(0);
  });

  it("keeps the token out of every error message", async () => {
    const echoes = [
      await started({ routes: { start: [() => problem(400, `bad capability ${TOKEN}`)] } }),
      await started(),
    ];
    echoes[1].socket().receive({
      ...frames.errorInvalidFrame,
      data: { code: "invalid_frame", message: `rejected ${TOKEN}`, ref_id: null },
    });

    for (const { outcome } of echoes) {
      const error = await rejection(outcome);
      expect(error.message).not.toContain(TOKEN);
      expect(error.detail).toContain("[redacted]");
    }
  });
});

describe("startRun failures", () => {
  it("reports an Engine that cannot be reached", async () => {
    const run = startRun({
      candidateUrl4: CANDIDATE,
      benchmarkId: "ifeval",
      limit: 1,
      useCache: true,
      deps: {
        fetch: (async () => {
          throw new TypeError("Failed to fetch");
        }) as unknown as typeof fetch,
        WebSocket: FakeSocket,
      },
    });

    await expect(run).rejects.toMatchObject({ kind: "unreachable" });
  });

  it("passes a refused benchmark request through with its detail", async () => {
    const { outcome } = await launch({
      routes: { benchmark: () => problem(422, "limit must be between 1 and 541 for 'ifeval'") },
    });

    expect(await rejection(outcome)).toMatchObject({
      kind: "failed",
      code: "http_422",
      message: "limit must be between 1 and 541 for 'ifeval'",
    });
  });

  it("rejects a benchmark without url4", async () => {
    const { outcome } = await launch({ routes: { benchmark: () => reply(200, { id: "x" }) } });
    expect(await rejection(outcome)).toMatchObject({ kind: "failed" });
  });

  it("rejects an unreadable Engine response", async () => {
    const { outcome } = await launch({ routes: { benchmark: () => reply(200, "not json{") } });
    expect(await rejection(outcome)).toMatchObject({ kind: "failed" });
  });

  it("reports a socket that fails to connect as unreachable", async () => {
    const { outcome, socket } = await launch();
    socket().onerror?.({});
    expect(await rejection(outcome)).toMatchObject({ kind: "unreachable" });
  });

  it("reports a socket that drops mid-run as stream_failed", async () => {
    const { outcome, socket } = await started();
    socket().onerror?.({});
    socket().onclose?.({});
    expect(await rejection(outcome)).toMatchObject({ kind: "stream_failed" });
  });

  it("reports a start request that cannot reach the Engine", async () => {
    const { outcome } = await started({
      routes: {
        start: [
          () => {
            throw new TypeError("Failed to fetch");
          },
        ],
      },
    });
    expect(await rejection(outcome)).toMatchObject({ kind: "unreachable" });
  });

  it.each([
    ["an unreadable frame", "{not json"],
    ["an Engine error frame", JSON.stringify(frames.errorInvalidFrame)],
  ])("reports %s as stream_failed", async (_name, raw) => {
    const { outcome, socket } = await started();
    socket().onmessage?.({ data: raw });
    expect(await rejection(outcome)).toMatchObject({ kind: "stream_failed" });
  });

  it("reports a run that succeeds without a result", async () => {
    const { outcome, socket } = await started();
    socket().receive(...HAPPY.slice(0, 10), { ...HAPPY[11], sequence: "11" });
    expect(await rejection(outcome)).toMatchObject({
      kind: "stream_failed",
      message: "The run ended without a result.",
    });
  });

  it.each([
    ["an unreadable body", { body: "not json", media_type: "application/json" }],
    ["an artifact with an unsafe id", { artifact: { id: "../x", size_bytes: 1, sha256: "x" } }],
  ])("reports a result with %s", async (_name, data) => {
    const { outcome, socket } = await started();
    socket().receive(...HAPPY.slice(0, 10), { ...HAPPY[10], data }, HAPPY[11]);
    expect(await rejection(outcome)).toMatchObject({ kind: "stream_failed" });
  });

  it("reports a terminal state it does not know", async () => {
    const { outcome, socket } = await started();
    socket().receive({ ...HAPPY[11], sequence: "1", data: { status: "exploded" } });
    expect(await rejection(outcome)).toMatchObject({ kind: "stream_failed" });
  });
});

describe("startRun events", () => {
  it("reports an ungraded score as null, plain logs and out-of-band logs", async () => {
    const { events, socket } = await started();
    const progress = HAPPY[8];
    const ungraded = {
      ...progress,
      data: {
        ...progress.data,
        attributes: {
          ...progress.data.attributes,
          "sf.progress.graded": 0,
          "sf.progress.score": null,
        },
      },
    };
    const plain = {
      ...progress,
      sequence: "2",
      data: { severity_number: 13, severity_text: "WARN", body: "slow provider", attributes: {} },
    };
    const advisory = { ...plain, sequence: null, sequencetype: null };
    const failedCall = {
      ...HAPPY[6],
      sequence: "3",
      data: {
        ...HAPPY[6].data,
        attributes: {
          ...HAPPY[6].data.attributes,
          "sf.activity.state": "failed",
          "sf.activity.failure_code": "provider_error",
        },
      },
    };
    const selfCost = { ...HAPPY[9], sequence: "4", data: { ...HAPPY[9].data, scope: "self" } };

    socket().receive({ ...ungraded, sequence: "1" }, plain, advisory, failedCall, selfCost);

    expect(events).toEqual([
      { type: "progress", completed: 1, graded: 0, score: null },
      { type: "log", severity: "WARN", body: "slow provider", attributes: {} },
      { type: "log", severity: "WARN", body: "slow provider", attributes: {} },
      expect.objectContaining({ type: "activity", state: "failed", failureCode: "provider_error" }),
    ]);
  });

  it("uses the runtime's Engine when none is given", async () => {
    FakeSocket.instances = [];
    const engine = fakeEngine();
    void startRun({
      candidateUrl4: CANDIDATE,
      benchmarkId: "ifeval",
      limit: 1,
      useCache: true,
      deps: { fetch: engine.fetch, WebSocket: FakeSocket },
    }).catch(() => undefined);
    await flush();

    expect(engine.calls[0].url).toBe(`${BASE}/v1/benchmarks/ifeval?limit=1`);
  });

  it("is a typed error", () => {
    const error = new RunError("stopped");
    expect(error).toBeInstanceOf(Error);
    expect(error.message).toBe("The run was stopped.");
    expect(isRunError(error)).toBe(true);
    expect(isRunError(new Error("x"))).toBe(false);
  });
});
