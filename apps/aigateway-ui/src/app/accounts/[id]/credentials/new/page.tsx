/**
 * Attach a static provider API key to one tenant.
 *
 * Server Component: `getAccount` and `listProviders` run here, on the server, and the browser
 * receives rendered markup plus one opaque server-action reference — never the gateway's address
 * and never the caller's identity header. The form itself is a Client Component (it needs
 * `useActionState`); the action crosses to it as a prop.
 */

import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import type { ActionState, FormState } from "@/app/actions";
import { setApiKeyAction } from "@/app/actions";
import { Notice } from "@/components/ui";
import type { AdminAccount } from "@/lib/aigateway/client";
import { AdminApiError, getAccount, listProviders } from "@/lib/aigateway/client";
import { describeFailure } from "@/lib/auth";

import { CredentialForm } from "./form";
import styles from "./form.module.css";

export const metadata: Metadata = {
  title: "Attach a provider API key",
};

type PageProps = { params: Promise<{ id: string }> };

export default async function AttachCredentialPage({ params }: PageProps) {
  const { id } = await params;
  const accountHref = `/accounts/${encodeURIComponent(id)}`;

  let account: AdminAccount;
  try {
    account = await getAccount(id);
  } catch (error) {
    // A tenant that does not exist is a 404, not an error page with a message about it.
    if (error instanceof AdminApiError && error.kind === "not_found") notFound();
    // Everything else gets named: forbidden, unauthenticated and unavailable each need a
    // different thing done about them. `describeFailure` rethrows anything that is not an
    // AdminApiError, so a real bug still reaches the error boundary instead of this page.
    const failure = describeFailure(error);
    return (
      <main className="page">
        <p className="eyebrow">OpenMined · ScreamingFace</p>
        <h1 className="page-title">{failure.title}</h1>
        <p className="lede">{failure.message}</p>
        <p className={styles.pageNotice}>
          <Link href={accountHref}>Back to the account</Link>
        </p>
      </main>
    );
  }

  /*
   * Provider discovery is a convenience, not a dependency. `/v1/models` can be empty, slow or
   * refused for reasons that have nothing to do with attaching a key, and blocking the whole page
   * on it would mean an operator cannot fix a credential exactly when the gateway is unhappy.
   * An empty list makes the form take a typed provider id instead.
   */
  let providers: string[];
  try {
    providers = await listProviders();
  } catch {
    providers = [];
  }

  /*
   * Wraps the shared action to own what IS route-specific: which tenant the key is for, and where
   * to go on success.
   *
   * INVARIANT: the account id is CLOSED OVER, not posted and not `.bind`-ed. Next encrypts and
   * authenticates closed-over values per build, so the browser cannot rewrite them; `.bind`
   * arguments, by contrast, travel back from the browser as plain data.
   */
  const accountId = account.id;
  async function attachKey(prevState: FormState, formData: FormData): Promise<ActionState> {
    "use server";
    const state = await setApiKeyAction(accountId, prevState, formData);
    // `setApiKeyAction` has already purged the cache, so the account page renders the new
    // credential rather than the list it was showing a moment ago.
    if (state.ok) redirect(accountHref);
    return state;
  }

  return (
    <main className="page">
      <p className="eyebrow">Account · {account.username}</p>
      <h1 className="page-title">Attach a provider API key</h1>
      <p className="lede">
        The gateway will use this key for every request{" "}
        {account.display_name ?? account.username} makes to this provider, replacing any key it
        already holds there. It is stored encrypted and never shown again.
      </p>

      {account.is_active ? null : (
        <div className={styles.pageNotice}>
          <Notice tone="info" title="This tenant is suspended">
            Attaching a key does not re-enable the account.
          </Notice>
        </div>
      )}

      <CredentialForm
        providers={providers}
        cancelHref={accountHref}
        action={attachKey}
      />
    </main>
  );
}
