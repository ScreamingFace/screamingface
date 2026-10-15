/**
 * The pure half of the tenant detail page: formatting decisions and presentational components
 * that take plain props.
 *
 * WHY this is a separate module. `page.tsx` is an async Server Component that awaits the gateway,
 * and Testing Library cannot render one — so everything here that makes a DECISION (how an
 * instant reads, what an unknown credential state looks like, what the empty credentials table says)
 * lives where a test can hold it, and `page.tsx` is left as fetching plus composition.
 *
 * INVARIANT: no `'use client'` and no runtime import from `src/lib/*`. The only reference to the
 * server-only client is `import type`, which the compiler erases — that is what lets this module
 * render inside the Server Component page AND inside a jsdom test.
 */
import type { ReactNode } from "react";

import type { BadgeTone } from "@/components/ui";
import { Badge, EmptyState, Notice, TBody, TD, TH, THead, TR, Table } from "@/components/ui";
import type { AdminConnection, AdminConnectionConflict } from "@/lib/aigateway/client";

import styles from "./detail.module.css";

/** What an absent optional value looks like. An em dash, not an empty cell that reads as a bug. */
export const NO_VALUE = "—";

/**
 * Render an ISO-8601 instant as `YYYY-MM-DD HH:MM UTC`.
 *
 * UTC, not the viewer's locale, for two reasons. It is deterministic — a locale- or
 * timezone-formatted string differs between the server render and the browser's hydration of it,
 * which React reports as a hydration mismatch. And it matches what an operator reads everywhere
 * else in this stack: aigateway's logs and the gateway's own timestamps are UTC.
 *
 * An unparseable value is returned VERBATIM rather than replaced: showing what the gateway
 * actually sent is more useful than hiding it behind a dash.
 */
