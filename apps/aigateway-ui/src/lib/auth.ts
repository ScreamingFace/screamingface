import "server-only";

import { AdminApiError, callerEmail } from "./aigateway/client";

/**
 * Who the console believes is using it, and what to do when the gateway disagrees.
 *
 * INVARIANT: this module makes NO authorization decision. It does not know the allowlist and must
 * never learn it — `AIGATEWAY_ADMIN_EMAILS` lives in aigateway, which is the sole authority. A
 * local copy would be a second place to update and a way for the console to show an operator a
 * page the API would refuse to serve (or worse, hide one it would).
 *
 * What this DOES own is turning the gateway's answer into something a person can act on. The four
 * outcomes below need four different pages, because they need four different actions: log in as
 * someone else, ask for access, fix the deployment, or retry.
 */

export type AdminGateFailure = {
  title: string;
  message: string;
  /** Whether re-running the same request could plausibly succeed. Drives the retry affordance. */
  retryable: boolean;
};

export async function currentAdminEmail(): Promise<string | null> {
  return callerEmail();
}

/**
 * Turn an `AdminApiError` into the page a human should see.
 *
 * Anything that is not an `AdminApiError` is rethrown: an unexpected exception must reach the
 * error boundary and be visible, not be flattened into a tidy message that hides a bug.
 */
export function describeFailure(error: unknown): AdminGateFailure {
  if (!(error instanceof AdminApiError)) throw error;

  switch (error.kind) {
    case "forbidden":
      return {
        title: "Not an administrator",
        message:
          "Your address is not on this gateway's administrator list. Ask an existing administrator to add it to AIGATEWAY_ADMIN_EMAILS.",
        retryable: false,
      };
    case "unauthenticated":
      return {
        title: "No verified identity",
        message:
          "The gateway received no verified address. In a deployed cluster this means the request did not pass through the mesh gateway; locally it means X-User-Email was not set.",
        retryable: false,
      };
    case "unavailable":
      return {
        title: "Admin API is not enabled",
        message:
          "The gateway has no administrator addresses configured, or is not running in cloudflare_headers mode. This is a deployment setting, not something retrying will fix.",
        retryable: false,
      };
    case "unreachable":
      return {
        title: "Gateway unreachable",
        message: error.message,
        retryable: true,
      };
    case "conflict":
      return {
        title: "Another change landed first",
        message: "A concurrent write won. Nothing was lost — try again.",
        retryable: true,
      };
    // D18 §7: the three pair refusals below are never "try again". Repeating the write would
    // either overwrite a change the operator has not seen or meet the same refusal.
    case "superseded":
      return {
        title: "The credential changed",
        message:
          "This credential changed while the request was in flight. Reload the page and review it before submitting another change.",
        retryable: false,
      };
    case "ambiguous":
      return {
        title: "Credential cannot be addressed",
        message:
          "This tenant has more than one credential for this provider, so the console cannot tell which one to change. Resolve the duplicate before managing it here.",
        retryable: false,
      };
    case "unresolved":
      return {
        title: "Credential needs an operator",
        message:
          "This provider's credential is in a state the console cannot manage safely. An operator must resolve it before it can be changed here.",
        retryable: false,
      };
    case "temporary":
      return {
        title: "Credential service temporarily unavailable",
        // WHY the gateway's words: a storage outage and a provider key check that could not run
        // share this kind, and only the message says which one the operator is waiting on.
        message: error.message,
        retryable: true,
      };
    default:
      return { title: "Request refused", message: error.message, retryable: false };
  }
}
