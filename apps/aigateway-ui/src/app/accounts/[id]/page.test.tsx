/**
 * The detail page owns three decisions worth holding: that both reads go out together, that a
 * missing tenant reads as "no such tenant" rather than a generic refusal, and that any other
 * refusal replaces the working surface instead of sitting above controls that would also be
 * refused.
 *
 * Invoked as `await Page(props)` — an async Server Component is just an async function returning a
 * tree, and that tree is ordinary sync React. `server-only` is stubbed because vitest runs outside
 * the react-server condition where it throws by design; `next build` still sees the real module,
 * so the client/server split is enforced where it actually matters.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("server-only", () => ({}));

const getAccount = vi.fn();
const listConnections = vi.fn();

// Spread the real module so `AdminApiError` keeps ONE identity — `describeFailure` narrows with
// `instanceof`, and a second copy of the class would make every refusal look like a bug.
vi.mock("@/lib/aigateway/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/aigateway/client")>();
  return {
    ...actual,
    getAccount: (...args: unknown[]) => getAccount(...args),
    listConnections: (...args: unknown[]) => listConnections(...args),
  };
});

const deleteConnectionAction = vi.fn(async (..._args: unknown[]) => ({ ok: true }));
vi.mock("@/app/actions", () => ({
  setAccountActiveAction: vi.fn(async () => ({ ok: true })),
  deleteConnectionAction: (...args: unknown[]) => deleteConnectionAction(...args),
}));

const { AdminApiError } = await import("@/lib/aigateway/client");
const { default: Page } = await import("./page");
type AdminAccount = import("@/lib/aigateway/client").AdminAccount;
type AdminConnection = import("@/lib/aigateway/client").AdminConnection;

function account(overrides: Partial<AdminAccount> = {}): AdminAccount {
  return {
    id: "acc-1",
    username: "ops@acme.org",
    display_name: "Acme Ops",
    created_at: "2026-07-30T14:22:09Z",
    last_login_at: null,
    is_active: true,
    ...overrides,
  };
}

function connection(overrides: Partial<AdminConnection> = {}): AdminConnection {
  return {
    provider: "anthropic",
    auth_type: "api_key",
    credential_state: "active",
    masked_key_hint: null,
    last_refreshed_at: null,
    ...overrides,
  };
}

const props = { params: Promise.resolve({ id: "acc-1" }) };

beforeEach(() => {
  getAccount.mockReset().mockResolvedValue(account());
  listConnections.mockReset().mockResolvedValue({ connections: [], conflicts: [] });
});

it("names the tenant it is showing", async () => {
  render(await Page({ params: Promise.resolve({ id: "acc-1" }) }));

  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("ops@acme.org");
});

it("reads the account and its credentials in one round trip, not two", async () => {
  // Sequential awaits would put a second round trip on the critical path of a page that cannot
  // render without either result.
  await Page({ params: Promise.resolve({ id: "acc-1" }) });

  expect(getAccount).toHaveBeenCalledWith("acc-1");
  expect(listConnections).toHaveBeenCalledWith("acc-1");
});

it("shows an attached credential by its provider, with a detach control for that provider", async () => {
  listConnections.mockResolvedValue({ connections: [connection()], conflicts: [] });

  render(await Page(props));

  expect(screen.getByRole("cell", { name: "anthropic" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Detach anthropic" })).toBeInTheDocument();
  expect(screen.queryByText(/profile name/i)).not.toBeInTheDocument();
});

it("binds Detach to this account and that provider, in that order", async () => {
  // Both are strings, so a swapped bind type-checks — and would send
  // DELETE /v1/admin/accounts/<provider>/connections/<account>.
  listConnections.mockResolvedValue({ connections: [connection()], conflicts: [] });
  deleteConnectionAction.mockClear();

  render(await Page(props));
  fireEvent.click(screen.getByRole("button", { name: "Detach anthropic" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm detaching anthropic" }));

  await waitFor(() => expect(deleteConnectionAction).toHaveBeenCalledTimes(1));
  expect(deleteConnectionAction.mock.calls[0].slice(0, 2)).toEqual(["acc-1", "anthropic"]);
});

it("lists a pair the gateway cannot address, without a control and without the empty state", async () => {
  listConnections.mockResolvedValue({
    connections: [],
    conflicts: [{ provider: "openai", code: "credential_pair_ambiguous", message: "m" }],
  });

  render(await Page(props));

  expect(screen.getByRole("listitem")).toHaveTextContent("openai");
  expect(screen.queryByRole("button", { name: /detach openai/i })).not.toBeInTheDocument();
  // The tenant HAS a credential for openai — it just cannot be managed here — so "no credentials
  // attached" would be false.
  expect(screen.queryByText(/no credentials attached/i)).not.toBeInTheDocument();
});

it("reads a credential storage outage as temporary, not as a disabled admin API", async () => {
  listConnections.mockRejectedValue(new AdminApiError("temporary", 503, "m"));

  render(await Page(props));

  expect(screen.queryByText(/not enabled/i)).not.toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent(/reload the page to try again/i);
});

it("explains the consequence when a tenant has no credentials", async () => {
  // This sentence is the entire reason the console exists — a tenant with no key authenticates and
  // then gets 404 profile_not_found.
  render(await Page(props));

  expect(screen.getByText(/profile_not_found/i)).toBeInTheDocument();
});

it("says no such tenant rather than a generic refusal", async () => {
  getAccount.mockRejectedValue(new AdminApiError("not_found", 404, "nope"));
  listConnections.mockRejectedValue(new AdminApiError("not_found", 404, "nope"));

  render(await Page({ params: Promise.resolve({ id: "missing" }) }));

  expect(screen.getByText(/no such tenant/i)).toBeInTheDocument();
});

it("replaces the whole surface when the caller is not an administrator", async () => {
  getAccount.mockRejectedValue(new AdminApiError("forbidden", 403, "nope"));
  listConnections.mockRejectedValue(new AdminApiError("forbidden", 403, "nope"));

  render(await Page(props));

  expect(screen.getByText(/not an administrator/i)).toBeInTheDocument();
  // No controls a refused caller could press.
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("lets a real bug reach the error boundary", async () => {
  // `describeFailure` rethrows anything that is not an AdminApiError. Flattening a TypeError into
  // tidy copy would hide the bug behind a page that looks like a permissions problem.
  getAccount.mockRejectedValue(new TypeError("boom"));
  listConnections.mockRejectedValue(new TypeError("boom"));

  await expect(Page(props)).rejects.toThrow(TypeError);
});
