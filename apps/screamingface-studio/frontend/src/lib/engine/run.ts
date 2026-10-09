// Studio's client for one Engine run (spec §3, §4.2; plan T-B3). It speaks the same protocol
// as the SDK's transport (`screamingface/_engine/transport.py`, `run_lifecycle.py`):
//
//   1. GET  /v1/benchmarks/{id}?limit=N        → the Benchmark's url4 for exactly N cases
//   2. POST /token                             → a capability JWT whose `sub` is a fresh topic
//   3. WS   /ws?ticket=<token> (cloudevents.json), then send `ai.url4.attach`
//   4. GET  /?q=<linked url4>, Prefer: respond-async → 202; frames arrive on the socket
//   5. frames in `sequence` order until `ai.url4.result` + `ai.url4.terminated`
//
// AIDEV-NOTE: the capability token is a bearer secret. It is sent only in the `URL4-Capability`
// header and the socket URL, and every error message is scrubbed of it.

import { getEngineUrl } from "../runtime";
import { createUuid } from "../uuid";
import { problemDetail } from "./client";
import type { CandidateResult, LogAttributes, RunEvent } from "./run-types";
import { linkCandidate } from "./url4";

export type RunErrorKind = "failed" | "timed_out" | "stopped" | "unreachable" | "stream_failed";

const GENERIC_DETAIL: Record<RunErrorKind, string> = {
  failed: "The run failed.",
  timed_out: "The run took longer than the Engine allows.",
  stopped: "The run was stopped.",
  unreachable: "The ScreamingFace Engine could not be reached.",
  stream_failed: "The run's event stream from the Engine broke off.",
};

export class RunError extends Error {
  readonly kind: RunErrorKind;
  // The Engine's error code (`terminated.error.code`, an `ai.url4.error` code, or `http_<status>`
  // for a refused request), when it gave one.
  readonly code?: string;
  readonly detail: string;

  constructor(kind: RunErrorKind, detail?: string, code?: string) {
    const text = detail?.trim() || GENERIC_DETAIL[kind];
    super(text);
    this.name = "RunError";
    this.kind = kind;
    this.code = code;
    this.detail = text;
  }
}

export function isRunError(value: unknown): value is RunError {
  return value instanceof RunError;
}

// The parts of a browser WebSocket the run uses, so tests can drive a fake one.
export type RunSocket = {
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onclose: ((event: unknown) => void) | null;
};

export type RunDeps = {
  fetch: typeof fetch;
  WebSocket: new (url: string, protocols: string[]) => RunSocket;
  now: () => number;
  setTimeout: (callback: () => void, ms: number) => unknown;
  clearTimeout: (handle: unknown) => void;
  // The Engine's http(s) origin. Defaults to `getEngineUrl()`.
  engineUrl?: string;
};

export type StartRunOptions = {
  candidateUrl4: string;
  benchmarkId: string;
  limit: number;
  // On: the run reads and writes AI Gateway's cache. Off: it does neither (spec D9).
  useCache: boolean;
  onEvent?: (event: RunEvent) => void;
  signal?: AbortSignal;
  deps?: Partial<RunDeps>;
};

const SUBPROTOCOL = "cloudevents.json";
const PROGRESS_SCHEMA = "screamingface.benchmark-progress.v1";
const ACTIVITY_PREFIX = "sf.activity.";
// U4: the Engine answers 428 until the socket's attach has registered; the SDK re-sends.
const ATTACH_RETRIES = 5;
const ATTACH_RETRY_MS = 100;
// U5, matching the SDK: 120 s with no frame at all is a dead stream (the Engine heartbeats).
const SILENCE_MS = 120_000;
// A missing sequence number this long is a frame that is not coming.
const GAP_MS = 2_000;
// U5: after a stop frame, wait this long for `terminated`, then fall back to `DELETE /`.
const STOP_WAIT_MS = 5_000;
const ARTIFACT_ID = /^[0-9a-f]{64}$/;

function defaultDeps(overrides: Partial<RunDeps> = {}): RunDeps {
  // WHY late-bound: resolved per call, so fake timers installed by a test after import apply.
  return {
    fetch: (...args) => globalThis.fetch(...args),
    WebSocket: globalThis.WebSocket as unknown as RunDeps["WebSocket"],
    now: () => Date.now(),
    setTimeout: (callback, ms) => globalThis.setTimeout(callback, ms),
    clearTimeout: (handle) =>
      globalThis.clearTimeout(handle as ReturnType<typeof globalThis.setTimeout>),
    ...overrides,
  };
}

