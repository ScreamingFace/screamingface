"use client";

/**
 * The per-row control that detaches a credential.
 *
 * INVARIANT: this file never imports `@/lib/*`. It receives the server action ALREADY BOUND to the
 * account and provider it disconnects — a client component holding a closed-over reference the
 * server resolves. Nothing about the gateway (its address, the caller's identity) is in this
 * bundle, which is the BFF rule stated as a file boundary.
 *
 * Detaching is destructive and irreversible from here — the key is gone with the connection and
 * can only be restored by pasting it again — so the button arms before it fires. A two-step control
 * rather than `window.confirm`: the dialog is unstyled, blocks the whole tab, and is suppressible
 * by the browser.
 */

import { useActionState, useState } from "react";

import type { ActionState, FormState } from "@/app/actions";
import { Button } from "@/components/ui";

import styles from "./detail.module.css";

export type DeleteConnectionButtonProps = {
  provider: string;
  /** `deleteConnectionAction` with the account id and provider already bound. */
  action: () => Promise<ActionState>;
};

export function DeleteConnectionButton({ provider, action }: DeleteConnectionButtonProps) {
  const [armed, setArmed] = useState(false);
  // The form gives us `pending` and the sequencing for free; the payload is ignored because every
  // argument the action needs was bound on the server.
  const [state, submit, pending] = useActionState<FormState, FormData>(() => action(), null);

  // Several rows carry an identical-looking button, so each one names its own provider — the pair's
  // whole address on this page. The visible word stays at the front of the accessible name
  // (WCAG 2.5.3, label in name).
  const credential = provider;

  return (
    <div className={styles.rowActions}>
      {armed ? (
        <form action={submit} className={styles.confirm}>
          <Button
            type="submit"
            variant="danger"
            disabled={pending}
            aria-label={`Confirm detaching ${credential}`}
          >
            {pending ? "Detaching…" : "Confirm"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={pending}
            onClick={() => setArmed(false)}
            aria-label={`Cancel detaching ${credential}`}
          >
            Cancel
          </Button>
        </form>
      ) : (
        <Button
          type="button"
          variant="danger"
          onClick={() => setArmed(true)}
          aria-label={`Detach ${credential}`}
        >
          Detach
        </Button>
      )}
      {/* Stays armed on failure: the operator meant to do this, and the message says why it did
          not happen. On success the row itself is gone with the next render. */}
      {state && !state.ok ? (
        <p className={styles.rowError} role="alert">
          {state.error}
        </p>
      ) : null}
    </div>
  );
}
