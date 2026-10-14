/**
 * The tenant detail page, minus the fetch.
 *
 * `page.tsx` is an async Server Component and cannot be rendered here — so it holds nothing but
 * the two gateway calls and the composition, and everything that decides something lives in
 * `detail.tsx` or in the two client components, which is what this file exercises.
 *
 * Three things are pinned deliberately rather than incidentally: a credential is addressed by its
 * provider alone (no profile name, no label — D18 §3), a pair the gateway cannot address is listed
 * as a conflict with no control on it, and the empty state names `404 profile_not_found` — the
 * failure this whole console exists to prevent.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { ActionState } from "@/app/actions";
import type { AdminConnection } from "@/lib/aigateway/client";

import { AccountStatusControl } from "./account-status-control";
import { DeleteConnectionButton } from "./delete-connection-button";
import {
  AccountFacts,
  CredentialConflicts,
  CredentialsTable,
  NO_VALUE,
  NoCredentials,
  authTypeLabel,
  describeCredentialState,
  formatInstant,
} from "./detail";

function connection(overrides: Partial<AdminConnection> = {}): AdminConnection {
  return {
    provider: "anthropic",
    auth_type: "api_key",
    credential_state: "active",
    masked_key_hint: null,
    last_refreshed_at: "2026-07-30T14:03:07.512Z",
    ...overrides,
  };
}

describe("formatInstant", () => {
  it("renders an ISO instant in UTC, to the minute", () => {
    expect(formatInstant("2026-07-30T14:03:07.512Z")).toBe("2026-07-30 14:03 UTC");
  });

  it("normalises an offset to UTC rather than showing it as-written", () => {
    // 09:03-05:00 IS 14:03Z. Formatting in a fixed zone is what keeps the server render and the
    // browser's hydration of it byte-identical.
    expect(formatInstant("2026-07-30T09:03:07-05:00")).toBe("2026-07-30 14:03 UTC");
  });

  it("shows a dash for an absent value", () => {
    expect(formatInstant(null)).toBe(NO_VALUE);
    expect(formatInstant(undefined)).toBe(NO_VALUE);
    expect(formatInstant("")).toBe(NO_VALUE);
  });

  it("passes an unparseable value through instead of hiding it", () => {
    expect(formatInstant("whenever")).toBe("whenever");
  });
});

describe("describeCredentialState", () => {
  it("maps the gateway's credential states to a label and a tone", () => {
    expect(describeCredentialState("active")).toEqual({ label: "Active", tone: "good" });
    expect(describeCredentialState("pending")).toEqual({ label: "Pending", tone: "neutral" });
    expect(describeCredentialState("error")).toEqual({ label: "Error", tone: "bad" });
  });

  it("shows a state it has never heard of verbatim, never as active", () => {
    // The gateway owns that enum and may grow it. Collapsing an unknown value into "unknown" — or
    // worse, into "Active" — would hide the one string the operator needs to go look it up.
    expect(describeCredentialState("revoked")).toEqual({ label: "revoked", tone: "neutral" });
  });
});

describe("authTypeLabel", () => {
  it("spells out the auth types", () => {
    expect(authTypeLabel("api_key")).toBe("API key");
    expect(authTypeLabel("oauth")).toBe("OAuth");
  });

  it("passes anything else through", () => {
    expect(authTypeLabel("mtls")).toBe("mtls");
  });
});

describe("AccountFacts", () => {
  it("pairs every fact with its label", () => {
    render(
      <AccountFacts
        displayName="Platform team"
        createdAt="2026-07-01T08:00:00Z"
        lastLoginAt="2026-07-30T14:03:07Z"
        isActive
      />,
    );

    expect(screen.getByText("Display name").tagName).toBe("DT");
    expect(screen.getByText("Platform team").tagName).toBe("DD");
    expect(screen.getByText("2026-07-01 08:00 UTC")).toBeInTheDocument();
    expect(screen.getByText("2026-07-30 14:03 UTC")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("says a tenant that has not called the gateway has never logged in", () => {
    render(<AccountFacts createdAt="2026-07-01T08:00:00Z" lastLoginAt={null} isActive />);

    expect(screen.getByText("Never")).toBeInTheDocument();
  });

  it("dashes an absent or blank display name", () => {
    render(
      <AccountFacts displayName="   " createdAt="2026-07-01T08:00:00Z" lastLoginAt={null} isActive />,
    );

    expect(screen.getByText(NO_VALUE)).toBeInTheDocument();
  });

  it("states a deactivated tenant as deactivated", () => {
    render(
      <AccountFacts createdAt="2026-07-01T08:00:00Z" lastLoginAt={null} isActive={false} />,
    );

    expect(screen.getByText("Deactivated")).toBeInTheDocument();
    expect(screen.queryByText("Active")).not.toBeInTheDocument();
  });
});

describe("CredentialsTable", () => {
  it("heads the columns of a pair-addressed credential — no name, no label", () => {
    render(<CredentialsTable connections={[connection()]} renderActions={() => null} />);

    const headers = screen.getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headers).toEqual([
      "Provider",
      "Key hint",
      "State",
      "Auth type",
      "Last refreshed",
      "Actions",
    ]);
  });

  it("dashes the key hint the gateway does not provide", () => {
    // D18 §3: `masked_key_hint` is always null in this landing; nothing here derives one.
    render(<CredentialsTable connections={[connection()]} renderActions={() => null} />);

    const cells = within(screen.getAllByRole("row")[1]).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent(NO_VALUE);
  });

  it("renders a key hint exactly as received when the gateway sends one", () => {
    render(
      <CredentialsTable
        connections={[connection({ masked_key_hint: "····WXYZ" })]}
        renderActions={() => null}
      />,
    );

    expect(screen.getByText("····WXYZ")).toBeInTheDocument();
  });

  it("renders a row per provider, with its own actions", () => {
    render(
      <CredentialsTable
        connections={[
          connection(),
          connection({ provider: "openai", credential_state: "pending", auth_type: "oauth" }),
        ]}
        renderActions={(row) => <button type="button">{`Detach ${row.provider}`}</button>}
      />,
    );

    const rows = screen.getAllByRole("row").slice(1); // drop the header row
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByRole("button", { name: "Detach anthropic" })).toBeVisible();
    expect(within(rows[1]).getByRole("button", { name: "Detach openai" })).toBeVisible();
    expect(within(rows[1]).getByText("Pending")).toBeInTheDocument();
    expect(within(rows[1]).getByText("OAuth")).toBeInTheDocument();
  });

  it("never renders anything a stale row happens to carry", () => {
    const stale = { ...connection(), name: "default", account_label: "API key ····LEAK" };
    render(<CredentialsTable connections={[stale]} renderActions={() => null} />);

    expect(screen.queryByText("default")).not.toBeInTheDocument();
    expect(screen.queryByText(/LEAK/)).not.toBeInTheDocument();
  });
});

describe("CredentialConflicts", () => {
  it("renders nothing when every pair is addressable", () => {
    const { container } = render(<CredentialConflicts conflicts={[]} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("lists each conflicting provider with what has to happen next, and no control", () => {
    render(
      <CredentialConflicts
        conflicts={[
          { provider: "anthropic", code: "credential_pair_ambiguous", message: "gateway words" },
          { provider: "openai", code: "credential_pair_unresolved", message: "gateway words" },
        ]}
      />,
    );

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("anthropic");
    expect(items[0]).toHaveTextContent(/more than one credential/i);
    expect(items[1]).toHaveTextContent("openai");
    expect(items[1]).toHaveTextContent(/operator/i);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("falls back to the gateway's own message for a code it does not know", () => {
    const conflict = { provider: "gemini", code: "credential_pair_new", message: "Gateway explains." };
    render(<CredentialConflicts conflicts={[conflict as never]} />);

    expect(screen.getByRole("listitem")).toHaveTextContent("Gateway explains.");
  });
});

describe("NoCredentials", () => {
  it("names the exact failure an unprovisioned tenant hits", () => {
    render(<NoCredentials action={<a href="/x">Attach API key</a>} />);

    expect(screen.getByText(/404 profile_not_found/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Attach API key" })).toBeInTheDocument();
  });
});

describe("DeleteConnectionButton", () => {
  it("names the provider it would detach, so identical buttons stay distinguishable", () => {
    render(<DeleteConnectionButton provider="anthropic" action={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Detach anthropic" })).toBeInTheDocument();
  });

  it("does not fire on the first click — it arms", () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ ok: true }));
    render(<DeleteConnectionButton provider="anthropic" action={action} />);

    fireEvent.click(screen.getByRole("button", { name: "Detach anthropic" }));

    expect(action).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Confirm detaching anthropic" })).toBeInTheDocument();
  });

  it("puts the button back when the operator cancels", () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ ok: true }));
    render(<DeleteConnectionButton provider="anthropic" action={action} />);

    fireEvent.click(screen.getByRole("button", { name: "Detach anthropic" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel detaching anthropic" }));

    expect(action).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Detach anthropic" })).toBeInTheDocument();
  });

  it("calls the bound action once the operator confirms", async () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ ok: true }));
    render(<DeleteConnectionButton provider="anthropic" action={action} />);

    fireEvent.click(screen.getByRole("button", { name: "Detach anthropic" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm detaching anthropic" }));

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
  });

  it("shows the gateway's refusal and stays armed", async () => {
    const action = vi.fn(
      async (): Promise<ActionState> => ({ ok: false, error: "Another change landed first." }),
    );
    render(<DeleteConnectionButton provider="anthropic" action={action} />);

    fireEvent.click(screen.getByRole("button", { name: "Detach anthropic" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm detaching anthropic" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Another change landed first.");
    expect(screen.getByRole("button", { name: "Confirm detaching anthropic" })).toBeInTheDocument();
  });
});

describe("AccountStatusControl", () => {
  it("explains that deactivating locks the tenant out, and arms before it does", () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ ok: true }));
    render(<AccountStatusControl isActive action={action} />);

    expect(screen.getByText(/locks this tenant out of the gateway/i)).toBeInTheDocument();
    expect(screen.getByText(/refused with 401/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Deactivate tenant" }));

    expect(action).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Confirm deactivation" })).toBeInTheDocument();
  });

  it("backs out cleanly", () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ ok: true }));
    render(<AccountStatusControl isActive action={action} />);

    fireEvent.click(screen.getByRole("button", { name: "Deactivate tenant" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep active" }));

    expect(action).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Deactivate tenant" })).toBeInTheDocument();
  });

  it("deactivates on confirmation", async () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ ok: true }));
    render(<AccountStatusControl isActive action={action} />);

    fireEvent.click(screen.getByRole("button", { name: "Deactivate tenant" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm deactivation" }));

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
  });

  it("reactivates in one click — restoring service is not the destructive direction", async () => {
    const action = vi.fn(async (): Promise<ActionState> => ({ ok: true }));
    render(<AccountStatusControl isActive={false} action={action} />);

    expect(screen.getByText(/locked out/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reactivate tenant" }));

    await waitFor(() => expect(action).toHaveBeenCalledTimes(1));
  });

  it("reports a change the gateway refused", async () => {
    const action = vi.fn(
      async (): Promise<ActionState> => ({ ok: false, error: "The gateway is unreachable." }),
    );
    render(<AccountStatusControl isActive={false} action={action} />);

    fireEvent.click(screen.getByRole("button", { name: "Reactivate tenant" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The gateway is unreachable.");
  });
});
