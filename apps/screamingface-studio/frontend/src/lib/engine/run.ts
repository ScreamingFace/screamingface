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
import { type RequestOptions, engineRequest, problemDetail, redact } from "./client";
import { isEngineError } from "./errors";
import { checkCandidateResult } from "./run-result";
import type { CandidateResult, LogAttributes, RunEvent } from "./run-types";
import { linkCandidate } from "./url4";

export type RunErrorKind =
  | "failed"
  | "timed_out"
  | "stopped"
  // Studio asked the Engine to stop the run, and could not confirm that it did.
  | "stop_unconfirmed"
  | "unreachable"
  | "stream_failed"
  // The result arrived but breaks the `CandidateResult` contract; the detail names the field.
  | "invalid_result";

const GENERIC_DETAIL: Record<RunErrorKind, string> = {
  failed: "The run failed.",
  timed_out: "The run took longer than the Engine allows.",
  stopped: "The run was stopped.",
  stop_unconfirmed:
    "Studio asked the Engine to stop the run but could not confirm that it stopped.",
  unreachable: "The ScreamingFace Engine could not be reached.",
  stream_failed: "The run's event stream from the Engine broke off.",
  invalid_result: "The Engine sent a result Studio could not read.",
};

export class RunError extends Error {
  readonly kind: RunErrorKind;
  // The Engine's error code (`terminated.error.code`, an `ai.url4.error` code, or `http_<status>`
  // for a refused request), when it gave one.
  readonly code?: string;
  readonly detail: string;
  // Set when the run failed on Studio's side (the socket broke, the stream went silent or
  // skipped a frame, the Engine sent an error frame) after the Engine had accepted it: Studio
  // then stopped the Engine's run with `DELETE /`, and this says whether the Engine confirmed
  // it ("stopped") or not ("unconfirmed"). Unset when no cleanup was needed.
  readonly cleanup?: "stopped" | "unconfirmed";

