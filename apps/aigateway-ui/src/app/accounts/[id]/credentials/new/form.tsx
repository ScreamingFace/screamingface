"use client";

/**
 * The credential form. Client-side because it needs `useActionState` for the pending flag and for
 * the error that comes back on a named field.
 *
 * INVARIANT: nothing here imports `@/lib/aigateway/client` or `@/lib/auth`. The action arrives as
 * a PROP — the page passes a server action in — so the gateway's address, the caller's identity
 * and the admin API's shape stay on the server. The only imports from `@/app/actions` are types,
 * which are erased at compile time.
 *
 * INVARIANT: the api_key control has no `value` and no `defaultValue`, from any source, ever. It
 * is write-only: the operator types a key, the action forwards it, and the browser never sees it
 * again — not on a re-render, not after a failed submit, not from the gateway (which returns
 * nothing derived from the key). `form.test.tsx` pins this.
 *
 * INVARIANT (OME-1138 Stage C, OME-1322): no saved request defaults. Parameters such as model,
 * temperature or max tokens are the caller's, per request — this form offers no control for them
 * and posts only provider and key.
 *
 * INVARIANT: no account id is posted. The page binds it on the server; a hidden field would be a
 * target the browser could rewrite.
 *
 * INVARIANT (D18 §8): no profile name. The pair `(account, provider)` is the credential's whole
 * address, so there is no name control, no hidden name and no `default` to keep.
 */

import { useActionState, type ReactNode } from "react";

import type { ActionFailure, ActionState, FormState } from "@/app/actions";
import { Button, Field, Input, Notice, Select } from "@/components/ui";

import styles from "./form.module.css";

/**
 * The action the form submits to.
 *
 * The page wraps `setApiKeyAction` in a server action that redirects on success, which is why
 * this component renders no "what now" affordance after a win — the navigation is the answer.
 */
export type CredentialFormAction = (state: FormState, formData: FormData) => Promise<ActionState>;

export type CredentialFormProps = {
  /**
   * Provider ids the gateway advertises. EMPTY IS MEANINGFUL: it means discovery failed, and the
   * form falls back to a typed provider id rather than blocking the operator behind a list it
   * could not fetch.
   */
  providers: string[];
  /** Where "Cancel" goes — the account this credential is being attached to. */
  cancelHref: string;
  action: CredentialFormAction;
};

export type CredentialFieldsProps = Omit<CredentialFormProps, "action"> & {
  state: FormState;
  pending: boolean;
};

export function CredentialForm({ action, ...rest }: CredentialFormProps) {
  const [state, formAction, pending] = useActionState<FormState, FormData>(action, null);

  return (
    <form className={styles.form} action={formAction}>
      <CredentialFields state={state} pending={pending} {...rest} />
    </form>
  );
}

/**
 * The form's contents, split out from the hook so the failure states can be rendered — and tested
 * — directly from a state object instead of by driving a submit.
 */
export function CredentialFields({
  providers,
  cancelHref,
  state,
  pending,
}: CredentialFieldsProps) {
  const failure: ActionFailure | null = state && !state.ok ? state : null;
  const on = (field: string): ActionFailure | null => (failure?.field === field ? failure : null);

  const providerFailure = on("provider");
  const keyFailure = on("api_key");

  // A failure with no field has no control to sit under — it is said at the top of the form or it
  // is not said at all.
  const formFailure = failure && !failure.field ? failure : null;

  return (
    <>
      {formFailure ? (
        <Notice tone="error" title="The key was not attached">
          {formFailure.error}
        </Notice>
      ) : null}
      {state?.ok ? (
        <Notice tone="success" title="Key attached">
          Returning to the account.
        </Notice>
      ) : null}

      {providers.length > 0 ? (
        <Field
          label="Provider"
          hint="The providers this gateway advertises models for."
          error={providerFailure?.error}
        >
          <Select name="provider" required defaultValue={providers[0]}>
            {providers.map((provider) => (
              <option key={provider} value={provider}>
                {provider}
              </option>
            ))}
          </Select>
        </Field>
      ) : (
        <Field
          label="Provider"
          hint="The gateway's model list could not be read, so type the provider id exactly as aigateway names it — for example openai or anthropic."
          error={providerFailure?.error}
        >
          <Input
            name="provider"
            required
            placeholder="openai"
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
      )}

      <Field
        label="API key"
        hint="Sent straight to the gateway and stored encrypted. It is never shown again. Attaching a key for a provider that already has one replaces it."
        error={keyErrorFor(keyFailure)}
      >
        {/* INVARIANT: no value, no defaultValue. Write-only — see the file header. */}
        <Input
          name="api_key"
          type="password"
          required
          autoComplete="off"
          spellCheck={false}
          placeholder="Paste the provider API key"
        />
      </Field>

      <div className={styles.actions}>
        {/* No `type` — see the note in ui.tsx: this button must submit. */}
        <Button disabled={pending}>{pending ? "Attaching…" : "Attach key"}</Button>
        {/*
          A plain anchor, not next/link. Leaving this form should tear the document down rather
          than transition a tree that is holding a half-typed key in component state.
        */}
        <a className={styles.cancel} href={cancelHref}>
          Cancel
        </a>
      </div>
    </>
  );
}

/**
 * What to say about a failure that landed on the key field.
 *
 * `invalid` is the common one and it is NOT a validation error in this form — the gateway got the
 * request, handed the key to the provider, and the provider said no. Saying "invalid input" there
 * sends the operator hunting for a typo in a field that is fine. Every other kind (unreachable,
 * conflict, forbidden) is about the gateway, so the gateway's own message stands alone.
 */
function keyErrorFor(failure: ActionFailure | null): ReactNode {
  if (!failure) return undefined;
  if (failure.kind !== "invalid") return failure.error;
  return (
    <>
      The provider refused this key — it was not rejected by this form. Check that the key is
      active, belongs to the right account at that provider, and was copied whole. Gateway said:{" "}
      {failure.error}
    </>
  );
}