// The token's `sub` is the run's topic. Read without verifying: the Engine verifies it.
function topicOf(token: string): string | null {
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload.padEnd(Math.ceil(payload.length / 4) * 4, "=");
    const sub: unknown = JSON.parse(atob(padded)).sub;
    return typeof sub === "string" && sub ? sub : null;
  } catch {
    return null;
  }
}

function command(type: string, data: Record<string, unknown>, now: number): string {
  // Mirrors the SDK's `run_lifecycle._command`: a CloudEvents 1.0 JSON envelope.
  return JSON.stringify({
    specversion: "1.0",
    id: createUuid(),
    source: "/screamingface/studio",
    time: new Date(now).toISOString(),
    type,
    datacontenttype: "application/json",
    data,
  });
}

type Frame = { type?: unknown; sequence?: unknown; data?: unknown };

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function text(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

// `sequence` is a positive integer string on the wire (`sequencetype: "Integer"`); a number is
// accepted too. Null means an unsequenced frame (heartbeat, error, an advisory log).
function sequenceOf(frame: Frame): number | null {
  const value = frame.sequence;
  const parsed =
    typeof value === "number" ? value : typeof value === "string" && /^\d+$/.test(value) ? Number(value) : NaN;
  return Number.isSafeInteger(parsed) && parsed >= 1 ? parsed : null;
}

function logEvent(data: Record<string, unknown>): RunEvent {
  const attributes = record(data.attributes) as LogAttributes;
  const body = text(data.body) ?? "";
  if (attributes["sf.progress.schema"] === PROGRESS_SCHEMA) {
    const score = attributes["sf.progress.score"];
    return {
      type: "progress",
      completed: Number(attributes["sf.progress.completed"] ?? 0),
      graded: Number(attributes["sf.progress.graded"] ?? 0),
      score: typeof score === "number" ? score : null,
    };
  }
  const kind = attributes[`${ACTIVITY_PREFIX}kind`];
  const state = attributes[`${ACTIVITY_PREFIX}state`];
  if (typeof kind === "string" && typeof state === "string") {
    const caseId = attributes[`${ACTIVITY_PREFIX}case_id`];
    const modelId = attributes[`${ACTIVITY_PREFIX}model_id`];
    const failureCode = attributes[`${ACTIVITY_PREFIX}failure_code`];
    return {
      type: "activity",
      kind,
      state,
      body,
      ...(typeof caseId === "string" || typeof caseId === "number" ? { caseId } : {}),
      ...(typeof modelId === "string" ? { modelId } : {}),
      ...(typeof failureCode === "string" ? { failureCode } : {}),
    };
  }
  return { type: "log", severity: text(data.severity_text) ?? "INFO", body, attributes };
}

function parseResult(body: string): CandidateResult {
  try {
    const value: unknown = JSON.parse(body);
    if (value && typeof value === "object" && Array.isArray((value as CandidateResult).cases)) {
      return value as CandidateResult;
    }
  } catch {
    // Reported below.
  }
  throw new RunError("stream_failed", "The Engine sent a result Studio could not read.");
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

export async function startRun(options: StartRunOptions): Promise<CandidateResult> {
  const { candidateUrl4, benchmarkId, limit, useCache, onEvent, signal } = options;
  const deps = defaultDeps(options.deps);
  if (signal?.aborted) throw new RunError("stopped");

  let origin: string;
  try {
    origin = (deps.engineUrl ?? (await getEngineUrl())).replace(/\/+$/, "");
  } catch {
    throw new RunError("unreachable");
  }

  async function call(path: string, init: RequestInit = {}): Promise<Record<string, unknown>> {
    let response: Response;
    try {
      response = await deps.fetch(`${origin}${path}`, {
        ...init,
        headers: { accept: "application/json", ...init.headers },
        cache: "no-store",
        signal,
      });
    } catch {
      throw new RunError(signal?.aborted ? "stopped" : "unreachable");
    }
    if (!response.ok) {
      throw new RunError("failed", await problemDetail(response), `http_${response.status}`);
    }
    try {
      return record(await response.json());
    } catch {
      throw new RunError("failed", "The Engine returned an unexpected response.");
    }
  }

  const benchmark = await call(
    `/v1/benchmarks/${encodeURIComponent(benchmarkId)}?limit=${encodeURIComponent(limit)}`,
  );
  const benchmarkUrl4 = text(benchmark.url4);
  if (!benchmarkUrl4) throw new RunError("failed", "The Engine returned no url4 for this benchmark.");
  const token = text((await call("/token", { method: "POST" })).token);
  if (!token) throw new RunError("failed", "The Engine returned no capability token.");
  if (signal?.aborted) throw new RunError("stopped");

  return runOnSocket({
    deps,
    origin,
    token,
    linked: linkCandidate(candidateUrl4, benchmarkUrl4),
    useCache,
    onEvent,
    signal,
  });
}

type SocketRun = {
  deps: RunDeps;
  origin: string;
  token: string;
  linked: string;
  useCache: boolean;
  onEvent?: (event: RunEvent) => void;
  signal?: AbortSignal;
};

function runOnSocket(run: SocketRun): Promise<CandidateResult> {
  const { deps, origin, token, linked, useCache, onEvent, signal } = run;
  const capability = { "URL4-Capability": token };

  return new Promise<CandidateResult>((resolve, reject) => {
    let socket: RunSocket | null = null;
    let settled = false;
    let opened = false;
    let started = false;
    let starting = false;
    let abortRequested = false;
    let stopping = false;
    let terminated = false;
    let lastSequence = 0;
    const pending = new Map<number, Frame>();
    let result: Promise<CandidateResult> | null = null;
    const timers: { silence?: unknown; gap?: unknown; stop?: unknown } = {};

    function clear(name: keyof typeof timers) {
      if (timers[name] !== undefined) deps.clearTimeout(timers[name]);
      timers[name] = undefined;
    }

    function scrub(error: RunError): RunError {
      return error.detail.includes(token)
        ? new RunError(error.kind, error.detail.split(token).join("[redacted]"), error.code)
        : error;
    }

    function settle(outcome: { value: CandidateResult } | { error: RunError }) {
      if (settled) return;
      settled = true;
      clear("silence");
      clear("gap");
      clear("stop");
      signal?.removeEventListener("abort", onAbort);
      if (socket) {
        socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
        try {
          socket.close(1000);
        } catch {
          // Already closed.
        }
      }
      if ("value" in outcome) resolve(outcome.value);
      else reject(scrub(outcome.error));
    }

    function fail(kind: RunErrorKind, detail?: string, code?: string) {
      settle({ error: new RunError(kind, detail, code) });
    }

    function armSilence() {
      clear("silence");
      if (terminated) return;
      timers.silence = deps.setTimeout(
        () => fail("stream_failed", "The Engine sent nothing for 120 seconds."),
        SILENCE_MS,
      );
    }

    async function deleteRun() {
      const topic = topicOf(token);
      try {
        await deps.fetch(`${origin}/${topic ? `?topic=${encodeURIComponent(topic)}` : ""}`, {
          method: "DELETE",
          headers: capability,
          cache: "no-store",
        });
      } catch {
        // The run is being abandoned either way; the Engine reaps an unwatched run.
      }
      fail("stopped");
    }

    function requestStop() {
      if (stopping || settled) return;
      stopping = true;
      try {
        socket?.send(command("ai.url4.stop", { reason: "cancelled by user" }, deps.now()));
      } catch {
        // The socket is gone; the DELETE fallback below still stops the run.
      }
      timers.stop = deps.setTimeout(() => void deleteRun(), STOP_WAIT_MS);
    }

    function onAbort() {
      abortRequested = true;
      if (started) requestStop();
      else if (!starting) fail("stopped");
      // A start in flight: `begin` stops the run once the Engine has accepted it.
    }

    async function begin() {
      starting = true;
      const headers: Record<string, string> = { ...capability, Prefer: "respond-async" };
      if (!useCache) headers["Cache-Control"] = "no-store";
      for (let attempt = 0; ; attempt += 1) {
        let response: Response;
        try {
          response = await deps.fetch(`${origin}/?q=${encodeURIComponent(linked)}`, {
            method: "GET",
            headers,
            cache: "no-store",
          });
        } catch {
          return fail("unreachable");
        }
        if (settled) return;
        if (response.status === 202) {
          started = true;
          starting = false;
          if (abortRequested) requestStop();
          return;
        }
        const detail = await problemDetail(response);
        const registering =
          response.status === 428 && Boolean(detail?.toLowerCase().includes("attach a websocket"));
        if (!registering || attempt >= ATTACH_RETRIES) {
          return fail("failed", detail, `http_${response.status}`);
        }
        await new Promise<void>((wake) => deps.setTimeout(wake, ATTACH_RETRY_MS));
        if (settled) return;
        if (abortRequested) return fail("stopped");
      }
    }

    async function readResult(data: Record<string, unknown>): Promise<CandidateResult> {
      const body = text(data.body);
      if (body !== undefined) return parseResult(body);
      const artifact = record(data.artifact);
      const id = text(artifact.id);
      if (!id || !ARTIFACT_ID.test(id)) {
        throw new RunError("stream_failed", "The Engine sent a result Studio could not read.");
      }
      let response: Response;
      try {
        response = await deps.fetch(`${origin}/artifacts/${id}`, {
          headers: capability,
          cache: "no-store",
        });
      } catch {
        throw new RunError("unreachable", "The run's result could not be fetched from the Engine.");
      }
      if (!response.ok) {
        throw new RunError(
          "stream_failed",
          (await problemDetail(response)) ?? "The Engine would not hand over the run's result.",
          `http_${response.status}`,
        );
      }
      // INVARIANT (as the SDK's `_verified_artifact_text`): byte count and sha256 both match
      // the claim ticket, or nothing is decoded.
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.length !== artifact.size_bytes || (await sha256Hex(bytes)) !== artifact.sha256) {
        throw new RunError("stream_failed", "The run's result failed its integrity check.");
      }
      return parseResult(new TextDecoder().decode(bytes));
    }

    async function onTerminated(data: Record<string, unknown>) {
      terminated = true;
      clear("silence");
      clear("gap");
      const status = data.status;
      const error = record(data.error);
      const message = text(error.message);
      const code = text(error.code);
      if (status === "succeeded") {
        if (!result) return fail("stream_failed", "The run ended without a result.");
        try {
          settle({ value: await result });
        } catch (caught) {
          settle({ error: isRunError(caught) ? caught : new RunError("stream_failed") });
        }
      } else if (status === "failed" || status === "timed_out" || status === "stopped") {
        fail(status, message, code);
      } else {
        fail("stream_failed", "The run ended in a state Studio does not know.");
      }
    }

    function dispatch(frame: Frame) {
      const data = record(frame.data);
      switch (frame.type) {
        case "ai.url4.started":
          onEvent?.({ type: "started" });
          break;
        case "ai.url4.log":
          onEvent?.(logEvent(data));
          break;
        case "ai.url4.cost.usage": {
          const total = Number(text(record(data.cost).total_usd));
          if (data.scope === "subtree" && Number.isFinite(total)) {
            onEvent?.({ type: "cost", totalUsd: total });
          }
          break;
        }
        case "ai.url4.result":
          result = readResult(data);
          // Handled when `terminated` arrives; this only keeps an early failure from going
          // unobserved.
          result.catch(() => undefined);
          break;
        case "ai.url4.terminated":
          void onTerminated(data);
          break;
        default:
          // Spans and anything newer: not used by Studio yet.
          break;
      }
    }

    function drain() {
      const before = lastSequence;
      while (!settled && !terminated && pending.has(lastSequence + 1)) {
        const frame = pending.get(lastSequence + 1) as Frame;
        pending.delete(lastSequence + 1);
        lastSequence += 1;
        dispatch(frame);
      }
      if (pending.size === 0 || terminated) {
        clear("gap");
      } else if (timers.gap === undefined || lastSequence !== before) {
        clear("gap");
        timers.gap = deps.setTimeout(
          () => fail("stream_failed", `The Engine's event stream skipped event ${lastSequence + 1}.`),
          GAP_MS,
        );
      }
    }

    function onFrame(raw: unknown) {
      if (settled || terminated) return;
      armSilence();
      let frame: Frame;
      try {
        frame = record(JSON.parse(String(raw)));
      } catch {
        return fail("stream_failed", "The Engine sent a frame Studio could not read.");
      }
      if (frame.type === "ai.url4.heartbeat") return;
      if (frame.type === "ai.url4.error") {
        const data = record(frame.data);
        return fail("stream_failed", text(data.message), text(data.code));
      }
      const sequence = sequenceOf(frame);
      if (sequence === null) {
        // Only a log may arrive out of band (an advisory notice); it changes no run state.
        if (frame.type === "ai.url4.log") dispatch(frame);
        return;
      }
      if (sequence <= lastSequence || pending.has(sequence)) return; // a duplicate
      pending.set(sequence, frame);
      drain();
    }

    signal?.addEventListener("abort", onAbort);
    try {
      socket = new deps.WebSocket(
        `${origin.replace(/^http/i, "ws")}/ws?ticket=${encodeURIComponent(token)}`,
        [SUBPROTOCOL],
      );
    } catch {
      return fail("unreachable");
    }
    socket.onopen = () => {
      opened = true;
      // `from_sequence` must be null or >= 1: 0 is refused as `invalid_frame` and the socket
      // then carries nothing (checked live 2026-10-05).
      socket?.send(
        command(
          "ai.url4.attach",
          { from_sequence: null, cache: { participate: useCache } },
          deps.now(),
        ),
      );
      armSilence();
      if (abortRequested) return fail("stopped");
      void begin();
    };
    socket.onmessage = (event) => onFrame(event.data);
    socket.onerror = () => {
      if (!opened) fail("unreachable");
    };
    socket.onclose = () => {
      if (settled || terminated) return;
      if (stopping) {
        clear("stop");
        void deleteRun();
      } else {
        fail(opened ? "stream_failed" : "unreachable");
      }
    };
  });
}
