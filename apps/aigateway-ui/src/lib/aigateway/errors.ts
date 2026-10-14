/**
 * The admin client's error taxonomy: what kind of failure a gateway answer is, and therefore what
 * the operator must DO about it. Pure — no I/O, no headers — so it is shared by every call shape in
 * `client.ts` (JSON and multipart) and holds no copy of anything the gateway authorizes.
 */

/**
 * Why the caller could not be served — each maps to a different thing the operator must DO, which
 * is why they are distinct types rather than one message string.
 *
 * - `forbidden` — identified, not an administrator. Nothing to retry.
 * - `unauthenticated` — no identity reached the gateway. The mesh is misconfigured, or this is
 *   local development without the header.
 * - `unavailable` — the gateway cannot serve this API at all: no allowlist configured, or it is
 *   running in `jwt` mode. A DEPLOYMENT problem, not a request problem.
 * - `conflict` — a concurrent write lost a CAS (`profile_index_conflict`,
 *   `credential_write_conflict`). Genuinely retryable: "try again" is the right advice.
 * - `superseded` — the credential changed between read and write. Reload; never resubmit the key.
 * - `ambiguous` / `unresolved` — the pair cannot be addressed, or managed safely, from here.
 * - `temporary` — credential storage or authority is briefly unreadable, or the provider's key
 *   check could not run just now. Retry later.
 * - `invalid` — the gateway rejected the input (422), e.g. a malformed address or a key the
 *   provider refused. Carries the detail so a form can show it.
 */
export type AdminErrorKind =
  | "forbidden"
  | "unauthenticated"
  | "unavailable"
  | "conflict"
  | "superseded"
  | "ambiguous"
  | "unresolved"
  | "temporary"
  | "invalid"
  | "not_found"
  | "unreachable"
  | "unknown";

export class AdminApiError extends Error {
  readonly kind: AdminErrorKind;
  readonly status: number;
  readonly detail: unknown;
  /**
   * The gateway's own error code, when it sent one. The kind says what to DO; the code says what
   * was at fault — `unknown_provider` and a refused key are both answers to one form, but they sit
   * under different controls.
   */
  readonly code: string | undefined;

  constructor(kind: AdminErrorKind, status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "AdminApiError";
    this.kind = kind;
    this.status = status;
    this.detail = detail;
    this.code = codeOf(detail);
  }
}

function codeOf(detail: unknown): string | undefined {
  const code =
    typeof detail === "object" && detail !== null && "code" in detail
      ? (detail as { code?: unknown }).code
      : undefined;
  return typeof code === "string" ? code : undefined;
}

/**
 * Gateway error codes whose advice differs from their status (D18 §7).
 *
 * WHY code first: one status carries opposite advice. A 503 is a retryable lost CAS, a temporary
 * storage outage, or — bare — the admin API switched off at the deployment level, where retrying
 * never helps. A 409 is either "try again" or "reload; the state you saw is gone".
 */
const CODE_KINDS: Readonly<Record<string, AdminErrorKind>> = {
  profile_index_conflict: "conflict",
  credential_write_conflict: "conflict",
  credential_publication_superseded: "superseded",
  credential_pair_ambiguous: "ambiguous",
  credential_pair_unresolved: "unresolved",
  credential_authority_unavailable: "temporary",
  credential_store_read_unavailable: "temporary",
  credential_store_unavailable: "temporary",
  // The provider's key check (`routes/api_key_validation.py`). By status these would read as "not
  // an administrator" (403) or "admin API disabled" (503) — both false, both misdirecting.
  api_key_permission_denied: "invalid",
  api_key_no_quota: "invalid",
  api_key_validation_rate_limited: "temporary",
  api_key_validation_unavailable: "temporary",
  // An operator fixes it on the gateway; the gateway's own message says so, and retrying never helps.
  api_key_validation_misconfigured: "unknown",
};

export function classify(status: number, detail: unknown): AdminErrorKind {
  const code = codeOf(detail);
  // `Object.hasOwn`, not `in`: a code of `constructor` must not resolve through the prototype.
  if (code !== undefined && Object.hasOwn(CODE_KINDS, code)) return CODE_KINDS[code];
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 422) return "invalid";
  if (status === 409) return "conflict";
  if (status === 503) return "unavailable";
  return "unknown";
}

export function messageFor(kind: AdminErrorKind, detail: unknown): string {
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
    case "temporary":
      return "The gateway could not read or write credential state just now. Wait a moment and retry.";
    default:
      return "The gateway rejected this request.";
  }
}

/**
 * Kinds where the gateway answered and refused THIS request — expected in normal operation, so
 * they log at `warn`. Everything else (unavailable, unreachable, unknown) means the console cannot
 * be served and logs at `error`. The split is what gives `LOG_LEVEL=error` a meaning.
 */
export const REFUSALS: ReadonlySet<AdminErrorKind> = new Set<AdminErrorKind>([
  "forbidden",
  "unauthenticated",
  "invalid",
  "not_found",
  "conflict",
  "superseded",
  "ambiguous",
  "unresolved",
]);
