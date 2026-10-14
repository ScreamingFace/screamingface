/**
 * The attach-key page's own decisions, as distinct from the form's: that a missing tenant becomes
 * a real 404 rather than a message, that a refusal is named instead of generic, and — the one
 * worth the most — that provider discovery failing does NOT block the page. Discovery is a
 * convenience; being unable to attach a key because a list endpoint hiccuped would defeat the
 * purpose of the whole console.
 */
import { render, screen } from "@testing-library/react";

vi.mock("server-only", () => ({}));

const getAccount = vi.fn();
const listProviders = vi.fn();
const notFound = vi.fn(() => {
  // Next's real `notFound()` throws a special error to unwind rendering; a plain throw is enough
  // to assert that this page took that branch.
  throw new Error("NEXT_NOT_FOUND");
});

vi.mock("next/navigation", () => ({ notFound, redirect: vi.fn() }));

vi.mock("@/lib/aigateway/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/aigateway/client")>();
  return {
    ...actual,
    getAccount: (...args: unknown[]) => getAccount(...args),
    listProviders: (...args: unknown[]) => listProviders(...args),
  };
});

vi.mock("@/app/actions", () => ({ setApiKeyAction: vi.fn(async () => ({ ok: true })) }));

const { AdminApiError } = await import("@/lib/aigateway/client");
const { default: Page } = await import("./page");
type AdminAccount = import("@/lib/aigateway/client").AdminAccount;

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

const props = () => ({ params: Promise.resolve({ id: "acc-1" }) });

beforeEach(() => {
  getAccount.mockReset().mockResolvedValue(account());
  listProviders.mockReset().mockResolvedValue(["anthropic", "openrouter"]);
  notFound.mockClear();
});

it("names the tenant the key will belong to", async () => {
  render(await Page(props()));

  expect(screen.getByText(/ops@acme\.org/)).toBeInTheDocument();
});

it("offers the providers the gateway can actually serve", async () => {
  render(await Page(props()));

  expect(screen.getByRole("option", { name: "anthropic" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "openrouter" })).toBeInTheDocument();
});

it("still lets a key be attached when provider discovery fails", async () => {
  // THE decision this test exists for. Discovery is a convenience; blocking the entire page on it
  // would mean a hiccup in an unrelated endpoint stops an operator fixing a tenant's credentials.
  listProviders.mockRejectedValue(new AdminApiError("unreachable", 0, "no"));

  render(await Page(props()));

  expect(screen.getByLabelText(/provider/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/api key/i)).toBeInTheDocument();
});

it("keeps the key input write-only", async () => {
  render(await Page(props()));

  const input = screen.getByLabelText(/api key/i);
  expect(input).toHaveAttribute("type", "password");
  expect(input).toHaveAttribute("autocomplete", "off");
  // No value and no defaultValue: there is no source a key could legitimately come from, and an
  // attribute here would be the seam through which one leaks back into the DOM.
  expect(input).not.toHaveAttribute("value");
});

it("promises no key hint and no profile the pair-addressed API does not have", async () => {
  // D18 §3: the gateway returns no key hint in this landing, and the pair is the address.
  render(await Page(props()));

  expect(screen.queryByText(/last four characters/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/profile/i)).not.toBeInTheDocument();
});

it("turns a missing tenant into a real 404", async () => {
  getAccount.mockRejectedValue(new AdminApiError("not_found", 404, "nope"));

  await expect(Page(props())).rejects.toThrow("NEXT_NOT_FOUND");
  expect(notFound).toHaveBeenCalled();
});

it("names a refusal rather than showing a generic error", async () => {
  getAccount.mockRejectedValue(new AdminApiError("forbidden", 403, "nope"));

  render(await Page(props()));

  expect(screen.getByText(/not an administrator/i)).toBeInTheDocument();
});

it("lets a real bug reach the error boundary", async () => {
  getAccount.mockRejectedValue(new TypeError("boom"));

  await expect(Page(props())).rejects.toThrow(TypeError);
});
