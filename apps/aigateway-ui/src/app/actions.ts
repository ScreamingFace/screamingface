"use server";

/**
 * Every write the console can perform. This module is the ONLY place a mutation crosses into
 * aigateway, and it runs exclusively on the server — `'use server'` on line 1 makes each export a
 * server action, so the browser gets an opaque reference, never the code or the admin base URL.
 *
 * INVARIANT: a raw API key travels one way. It is read out of the FormData, handed to the client,
 * and dropped. It is never logged, never returned, never echoed into the state a form re-renders
 * from — `scrubSecret` exists to hold that line even if the gateway ever echoed the value back in
 * an error body.
 *
 * INVARIANT: the returned state is plain, serialisable data. Anything that is not an
 * `AdminApiError` is rethrown so it reaches the error boundary instead of being flattened into a
 * tidy message that hides a bug.
 */

import { revalidatePath } from "next/cache";

import type { AdminCacheJob, AdminErrorKind, ProfileDefaults } from "@/lib/aigateway/client";
import {
  AdminApiError,
  createAccount,
  deleteProfile,
  listCacheJobs,
  patchAccount,
  setApiKey,
  uploadCacheSnapshot,
} from "@/lib/aigateway/client";
import { describeFailure } from "@/lib/auth";

export type ActionSuccess = { ok: true };
/**
 * `field` names the control to attach the message to, when one control is clearly at fault.
 *
 * `kind` is present only when the GATEWAY refused — it is absent for the checks this module makes
 * before calling out. A form needs it because the same field carries two very different failures:
 * `invalid` on a key means the provider rejected it and the operator must fix it at the provider,
 * while `unreachable` or `conflict` mean the value in the control may be perfectly good. Only the
 * kind separates them; the message alone cannot.
 */
export type ActionFailure = {
  ok: false;
  error: string;
  field?: string;
  kind?: AdminErrorKind;
};
export type ActionState = ActionSuccess | ActionFailure;
/** What `useActionState` starts from: nothing has been submitted yet. */
export type FormState = ActionState | null;

const GENERIC_KEY_ERROR = "The gateway rejected that key. Check the value and try again.";

/**
 * Purge the whole console rather than a computed route.
 *
 * Every page here reads the same small pool of mutable admin state, and a write to one account is
 * visible from the list, the detail page and any future search view. Naming paths would couple
 * these actions to the route tree and go stale the moment it changes; purging the root layout is
 * both correct and route-shape-independent, and the console has a handful of pages to rebuild.
 */
function revalidateConsole(): void {
  revalidatePath("/", "layout");
}

