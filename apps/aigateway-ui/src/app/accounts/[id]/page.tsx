import Link from "next/link";

import { deleteConnectionAction, setAccountActiveAction } from "@/app/actions";
import { Notice } from "@/components/ui";
import type { AdminAccount, AdminConnectionList } from "@/lib/aigateway/client";
import { AdminApiError, getAccount, listConnections } from "@/lib/aigateway/client";
import { describeFailure } from "@/lib/auth";

import { AccountStatusControl } from "./account-status-control";
import { DeleteConnectionButton } from "./delete-connection-button";
import { AccountFacts, CredentialConflicts, CredentialsTable, NoCredentials } from "./detail";
import styles from "./detail.module.css";

/**
 * One tenant: who they are, what credentials they hold, and whether the gateway will serve them.
 *
 * Both reads happen HERE, on the server — the BFF rule. Nothing below the fold fetches; the two
 * client components exist only to hold a bound server action and its pending state.
 *
 * The two requests go out together: they are independent, and awaiting them in sequence would put
 * two round trips on the critical path for a page that cannot render without either.
 */

type PageProps = { params: Promise<{ id: string }> };

function BackLink() {
  return (
    <p className={styles.breadcrumb}>
      <Link href="/" className={styles.backLink}>
        ← All tenants
      </Link>
    </p>
  );
}

export default async function AccountDetailPage({ params }: PageProps) {
  // Next 16 hands route params in as a promise.
  const { id } = await params;

  let account: AdminAccount;
  let credentials: AdminConnectionList;
  try {
    [account, credentials] = await Promise.all([getAccount(id), listConnections(id)]);
  } catch (error) {
    // A 404 is its own page, not a generic refusal: the operator followed a link to something
    // that is not there, and the only useful next move is back to the list.
    if (error instanceof AdminApiError && error.kind === "not_found") {
      return (
        <main className="page">
          <BackLink />
          <h1 className="page-title">No such tenant</h1>
          <Notice tone="error" title="This account does not exist">
            The gateway has no account with id <code>{id}</code>. It may have been removed, or the
            link may be stale.
          </Notice>
        </main>
      );
    }
    // `describeFailure` rethrows anything that is not an AdminApiError, so a real bug reaches the
    // error boundary instead of being flattened into a tidy message.
    const failure = describeFailure(error);
    return (
      <main className="page">
        <BackLink />
        <h1 className="page-title">{failure.title}</h1>
        <Notice tone="error" title="This tenant could not be loaded">
          {failure.message}
          {failure.retryable ? " Reload the page to try again." : ""}
        </Notice>
      </main>
    );
  }

  const attachHref = `/accounts/${account.id}/credentials/new`;
  // A link, not a Button: it navigates. It wears the primary button's classes because it is the
  // page's main action and must look like one — the classes are the shared vocabulary, and an
  // anchor keeps middle-click, copy-link and keyboard behaviour that a <button> would throw away.
  const attachButton = (
    <Link href={attachHref} className="ui-btn ui-btn-primary">
      Attach API key
    </Link>
  );

  return (
    <main className="page">
      <BackLink />
      <p className="eyebrow">Tenant</p>
      <h1 className="page-title">{account.username}</h1>
      <p className={styles.identity}>{account.id}</p>

      <AccountFacts
        displayName={account.display_name}
        createdAt={account.created_at}
        lastLoginAt={account.last_login_at}
        isActive={account.is_active}
      />

      <section className={styles.section} aria-labelledby="credentials-heading">
        <div className={styles.sectionHead}>
          <h2 id="credentials-heading" className={styles.sectionTitle}>
            Credentials
          </h2>
          {attachButton}
        </div>
        <p className={styles.sectionLede}>
          One credential per provider that this tenant sends requests with. A key is write-only:
          once submitted it is never shown again.
        </p>
        <CredentialConflicts conflicts={credentials.conflicts} />
        {/* Empty only when the gateway listed nothing at all: a conflicting pair IS a credential
            the tenant holds, so "no credentials attached" would be false beside it. */}
        {credentials.connections.length === 0 && credentials.conflicts.length === 0 ? (
          <NoCredentials action={attachButton} />
        ) : credentials.connections.length > 0 ? (
          <CredentialsTable
            connections={credentials.connections}
            renderActions={(connection) => (
              <DeleteConnectionButton
                provider={connection.provider}
                // Bound on the server: the client component receives a reference, never the
                // account id as browser-supplied input it could be tricked into changing.
                action={deleteConnectionAction.bind(null, account.id, connection.provider)}
              />
            )}
          />
        ) : null}
      </section>

      <section className={styles.section} aria-labelledby="access-heading">
        <h2 id="access-heading" className={styles.sectionTitle}>
          Access
        </h2>
        {/* Keyed by the current status so the control remounts when the tenant flips — otherwise
            an armed "confirm" from the previous state would survive the revalidation. */}
        <AccountStatusControl
          key={String(account.is_active)}
          isActive={account.is_active}
          action={setAccountActiveAction.bind(null, account.id, !account.is_active)}
        />
      </section>
    </main>
  );
}