export function formatInstant(value: string | null | undefined): string {
  if (!value) return NO_VALUE;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return `${parsed.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

const CREDENTIAL_STATES: Record<string, { label: string; tone: BadgeTone }> = {
  active: { label: "Active", tone: "good" },
  pending: { label: "Pending", tone: "neutral" },
  error: { label: "Error", tone: "bad" },
};

/**
 * How a credential's lifecycle state reads, and which badge tone carries it.
 *
 * A state this console has not heard of is shown verbatim as a neutral badge. The gateway owns
 * that enum and may grow it; swallowing an unknown value into "unknown" — or into "Active" (D18 §3)
 * — would hide the one piece of information the operator needs to go look it up.
 */
export function describeCredentialState(state: string): { label: string; tone: BadgeTone } {
  return Object.hasOwn(CREDENTIAL_STATES, state)
    ? CREDENTIAL_STATES[state]
    : { label: state, tone: "neutral" };
}

/** `api_key` / `oauth` as an operator reads them; anything else passes through untouched. */
export function authTypeLabel(authType: string): string {
  if (authType === "api_key") return "API key";
  if (authType === "oauth") return "OAuth";
  return authType;
}

export type AccountFactsProps = {
  displayName?: string | null;
  createdAt: string;
  lastLoginAt?: string | null;
  isActive: boolean;
};

/** The tenant's own facts, as a definition list — labelled data, not a table of one row. */
export function AccountFacts({ displayName, createdAt, lastLoginAt, isActive }: AccountFactsProps) {
  return (
    <dl className={styles.facts}>
      <div className={styles.fact}>
        <dt className={styles.factLabel}>Display name</dt>
        <dd className={styles.factValue}>{displayName?.trim() || NO_VALUE}</dd>
      </div>
      <div className={styles.fact}>
        <dt className={styles.factLabel}>Created</dt>
        <dd className={styles.factValue}>{formatInstant(createdAt)}</dd>
      </div>
      <div className={styles.fact}>
        <dt className={styles.factLabel}>Last login</dt>
        {/* "Never" rather than a dash: a tenant that has not yet called the gateway is a fact
            about the tenant, not a value the gateway failed to give us. */}
        <dd className={styles.factValue}>{lastLoginAt ? formatInstant(lastLoginAt) : "Never"}</dd>
      </div>
      <div className={styles.fact}>
        <dt className={styles.factLabel}>Status</dt>
        <dd className={styles.factValue}>
          <Badge tone={isActive ? "good" : "bad"}>{isActive ? "Active" : "Deactivated"}</Badge>
        </dd>
      </div>
    </dl>
  );
}

export type CredentialsTableProps = {
  connections: AdminConnection[];
  /**
   * The per-row controls. A render prop rather than a baked-in button because the control is a
   * Client Component holding a server action bound to THIS row — knowledge that belongs to the
   * page, not to a presentational table.
   */
  renderActions: (connection: AdminConnection) => ReactNode;
};

/**
 * One row per provider: the pair `(account, provider)` is a credential's whole address (D18 §3).
 *
 * INVARIANT: no name, label or key-hint column. Cells are read field by field from the DTO, so
 * anything a stale row still carries is never rendered. `masked_key_hint` is always null in this
 * landing and D18 leaves a hint column out of scope: a column of dashes would suggest one is coming.
 */
export function CredentialsTable({ connections, renderActions }: CredentialsTableProps) {
  return (
    <Table>
      <THead>
        <TR>
          <TH>Provider</TH>
          <TH>State</TH>
          <TH>Auth type</TH>
          <TH>Last refreshed</TH>
          <TH>Actions</TH>
        </TR>
      </THead>
      <TBody>
        {connections.map((connection) => {
          const state = describeCredentialState(connection.credential_state);
          return (
            <TR key={connection.provider}>
              <TD>{connection.provider}</TD>
              <TD>
                <Badge tone={state.tone}>{state.label}</Badge>
              </TD>
              <TD>{authTypeLabel(connection.auth_type)}</TD>
              <TD>{formatInstant(connection.last_refreshed_at)}</TD>
              <TD>{renderActions(connection)}</TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}

const CONFLICT_GUIDANCE: Record<string, string> = {
  credential_pair_ambiguous:
    "more than one credential is attached for this provider, so the console cannot tell which one to change. Resolve the duplicate first.",
  credential_pair_unresolved:
    "the credential is in a state the console cannot manage safely. An operator must resolve it before it can be changed here.",
};

/**
 * Providers whose credential the gateway listed but cannot address as one pair (D18 §4).
 *
 * WHY no control on them: a PUT or DELETE on such a pair answers 409, so offering one would only
 * turn a known state into an error message. A code this console does not know shows the gateway's
 * own message rather than a guess.
 */
export function CredentialConflicts({ conflicts }: { conflicts: AdminConnectionConflict[] }) {
  if (conflicts.length === 0) return null;
  return (
    <Notice tone="error" title="Some credentials cannot be managed here">
      <ul className={styles.conflicts}>
        {conflicts.map((conflict) => (
          <li key={conflict.provider}>
            <span className={styles.conflictProvider}>{conflict.provider}</span>:{" "}
            {Object.hasOwn(CONFLICT_GUIDANCE, conflict.code)
              ? CONFLICT_GUIDANCE[conflict.code]
              : conflict.message}
          </li>
        ))}
      </ul>
    </Notice>
  );
}

/**
 * The empty credentials table.
 *
 * This copy is the reason the console exists, so it states the failure literally rather than
 * politely: a tenant with no credential clears Cloudflare Access, becomes a real account, and then
 * every chat request it sends comes back `404 profile_not_found`. Attaching a key is what closes
 * that gap.
 */
export function NoCredentials({ action }: { action?: ReactNode }) {
  return (
    <EmptyState
      title="No credentials attached"
      message="This tenant can authenticate but cannot be served. With no credential, every chat request it sends comes back 404 profile_not_found — attaching a provider API key here is what closes that gap."
      action={action}
    />
  );
}
