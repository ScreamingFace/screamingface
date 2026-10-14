"use client";

/**
 * Activate / deactivate a tenant.
 *
 * INVARIANT: no `@/lib/*` import — the server action arrives as a prop, already bound to this
 * account and to the state it moves to. See `delete-connection-button.tsx` for the same rule.
 *
 * The copy states the actual consequence, verified against the gateway: `account_for_identity`
 * returns None for a deactivated account and `current_account` turns that into
 * `401 Account not found or inactive`, on every request, in both auth modes. The credentials are left
 * alone, so this is a lockout and not a deletion.
 */

import { useActionState, useState } from "react";

import type { ActionState, FormState } from "@/app/actions";
import { Button, Notice } from "@/components/ui";

import styles from "./detail.module.css";

export type AccountStatusControlProps = {
  isActive: boolean;
  /** `setAccountActiveAction` with the account id and the TARGET state already bound. */
  action: () => Promise<ActionState>;
};

const ACTIVE_COPY =
  "Deactivating locks this tenant out of the gateway. Every request it sends is refused with " +
  "401 the moment the gateway resolves the account, whatever credentials are attached. The " +
  "credentials below are left in place, so reactivating restores service without re-entering a key.";

const INACTIVE_COPY =
  "This tenant is locked out. The gateway refuses each of its requests with 401 until it is " +
  "reactivated; the credentials below stay attached and start working again the moment it is.";

export function AccountStatusControl({ isActive, action }: AccountStatusControlProps) {
  const [armed, setArmed] = useState(false);
  const [state, submit, pending] = useActionState<FormState, FormData>(() => action(), null);

  // Reactivating is safe and single-click. Deactivating cuts a live tenant off, so it arms first.
  let control;
  if (!isActive) {
    control = (
      <form action={submit}>
        <Button type="submit" disabled={pending}>
          {pending ? "Reactivating…" : "Reactivate tenant"}
        </Button>
      </form>
    );
  } else if (armed) {
    control = (
      <form action={submit} className={styles.confirm}>
        <Button type="submit" variant="danger" disabled={pending}>
          {pending ? "Deactivating…" : "Confirm deactivation"}
        </Button>
        <Button type="button" variant="ghost" disabled={pending} onClick={() => setArmed(false)}>
          Keep active
        </Button>
      </form>
    );
  } else {
    control = (
      <Button type="button" variant="danger" onClick={() => setArmed(true)}>
        Deactivate tenant
      </Button>
    );
  }

  return (
    <div className={styles.statusPanel}>
      <p className={styles.statusCopy}>{isActive ? ACTIVE_COPY : INACTIVE_COPY}</p>
      <div className={styles.statusActions}>{control}</div>
      {state && !state.ok ? (
        <Notice tone="error" title="The tenant was not changed">
          {state.error}
        </Notice>
      ) : null}
    </div>
  );
}