  constructor(
    kind: RunErrorKind,
    detail?: string,
    code?: string,
    cleanup?: "stopped" | "unconfirmed",
  ) {
    const text = detail?.trim() || GENERIC_DETAIL[kind];
    super(text);
    this.name = "RunError";
    this.kind = kind;
    this.code = code;
    this.detail = text;
    this.cleanup = cleanup;
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
// The SDK's HTTP timeout for every Engine request (`_engine/transport.py:141`, `timeout=30.0`),
// used here as the whole deadline of one start request and of one artifact fetch.
const REQUEST_DEADLINE_MS = 30_000;
// The SDK's stop request timeout (`transport.py:62`, `_STOP_TIMEOUT_SECONDS = 5.0`).
const DELETE_DEADLINE_MS = 5_000;
// The SDK treats these answers to a stop as "it is not running" (`transport.py:64`).
const ALREADY_STOPPED = new Set([404, 409, 410]);
// The SDK's artifact fetch retries (`transport.py:1265`, `_ARTIFACT_FETCH_RETRY_DELAYS`).
const ARTIFACT_RETRY_DELAYS_MS = [0, 200, 800];
// The largest result artifact Studio will hold. A full ContractEval run (4,182 cases over a
// 209 MB dataset, spec D10) can approach this, while the decoded text stays well below V8's
// maximum string length (2^29 - 24 UTF-16 units, about 512 Mi), so decoding and `JSON.parse`
// cannot throw a RangeError. The Engine itself sets no cap on artifacts.
export const MAX_ARTIFACT_BYTES = 256 * 1024 * 1024;
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

type Frame = { type?: unknown; source?: unknown; sequence?: unknown; data?: unknown };

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
  let value: unknown;
  try {
    value = JSON.parse(body);
  } catch {
    throw new RunError("invalid_result", "The Engine's result is not JSON.", "invalid_result");
  }
  const checked = checkCandidateResult(value);
  if (!checked.ok) {
    throw new RunError(
      "invalid_result",
      `The Engine's result has an invalid \`${checked.field}\`.`,
      "invalid_result",
    );
  }
  return checked.value;
}

const TIMED_OUT = Symbol("timed out");
const UNREACHABLE = Symbol("unreachable");

// `work` with a deadline: it gets an AbortSignal that fires when `ms` passes, and the result is
// `TIMED_OUT` if the deadline wins.
async function withDeadline<T>(
  deps: RunDeps,
  ms: number,
  work: (signal: AbortSignal) => Promise<T>,
): Promise<T | typeof TIMED_OUT> {
  const controller = new AbortController();
  let timer: unknown;
  const deadline = new Promise<typeof TIMED_OUT>((resolve) => {
    timer = deps.setTimeout(() => {
      controller.abort();
      resolve(TIMED_OUT);
    }, ms);
  });
  const attempt = work(controller.signal);
  // Once the deadline wins, the aborted attempt's own rejection is expected and unobserved.
  attempt.catch(() => undefined);
  try {
    return await Promise.race([attempt, deadline]);
  } finally {
    deps.clearTimeout(timer);
  }
}

function concat(chunks: Uint8Array[], length: number): Uint8Array {
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return bytes;
}

// Read a response body without ever holding more than `limit` bytes: the stream is cancelled
// as soon as it passes the limit. `read` bounds each wait for the next chunk (the inactivity
// deadline); `TIMED_OUT` means the body stalled.
async function readAtMost(
  response: Response,
  limit: number,
  read: <T>(next: () => Promise<T>) => Promise<T | typeof TIMED_OUT>,
): Promise<Uint8Array | typeof TIMED_OUT> {
  if (!response.body) {
    const buffer = await read(() => response.arrayBuffer());
    if (buffer === TIMED_OUT) return TIMED_OUT;
    const bytes = new Uint8Array(buffer);
    if (bytes.length > limit) throw new RunError("stream_failed", OVERSIZE);
    return bytes;
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  for (;;) {
    const chunk = await read(() => reader.read());
    if (chunk === TIMED_OUT) {
      void reader.cancel().catch(() => undefined);
      return TIMED_OUT;
    }
    if (chunk.done) return concat(chunks, length);
    length += chunk.value.length;
    if (length > limit) {
      void reader.cancel().catch(() => undefined);
      throw new RunError("stream_failed", OVERSIZE);
    }
    chunks.push(chunk.value);
  }
}

const OVERSIZE = "The run's result is larger than its claim ticket said.";

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

  // Through the client's one request path (problem+json detail, redaction); its EngineError
  // becomes a RunError here.
  async function call(path: string, options: RequestOptions = {}): Promise<Record<string, unknown>> {
    try {
      return record(await engineRequest(deps.fetch, origin, path, { ...options, signal }));
    } catch (error) {
      if (!isEngineError(error)) throw error;
      if (error.kind === "unreachable") throw new RunError(signal?.aborted ? "stopped" : "unreachable");
      const refused = error.status !== undefined && error.status >= 400;
      throw new RunError(
        "failed",
        refused ? error.engineDetail : "The Engine returned an unexpected response.",
        refused ? `http_${error.status}` : undefined,
      );
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
    // A local failure after the start: the DELETE cleanup is in flight, nothing else counts.
    let closing = false;
    // Aborts an artifact download when the caller aborts after the root has terminated.
    const download = new AbortController();
    let lastSequence = 0;
    const pending = new Map<number, Frame>();
    let result: Promise<CandidateResult> | null = null;
    let rootSource: string | null = null;
    const timers: { silence?: unknown; gap?: unknown; stop?: unknown } = {};

    function clear(name: keyof typeof timers) {
      if (timers[name] !== undefined) deps.clearTimeout(timers[name]);
      timers[name] = undefined;
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
      else {
        const { kind, detail, code, cleanup } = outcome.error;
        reject(new RunError(kind, redact(detail, token), code, cleanup));
      }
    }

    function fail(kind: RunErrorKind, detail?: string, code?: string) {
      if (settled || closing) return;
      const error = new RunError(kind, detail, code);
      // Studio gave up on a run the Engine accepted and is still running (no root `terminated`
      // yet, and no stop of its own under way): stop the Engine's paid work too, with the same
      // bounded DELETE as a user stop, and report the original failure with the outcome.
      if (started && !terminated && !stopping) void cleanUp(error);
      else settle({ error });
    }

    async function cleanUp(error: RunError) {
      closing = true;
      clear("silence");
      clear("gap");
      const cleanup = await deleteRun();
      settle({ error: new RunError(error.kind, error.detail, error.code, cleanup) });
    }

    function armSilence() {
      clear("silence");
      if (terminated) return;
      timers.silence = deps.setTimeout(
        () => fail("stream_failed", "The Engine sent nothing for 120 seconds."),
        SILENCE_MS,
      );
    }

    // `DELETE /` with the capability: the REST stop. "stopped" when the Engine confirms it, or
    // says the run is already gone (as the SDK's `_require_stopped`); otherwise "unconfirmed".
    async function deleteRun(): Promise<"stopped" | "unconfirmed"> {
      const topic = topicOf(token);
      const url = `${origin}/${topic ? `?topic=${encodeURIComponent(topic)}` : ""}`;
      try {
        const response = await withDeadline(deps, DELETE_DEADLINE_MS, (deadline) =>
          deps.fetch(url, {
            method: "DELETE",
            headers: capability,
            cache: "no-store",
            signal: deadline,
          }),
        );
        if (response === TIMED_OUT) return "unconfirmed";
        return response.ok || ALREADY_STOPPED.has(response.status) ? "stopped" : "unconfirmed";
      } catch {
        return "unconfirmed";
      }
    }

    async function stopOverHttp() {
      const outcome = await deleteRun();
      // The root's `terminated` won the race: its outcome stands.
      if (terminated) return;
      fail(outcome === "stopped" ? "stopped" : "stop_unconfirmed");
    }

    function requestStop() {
      if (stopping || settled || closing || terminated) return;
      stopping = true;
      try {
        socket?.send(command("ai.url4.stop", { reason: "cancelled by user" }, deps.now()));
      } catch {
        // The socket is gone; the DELETE fallback below still stops the run.
      }
      timers.stop = deps.setTimeout(() => void stopOverHttp(), STOP_WAIT_MS);
    }

    function onAbort() {
      abortRequested = true;
      if (terminated) {
        // The run already ended on the Engine: nothing to stop and no DELETE. Studio only stops
        // waiting for the result's download.
        download.abort();
        fail("stopped");
      } else if (started) requestStop();
      else if (!starting) fail("stopped");
      // A start in flight: `begin` settles it once the Engine answers or the deadline passes.
    }

    async function begin() {
      starting = true;
      const headers: Record<string, string> = { ...capability, Prefer: "respond-async" };
      if (!useCache) headers["Cache-Control"] = "no-store";
      for (let attempt = 0; ; attempt += 1) {
        let response: Response | typeof TIMED_OUT;
        try {
          response = await withDeadline(deps, REQUEST_DEADLINE_MS, (deadline) =>
            deps.fetch(`${origin}/?q=${encodeURIComponent(linked)}`, {
              method: "GET",
              headers,
              cache: "no-store",
              signal: deadline,
            }),
          );
        } catch {
          return fail(abortRequested ? "stopped" : "unreachable");
        }
        if (settled || closing) {
          // Accepted after Studio already gave up on this run: stop it rather than orphan it.
          if (response !== TIMED_OUT && response.status === 202) void deleteRun();
          return;
        }
        if (response === TIMED_OUT) {
          // The Engine may have accepted the run without answering: stop it over HTTP, so no
          // run is left going with nobody watching it.
          const outcome = await deleteRun();
          if (abortRequested) return fail(outcome === "stopped" ? "stopped" : "stop_unconfirmed");
          return fail("unreachable", "The Engine did not answer the run's start within 30 seconds.");
        }
        if (response.status === 202) {
          started = true;
          starting = false;
          // Accepted after the user aborted: stop the run that just began.
          if (abortRequested) requestStop();
          return;
        }
        if (abortRequested) return fail("stopped");
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

    // One artifact fetch. `UNREACHABLE` is a failure worth retrying (the SDK retries any
    // transport failure); a `RunError` is final. The deadline is for inactivity, as the SDK's
    // httpx timeout is per connect/read: 30 s for the headers, then 30 s between chunks.
    async function fetchArtifactOnce(
      id: string,
      size: number,
      sha256: string,
    ): Promise<string | typeof UNREACHABLE> {
      const controller = new AbortController();
      const cancel = () => controller.abort();
      download.signal.addEventListener("abort", cancel);
      const read = <T,>(next: () => Promise<T>) =>
        withDeadline(deps, REQUEST_DEADLINE_MS, () => next()).then((value) => {
          if (value === TIMED_OUT) cancel();
          return value;
        });
      try {
        let response: Response | typeof TIMED_OUT;
        try {
          response = await read(() =>
            deps.fetch(`${origin}/artifacts/${id}`, {
              headers: capability,
              cache: "no-store",
              signal: controller.signal,
            }),
          );
        } catch {
          return UNREACHABLE;
        }
        if (response === TIMED_OUT) return UNREACHABLE;
        if (!response.ok) {
          throw new RunError(
            "stream_failed",
            (await problemDetail(response)) ?? "The Engine would not hand over the run's result.",
            `http_${response.status}`,
          );
        }
        // A declared length that disagrees with the ticket is refused before any byte is read.
        // (An encoded body's Content-Length counts the encoded bytes, so it is not compared.)
        const declared = response.headers.get("content-length");
        if (
          declared !== null &&
          !response.headers.get("content-encoding") &&
          Number(declared) !== size
        ) {
          throw new RunError("stream_failed", OVERSIZE);
        }
        let bytes: Uint8Array | typeof TIMED_OUT;
        try {
          bytes = await readAtMost(response, size, read);
        } catch (error) {
          if (isRunError(error)) throw error;
          return UNREACHABLE;
        }
        if (bytes === TIMED_OUT) return UNREACHABLE;
        // INVARIANT (as the SDK's `_verified_artifact_text`): byte count and sha256 both match
        // the claim ticket, or nothing is decoded.
        if (bytes.length !== size || (await sha256Hex(bytes)) !== sha256) {
          throw new RunError("stream_failed", "The run's result failed its integrity check.");
        }
        try {
          return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        } catch {
          throw new RunError("stream_failed", "The run's result is not UTF-8 text.");
        }
      } finally {
        download.signal.removeEventListener("abort", cancel);
      }
    }

    async function readResult(data: Record<string, unknown>): Promise<CandidateResult> {
      const body = text(data.body);
      if (body !== undefined) return parseResult(body);
      const artifact = record(data.artifact);
      const id = text(artifact.id);
      const sha256 = text(artifact.sha256);
      const size = artifact.size_bytes;
      if (!id || !ARTIFACT_ID.test(id) || !sha256 || !ARTIFACT_ID.test(sha256)) {
        throw new RunError("stream_failed", "The Engine sent a result Studio could not read.");
      }
      if (typeof size !== "number" || !Number.isSafeInteger(size) || size < 1) {
        throw new RunError("stream_failed", "The Engine sent a result Studio could not read.");
      }
      if (size > MAX_ARTIFACT_BYTES) {
        throw new RunError(
          "stream_failed",
          `The run's result is ${Math.ceil(size / 2 ** 20)} MiB, more than the ${MAX_ARTIFACT_BYTES / 2 ** 20} MiB Studio can hold.`,
        );
      }
      for (const delay of ARTIFACT_RETRY_DELAYS_MS) {
        if (delay) await new Promise<void>((wake) => deps.setTimeout(wake, delay));
        if (settled) break;
        const fetched = await fetchArtifactOnce(id, size, sha256);
        if (fetched !== UNREACHABLE) return parseResult(fetched);
      }
      throw new RunError("unreachable", "The run's result could not be fetched from the Engine.");
    }

    async function onTerminated(data: Record<string, unknown>) {
      terminated = true;
      clear("silence");
      clear("gap");
      // A stop requested before the root ended is moot now; it must not replace the outcome.
      clear("stop");
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

    // The run's root node is the one whose `started` frame names exactly the url4 Studio sent;
    // its `source` then marks the root's result, cost and terminal state. Fusion members and
    // pipeline stages run as child nodes with lifecycle frames of their own, which never end
    // the run or replace its result. This is the SDK's rule (`_engine/contract.py` `_started`,
    // `_result_event`, `_terminated`, `_usage`).
    function dispatch(frame: Frame) {
      const data = record(frame.data);
      const source = text(frame.source) ?? "";
      const fromRoot = rootSource !== null && source === rootSource;
      switch (frame.type) {
        case "ai.url4.started":
          if (rootSource === null && data.url4 === linked) {
            rootSource = source;
            onEvent?.({ type: "started" });
          } else if (fromRoot) {
            fail("stream_failed", "The Engine started this run's root node twice.");
          }
          break;
        case "ai.url4.log":
          onEvent?.(logEvent(data));
          break;
        case "ai.url4.cost.usage": {
          const total = Number(text(record(data.cost).total_usd));
          if (fromRoot && data.scope === "subtree" && Number.isFinite(total)) {
            onEvent?.({ type: "cost", totalUsd: total });
          }
          break;
        }
        case "ai.url4.result":
          if (!fromRoot) break;
          if (result) {
            fail("stream_failed", "The Engine sent this run's result twice.");
            break;
          }
          result = readResult(data);
          // Handled when `terminated` arrives; this only keeps an early failure from going
          // unobserved.
          result.catch(() => undefined);
          break;
        case "ai.url4.terminated":
          // WHY (as the SDK): without a root, heartbeats could keep an unrecognised run open.
          if (rootSource === null) {
            fail("stream_failed", "The Engine never started this run's root node.");
          } else if (fromRoot) {
            void onTerminated(data);
          }
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
      if (settled || terminated || closing) return;
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
        void stopOverHttp();
      } else {
        fail(opened ? "stream_failed" : "unreachable");
      }
    };
  });
}
