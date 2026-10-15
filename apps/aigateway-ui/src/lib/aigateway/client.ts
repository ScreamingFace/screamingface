import "server-only";

import { headers } from "next/headers";

import { log } from "@/lib/log";

import { AdminApiError, REFUSALS, classify, messageFor } from "./errors";
import type { components } from "./schema";

/**
 * The typed, server-only client for aigateway's `/v1/admin` surface.
 *
 * INVARIANT: `import "server-only"` on the first line is the load-bearing part of the BFF. If any
 * Client Component ever imports this module — directly or transitively — the BUILD fails rather
 * than shipping the admin API's address and the caller's verified identity into a browser bundle.
 * That is a compile-time guarantee, not a convention someone has to remember.
 *
 * INVARIANT: `X-User-Email` is READ from the incoming request and forwarded. It is never
 * constructed, defaulted, or taken from user input. Envoy is the only thing entitled to set it,
 * having re-verified Cloudflare Access's assertion against Cloudflare's JWKS.
 */

export { AdminApiError, type AdminErrorKind } from "./errors";

export type AdminAccount = components["schemas"]["AdminAccountOut"];
export type AdminAccountList = components["schemas"]["AdminAccountList"];
export type AdminConnection = components["schemas"]["AdminConnectionOut"];
export type AdminConnectionConflict = components["schemas"]["AdminConnectionConflictOut"];
export type AdminConnectionList = components["schemas"]["AdminConnectionList"];

/** The identity header Envoy injects. Mirrors `HEADER_USER_EMAIL` in aigateway. */
const IDENTITY_HEADER = "x-user-email";

/** The per-request id Envoy stamps on every request it routes. Read, never minted, here. */
const REQUEST_ID_HEADER = "x-request-id";

function baseUrl(): string {
  const configured = process.env.AIGATEWAY_ADMIN_BASE_URL;
  if (!configured) {
    throw new AdminApiError(
      "unavailable",
      0,
      "AIGATEWAY_ADMIN_BASE_URL is not set, so this console does not know where the gateway is.",
    );
  }
  return configured.replace(/\/$/, "");
}

/**
 * The verified address of whoever is using the console right now.
 *
 * Returns null rather than throwing so `requireAdmin` owns the "what does absence mean" decision —
 * it differs between local development and a deployed mesh.
 */
export async function callerEmail(): Promise<string | null> {
  const incoming = await headers();
  const value = incoming.get(IDENTITY_HEADER)?.trim();
  if (value) return value;

  // Local development only. There is no Envoy in front of `npm run dev`, so without this every
  // request 401s and the console cannot be exercised at all.
  //
  // INVARIANT: hard-gated on NODE_ENV, checked here rather than at module scope so a production
  // build cannot be tricked into reading it by setting the variable at runtime. `next build` sets
  // NODE_ENV=production, so this branch is unreachable in the shipped image — and even if it were
  // reached, aigateway independently refuses header identity from outside AIGW_ALLOWED_NETWORKS.
  // Two failures would have to line up for this to matter.
  if (process.env.NODE_ENV !== "production") {
    const devEmail = process.env.AIGATEWAY_DEV_USER_EMAIL?.trim();
    if (devEmail) return devEmail;
  }
  return null;
}

/**
 * Run one admin call; if it fails with an `AdminApiError`, write exactly one server-side line
 * before rethrowing it unchanged.
 *
 * FEATURE: BFF error traceability (OME-943). Before this, a failed call became an error object
 * handed to a page or server action, and the failure reached the browser and left nothing behind.
 *
 * INVARIANT: the line carries method, path, kind, status and request id — and NOTHING derived from
 * the upstream body (`detail`, `message`). Those can carry provider text, and a key write's refusal
 * can echo the key. The path is logged without its query string: `?q=` is operator-typed search.
 *
 * WHY only `AdminApiError`: anything else is a bug that propagates to Next's error boundary, which
 * already logs it server-side; logging it here too would make one failure two lines.
 */