function text(formData: FormData, key: string): string {
  const value = formData.get(key);
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Read an optional number.
 *
 * Three-way result: `null` = the field was left blank (send no default), a number = parsed,
 * `undefined` = the operator typed something that is not a number and must be told.
 */
function optionalNumber(formData: FormData, key: string): number | null | undefined {
  const raw = text(formData, key);
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

/** Never let a value that contains the submitted key reach the browser. */
function scrubSecret(message: string, secret?: string): string {
  if (!secret) return message;
  return message.includes(secret) ? GENERIC_KEY_ERROR : message;
}

function failure(error: unknown, field?: string, secret?: string): ActionFailure {
  // `describeFailure` rethrows anything that is not an AdminApiError — that is the behaviour we
  // want, and reusing it keeps one source of truth for how each error kind reads to a human.
  const described = describeFailure(error);
  return {
    ok: false,
    error: scrubSecret(described.message, secret),
    ...(field ? { field } : {}),
    // `describeFailure` has already rethrown anything else, so this narrowing always succeeds —
    // it is written as a check rather than a cast so the day someone changes that, this reads
    // `undefined` instead of lying about the kind.
    ...(error instanceof AdminApiError ? { kind: error.kind } : {}),
  };
}

/**
 * Provision a tenant.
 *
 * The address check is a courtesy, not authority: aigateway validates the address and owns the
 * verdict (422 → `invalid`). This only spares a round trip on an obvious typo.
 */
export async function createAccountAction(
  _prevState: FormState,
  formData: FormData,
): Promise<ActionState> {
  const email = text(formData, "email");
  const displayName = text(formData, "display_name");

  if (!email) {
    return { ok: false, error: "An email address is required.", field: "email" };
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return { ok: false, error: "That does not look like an email address.", field: "email" };
  }

  try {
    await createAccount({ email, display_name: displayName || null });
  } catch (error) {
    return failure(error, "email");
  }

  revalidateConsole();
  return { ok: true };
}

/** Enable or suspend a tenant. Called with bound arguments, so there is no form to validate. */
export async function setAccountActiveAction(
  accountId: string,
  isActive: boolean,
): Promise<ActionState> {
  if (!accountId) {
    return { ok: false, error: "No account was identified for this change." };
  }

  try {
    await patchAccount(accountId, { is_active: isActive });
  } catch (error) {
    return failure(error);
  }

  revalidateConsole();
  return { ok: true };
}

/**
 * Attach or replace a tenant's static provider API key.
 *
 * `api_key` is read, forwarded and forgotten: it is trimmed (a pasted key routinely carries a
 * trailing newline) into a local that leaves this function only as an argument to the client, and
 * is passed to `failure()` solely so an error message containing it can be replaced.
 */
export async function setApiKeyAction(
  _prevState: FormState,
  formData: FormData,
): Promise<ActionState> {
  const accountId = text(formData, "account_id");
  const provider = text(formData, "provider");
  // Every tenant gets one profile per provider in this console; "default" is that profile's name.
  const name = text(formData, "name") || "default";
  const apiKey = text(formData, "api_key");

  if (!accountId) {
    return { ok: false, error: "No account was identified for this key.", field: "account_id" };
  }
  if (!provider) {
    return { ok: false, error: "Choose a provider.", field: "provider" };
  }
  if (!apiKey) {
    return { ok: false, error: "Paste the provider API key.", field: "api_key" };
  }

  const maxTokens = optionalNumber(formData, "max_tokens");
  if (maxTokens === undefined) {
    return { ok: false, error: "Max tokens must be a number.", field: "max_tokens" };
  }
  const temperature = optionalNumber(formData, "temperature");
  if (temperature === undefined) {
    return { ok: false, error: "Temperature must be a number.", field: "temperature" };
  }
  const timeoutSeconds = optionalNumber(formData, "timeout_seconds");
  if (timeoutSeconds === undefined) {
    return { ok: false, error: "Timeout must be a number of seconds.", field: "timeout_seconds" };
  }

  const defaults: ProfileDefaults = {
    model: text(formData, "model") || null,
    system_prompt: text(formData, "system_prompt") || null,
    max_tokens: maxTokens,
    temperature,
    timeout_seconds: timeoutSeconds,
    reasoning_effort: text(formData, "reasoning_effort") || null,
  };
  // An all-blank defaults block is sent as null, so replacing a key does not quietly wipe the
  // defaults a previous form submission set.
  const anyDefault = Object.values(defaults).some((value) => value !== null);

  try {
    await setApiKey(accountId, provider, name, {
      api_key: apiKey,
      defaults: anyDefault ? defaults : null,
    });
  } catch (error) {
    return failure(error, "api_key", apiKey);
  }

  revalidateConsole();
  return { ok: true };
}

/** Detach a credential profile. The key itself is gone with it — aigateway owns that deletion. */
export async function deleteProfileAction(
  accountId: string,
  provider: string,
  name: string,
): Promise<ActionState> {
  if (!accountId || !provider || !name) {
    return { ok: false, error: "That credential could not be identified." };
  }

  try {
    await deleteProfile(accountId, provider, name);
  } catch (error) {
    return failure(error);
  }

  revalidateConsole();
  return { ok: true };
}

/**
 * Upload one cache snapshot for the gateway to load (OME-953).
 *
 * The archive is read out of the FormData as a `File` and handed to the client whole — never
 * logged, never echoed, and never held in the returned state. There is nothing secret IN a
 * snapshot (cached provider responses), but it is other callers' data, and the one-way rule the
 * key actions follow costs nothing to keep here too.
 */
export async function uploadCacheSnapshotAction(
  _prevState: FormState,
  formData: FormData,
): Promise<ActionState> {
  const mode = text(formData, "mode") || "merge";
  const snapshot = formData.get("snapshot");
  const manifest = formData.get("manifest");

  if (mode !== "merge" && mode !== "replace") {
    return { ok: false, error: "Choose a load mode: merge or replace.", field: "mode" };
  }
  if (!(snapshot instanceof File) || snapshot.size === 0) {
    return { ok: false, error: "Attach the snapshot archive (.sql.gz).", field: "snapshot" };
  }
  if (snapshot.size > 512 * 1024 * 1024) {
    // A courtesy bound so a wrong file (e.g. a database backup) fails before the upload; the
    // gateway's own cap remains the authority and may differ per deployment.
    return { ok: false, error: "That file is too large to be a snapshot archive.", field: "snapshot" };
  }
  if (manifest && !(manifest instanceof File)) {
    return { ok: false, error: "The manifest must be a file.", field: "manifest" };
  }

  try {
    await uploadCacheSnapshot({
      mode,
      force: formData.get("force") === "on" || formData.get("force") === "true",
      acknowledgeLoss:
        formData.get("acknowledge_loss") === "on" || formData.get("acknowledge_loss") === "true",
      snapshot,
      manifest: manifest instanceof File && manifest.size > 0 ? manifest : null,
    });
  } catch (error) {
    return failure(error, "snapshot");
  }

  revalidateConsole();
  return { ok: true };
}

/**
 * Refresh the cache-job list for the poller. A query-shaped action: it mutates nothing, but
 * running it as a server action keeps the gateway's address and the identity header server-side,
 * exactly like every other read the console does.
 */
export async function listCacheJobsAction(): Promise<AdminCacheJob[]> {
  return listCacheJobs();
}
