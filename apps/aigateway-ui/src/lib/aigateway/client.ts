import "server-only";

import { headers } from "next/headers";

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

export type AdminAccount = components["schemas"]["AdminAccountOut"];
export type AdminAccountList = components["schemas"]["AdminAccountList"];
export type AdminProfile = components["schemas"]["AdminProfileOut"];
export type AdminProfileList = components["schemas"]["AdminProfileList"];
export type ProfileDefaults = components["schemas"]["ProfileDefaults"];

/** The identity header Envoy injects. Mirrors `HEADER_USER_EMAIL` in aigateway. */
const IDENTITY_HEADER = "x-user-email";

/**
 * Why the caller could not be served — each maps to a different thing the operator must DO, which
 * is why they are distinct types rather than one message string.
 *
 * - `forbidden` — identified, not an administrator. Nothing to retry.
 * - `unauthenticated` — no identity reached the gateway. The mesh is misconfigured, or this is
 *   local development without the header.
 * - `unavailable` — the gateway cannot serve this API at all: no allowlist configured, or it is
 *   running in `jwt` mode. A DEPLOYMENT problem, not a request problem.
 * - `conflict` — a concurrent write lost the profile-index CAS (`profile_index_conflict`).
 *   Genuinely retryable, and the only one where "try again" is the right advice.
 * - `invalid` — the gateway rejected the input (422), e.g. a malformed address or a key the
 *   provider refused. Carries the detail so a form can show it.
 */
export type AdminErrorKind =
  | "forbidden"
  | "unauthenticated"
  | "unavailable"
  | "conflict"
  | "invalid"
  | "not_found"
  | "unreachable"
  | "unknown";

export class AdminApiError extends Error {
  readonly kind: AdminErrorKind;
  readonly status: number;
  readonly detail: unknown;

  constructor(kind: AdminErrorKind, status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "AdminApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

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

function classify(status: number, detail: unknown): AdminErrorKind {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 422) return "invalid";
  if (status === 409) return "conflict";
  if (status === 503) {
    // The gateway uses 503 for two unrelated things. `profile_index_conflict` is a lost CAS on a
    // concurrent profile write and IS retryable; a bare 503 means the admin API is switched off at
    // the deployment level and retrying will never help. Telling them apart is the difference
    // between "try again" and "go fix your configuration".
    const code =
      typeof detail === "object" && detail !== null && "code" in detail
        ? (detail as { code?: unknown }).code
        : undefined;
    return code === "profile_index_conflict" ? "conflict" : "unavailable";
  }
  return "unknown";
}

function messageFor(kind: AdminErrorKind, detail: unknown): string {
  if (typeof detail === "object" && detail !== null && "message" in detail) {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === "string" && message) return message;
  }
  if (typeof detail === "string" && detail) return detail;
  switch (kind) {
    case "forbidden":
      return "This account is not an administrator of this gateway.";
    case "unauthenticated":
      return "No verified identity reached the gateway.";
    case "unavailable":
      return "The gateway is not configured to serve the admin API.";
    case "conflict":
      return "Another change landed first. Try again.";
    default:
      return "The gateway rejected this request.";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
 * An earlier version encoded `name` and not the others, which is how the gap hid: the inconsistency
 * inside one template literal read as deliberate.
 */
function segment(value: string): string {
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

export async function listProfiles(accountId: string): Promise<AdminProfileList> {
  return request<AdminProfileList>(`/v1/admin/accounts/${segment(accountId)}/profiles`);
}

/**
 * Attach or replace a tenant's provider API key.
 *
 * INVARIANT: the raw key travels one way. aigateway returns only a masked `account_label`, and
 * nothing here retains, logs, or echoes the value it was given.
 */
export async function setApiKey(
  accountId: string,
  provider: string,
  name: string,
  input: { api_key: string; defaults?: ProfileDefaults | null },
): Promise<AdminProfile> {
  return request<AdminProfile>(
    `/v1/admin/accounts/${segment(accountId)}/profiles/${segment(provider)}/${segment(name)}/api-key`,
    { method: "PUT", body: JSON.stringify(input) },
  );
}

export async function deleteProfile(
  accountId: string,
  provider: string,
  name: string,
): Promise<void> {
  await request<void>(
    `/v1/admin/accounts/${segment(accountId)}/profiles/${segment(provider)}/${segment(name)}`,
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
export async function uploadCacheSnapshot(input: {
  mode: "merge" | "replace";
  force: boolean;
  acknowledgeLoss: boolean;
  snapshot: File;
  manifest: File | null;
}): Promise<AdminCacheJob> {
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