async function reportingFailure<T>(method: string, path: string, call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (error) {
    if (error instanceof AdminApiError) {
      const incoming = await headers();
      log(REFUSALS.has(error.kind) ? "warn" : "error", "bff_admin_error", {
        method,
        path: path.split("?")[0],
        kind: error.kind,
        status: error.status,
        requestId: incoming.get(REQUEST_ID_HEADER) ?? null,
      });
    }
    throw error;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  return reportingFailure((init?.method ?? "GET").toUpperCase(), path, () => send<T>(path, init));
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  const email = await callerEmail();
  let response: Response;
  try {
    response = await fetch(`${baseUrl()}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "content-type": "application/json" } : {}),
        // Absent rather than empty when there is no caller: aigateway treats a blank header as no
        // identity, but sending the key at all invites a future reader to think one was supplied.
        ...(email ? { "x-user-email": email } : {}),
        ...(init?.headers as Record<string, string> | undefined),
      },
      // Admin data is mutable state an operator is actively editing. A cached list that shows a
      // tenant they just deleted is worse than a slower page.
      cache: "no-store",
    });
  } catch (cause) {
    throw new AdminApiError(
      "unreachable",
      0,
      "The gateway did not answer. Check AIGATEWAY_ADMIN_BASE_URL and that it is running.",
      cause,
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload: unknown = text ? safeJson(text) : undefined;

  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    const kind = classify(response.status, detail);
    throw new AdminApiError(kind, response.status, messageFor(kind, detail), detail);
  }
  return payload as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/**
 * Percent-encode one path segment.
 *
 * INVARIANT: every interpolated segment goes through this. Not a nicety — a raw `..` in an account
 * id walks the request OUT of `/v1/admin/`: `/v1/admin/accounts/../../v1/models` normalizes to
 * `/v1/v1/models` before it is sent, and a `?` splices on a query string. These values are
 * attacker-reachable — `accountId` is a route param and a hidden form field, `provider` is free
 * text whenever discovery fails and the form falls back to a typed id — and the resulting request
 * carries the admin's forwarded identity.
 *
 * Encoding is not enough for `.` and `..`: `encodeURIComponent` leaves dots alone and the URL
 * parser treats `%2E` as a dot too, so `/connections/..` still collapses into its parent. An empty
 * segment silently addresses the parent collection. All three are refused before any request.
 */
function segment(value: string): string {
  if (value === "" || value === "." || value === "..") {
    throw new AdminApiError("invalid", 0, "That identifier is not a valid path segment.", {
      code: "invalid_path_segment",
    });
  }
  return encodeURIComponent(value);
}

export async function listAccounts(params?: {
  q?: string;
  limit?: number;
  offset?: number;
}): Promise<AdminAccountList> {
  const search = new URLSearchParams();
  if (params?.q) search.set("q", params.q);
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.offset !== undefined) search.set("offset", String(params.offset));
  const suffix = search.size ? `?${search}` : "";
  return request<AdminAccountList>(`/v1/admin/accounts${suffix}`);
}

export async function getAccount(accountId: string): Promise<AdminAccount> {
  return request<AdminAccount>(`/v1/admin/accounts/${segment(accountId)}`);
}

export async function createAccount(input: {
  email: string;
  display_name?: string | null;
}): Promise<AdminAccount> {
  return request<AdminAccount>("/v1/admin/accounts", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function patchAccount(
  accountId: string,
  input: { display_name?: string | null; is_active?: boolean | null },
): Promise<AdminAccount> {
  return request<AdminAccount>(`/v1/admin/accounts/${segment(accountId)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

/**
 * One tenant's credentials, one per provider: a Connection, or a conflict the console cannot act
 * on (D18 §4). The pair `(account, provider)` is the whole address — there is no name.
 */
export async function listConnections(accountId: string): Promise<AdminConnectionList> {
  return request<AdminConnectionList>(`/v1/admin/accounts/${segment(accountId)}/connections`);
}

/**
 * Attach or replace a tenant's provider API key.
 *
 * INVARIANT: the raw key travels one way, and the body is exactly `{ "api_key": … }`. It is built
 * from `api_key` alone rather than by serialising `input`: a stale caller object can still carry
 * `name` or `defaults` at runtime, and the successor PUT refuses any other property with 422.
 */
export async function setConnectionApiKey(
  accountId: string,
  provider: string,
  input: { api_key: string },
): Promise<AdminConnection> {
  return request<AdminConnection>(
    `/v1/admin/accounts/${segment(accountId)}/connections/${segment(provider)}/api-key`,
    { method: "PUT", body: JSON.stringify({ api_key: input.api_key }) },
  );
}

/** Disconnect a tenant's provider. A repeat on a disconnected provider is also a 204. */
export async function deleteConnection(accountId: string, provider: string): Promise<void> {
  await request<void>(
    `/v1/admin/accounts/${segment(accountId)}/connections/${segment(provider)}`,
    { method: "DELETE" },
  );
}

/**
 * Provider ids the gateway can serve.
 *
 * Read from `owned_by`, which the gateway sets explicitly per model — NOT parsed out of the model
 * id. An earlier version split the id on `/` and treated the head as the provider, which silently
 * dropped every provider whose models are advertised bare. In practice that meant `anthropic`, the
 * one this repo defaults to, was missing from the console's provider list while four others showed
 * up: the failure was invisible because the list still looked plausible.
 */
export async function listProviders(): Promise<string[]> {
  const models = await request<{ data: { id: string; owned_by?: string }[] }>("/v1/models");
  const providers = new Set<string>();
  for (const model of models.data ?? []) {
    const owner = model.owned_by?.trim();
    if (owner) providers.add(owner);
  }
  return [...providers].sort();
}

// --- response-cache admin (OME-953) ---------------------------------------------------------------

export type AdminCacheInfo = components["schemas"]["AdminCacheInfoOut"];
export type AdminCacheJob = components["schemas"]["AdminCacheJobOut"];

export async function cacheInfo(): Promise<AdminCacheInfo> {
  return request<AdminCacheInfo>("/v1/admin/cache/info");
}

export async function listCacheJobs(): Promise<AdminCacheJob[]> {
  const page = await request<components["schemas"]["AdminCacheJobList"]>(
    "/v1/admin/cache/snapshots/jobs",
  );
  return page.jobs;
}

export async function getCacheJob(jobId: string): Promise<AdminCacheJob> {
  return request<AdminCacheJob>(`/v1/admin/cache/snapshots/jobs/${segment(jobId)}`);
}

type SnapshotUpload = {
  mode: "merge" | "replace";
  force: boolean;
  acknowledgeLoss: boolean;
  snapshot: File;
  manifest: File | null;
};

/**
 * Upload one snapshot archive (and its optional manifest) for the gateway to load.
 *
 * The console's only multipart call: the archive is tens of megabytes of file, not JSON, and the
 * browser-built `FormData` carries both the file and the scalar fields exactly as the gateway's
 * `POST /v1/admin/cache/snapshots` expects them. The `content-type` header is deliberately NOT
 * set — the boundary belongs to fetch, and a manual header would break the body it frames.
 *
 * `snapshot`/`manifest` are `File`s, which on the server side (this module only ever runs there)
 * are the request's web-standard file objects — never read into memory here; undici streams them.
 */
export async function uploadCacheSnapshot(input: SnapshotUpload): Promise<AdminCacheJob> {
  return reportingFailure("POST", "/v1/admin/cache/snapshots", () => sendSnapshot(input));
}

async function sendSnapshot(input: SnapshotUpload): Promise<AdminCacheJob> {
  const email = await callerEmail();
  const form = new FormData();
  form.set("mode", input.mode);
  form.set("force", String(input.force));
  form.set("acknowledge_loss", String(input.acknowledgeLoss));
  form.set("snapshot", input.snapshot, input.snapshot.name || "snapshot.sql.gz");
  if (input.manifest) form.set("manifest", input.manifest, input.manifest.name);

  let response: Response;
  try {
    response = await fetch(`${baseUrl()}/v1/admin/cache/snapshots`, {
      method: "POST",
      headers: {
        ...(email ? { "x-user-email": email } : {}),
      },
      body: form,
      cache: "no-store",
    });
  } catch (cause) {
    throw new AdminApiError(
      "unreachable",
      0,
      "The gateway did not answer. Check AIGATEWAY_ADMIN_BASE_URL and that it is running.",
      cause,
    );
  }
  if (response.status === 204) return undefined as unknown as AdminCacheJob;

  const text = await response.text();
  const payload: unknown = text ? safeJson(text) : undefined;
  if (!response.ok) {
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : payload;
    const kind = classify(response.status, detail);
    throw new AdminApiError(kind, response.status, messageFor(kind, detail), detail);
  }
  return payload as AdminCacheJob;
}
