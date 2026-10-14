/**
 * What these tests hold is the contract the forms depend on: a serialisable state, a `field` that
 * names the control at fault, a cache purge on success only — and, above everything, that a raw
 * API key never appears in what comes back.
 *
 * `server-only` is stubbed because vitest runs the module graph outside the react-server
 * condition, where importing it throws by design. The stub does not weaken the guarantee: it is
 * `next build` that enforces the client/server split, and it still sees the real module.
 */
vi.mock("server-only", () => ({}));

const revalidatePath = vi.fn();
vi.mock("next/cache", () => ({ revalidatePath: (...args: unknown[]) => revalidatePath(...args) }));

const createAccount = vi.fn();
const patchAccount = vi.fn();
const setConnectionApiKey = vi.fn();
const deleteConnection = vi.fn();

// Spread the real module so `AdminApiError` keeps ONE identity — `describeFailure` narrows with
// `instanceof`, and a second copy of the class would make every error look like a bug instead.
vi.mock("@/lib/aigateway/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/aigateway/client")>();
  return {
    ...actual,
    createAccount: (...args: unknown[]) => createAccount(...args),
    patchAccount: (...args: unknown[]) => patchAccount(...args),
    setConnectionApiKey: (...args: unknown[]) => setConnectionApiKey(...args),
    deleteConnection: (...args: unknown[]) => deleteConnection(...args),
  };
});

const { AdminApiError } = await import("@/lib/aigateway/client");
const { createAccountAction, deleteConnectionAction, setAccountActiveAction, setApiKeyAction } =
  await import("./actions");

function form(fields: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  return data;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("createAccountAction", () => {
  it("provisions the tenant and purges the console", async () => {
    createAccount.mockResolvedValue({ id: "a1" });

    const state = await createAccountAction(
      null,
      form({ email: " ada@example.org ", display_name: "Ada" }),
    );

    expect(createAccount).toHaveBeenCalledWith({ email: "ada@example.org", display_name: "Ada" });
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
    expect(state).toEqual({ ok: true });
  });

  it("sends a null display name when the field is blank", async () => {
    createAccount.mockResolvedValue({ id: "a1" });

    await createAccountAction(null, form({ email: "ada@example.org", display_name: "  " }));

    expect(createAccount).toHaveBeenCalledWith({ email: "ada@example.org", display_name: null });
  });

  it.each([
    { email: "", message: "An email address is required." },
    { email: "not-an-address", message: "That does not look like an email address." },
  ])("refuses $email without calling the gateway", async ({ email, message }) => {
    const state = await createAccountAction(null, form({ email }));

    expect(state).toEqual({ ok: false, error: message, field: "email" });
    expect(createAccount).not.toHaveBeenCalled();
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("turns a gateway refusal into a field error and leaves the cache alone", async () => {
    createAccount.mockRejectedValue(
      new AdminApiError("invalid", 422, "That address is already provisioned."),
    );

    const state = await createAccountAction(null, form({ email: "ada@example.org" }));

    expect(state).toEqual({
      ok: false,
      error: "That address is already provisioned.",
      field: "email",
      kind: "invalid",
    });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("rethrows anything that is not an AdminApiError", async () => {
    createAccount.mockRejectedValue(new TypeError("boom"));

    await expect(createAccountAction(null, form({ email: "ada@example.org" }))).rejects.toThrow(
      "boom",
    );
  });
});

describe("setAccountActiveAction", () => {
  it("patches the account and purges the console", async () => {
    patchAccount.mockResolvedValue({ id: "a1" });

    const state = await setAccountActiveAction("a1", false);

    expect(patchAccount).toHaveBeenCalledWith("a1", { is_active: false });
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
    expect(state).toEqual({ ok: true });
  });

  it("refuses an empty account id", async () => {
    const state = await setAccountActiveAction("", true);

    expect(state).toEqual({ ok: false, error: "No account was identified for this change." });
    expect(patchAccount).not.toHaveBeenCalled();
  });

  it("reports a conflict in the words the error kind maps to", async () => {
    patchAccount.mockRejectedValue(new AdminApiError("conflict", 409, "lost the CAS"));

    const state = await setAccountActiveAction("a1", true);

    expect(state).toEqual({
      ok: false,
      error: "A concurrent write won. Nothing was lost — try again.",
      kind: "conflict",
    });
  });
});

describe("setApiKeyAction", () => {
  const base = { account_id: "a1", provider: "openai", api_key: "sk-live-secret-value" };

  const badInput: Array<{ patch: Record<string, string>; error: string; field: string }> = [
    {
      patch: { account_id: "" },
      error: "No account was identified for this key.",
      field: "account_id",
    },
    { patch: { provider: "" }, error: "Choose a provider.", field: "provider" },
    { patch: { api_key: "  " }, error: "Paste the provider API key.", field: "api_key" },
  ];

  it.each(badInput)("rejects a bad $field before calling the gateway", async ({ patch, error, field }) => {
    const state = await setApiKeyAction(null, form({ ...base, ...patch }));

    expect(state).toEqual({ ok: false, error, field });
    expect(setConnectionApiKey).not.toHaveBeenCalled();
  });

  it("NEVER returns the raw key, even if the gateway echoes it back", async () => {
    setConnectionApiKey.mockRejectedValue(
      new AdminApiError("invalid", 422, "Input should be valid: sk-live-secret-value"),
    );

    const state = await setApiKeyAction(null, form(base));

    expect(state).toEqual({
      ok: false,
      error: "The gateway rejected that key. Check the value and try again.",
      field: "api_key",
      kind: "invalid",
    });
    expect(JSON.stringify(state)).not.toContain("sk-live-secret-value");
  });

  it("keeps a gateway message that does not contain the key", async () => {
    setConnectionApiKey.mockRejectedValue(new AdminApiError("invalid", 422, "The provider rejected this key."));

    const state = await setApiKeyAction(null, form(base));

    expect(state).toEqual({
      ok: false,
      error: "The provider rejected this key.",
      field: "api_key",
      kind: "invalid",
    });
  });

  // The credential form reads this: an `invalid` key error is the provider refusing the key and
  // needs different words from a gateway that could not be reached, and the two arrive on the
  // same field with messages that cannot be told apart programmatically.
  it("carries the gateway's error kind so a form can tell the causes apart", async () => {
    setConnectionApiKey.mockRejectedValue(new AdminApiError("unreachable", 0, "The gateway did not answer."));

    const state = await setApiKeyAction(null, form(base));

    expect(state).toEqual({
      ok: false,
      error: "The gateway did not answer.",
      field: "api_key",
      kind: "unreachable",
    });
  });

  it("leaves the kind off a refusal this module made without asking the gateway", async () => {
    const state = await setApiKeyAction(null, form({ ...base, api_key: "" }));

    expect(state).not.toHaveProperty("kind");
  });

  it("tells the operator to reload, not resubmit, when the credential changed meanwhile", async () => {
    setConnectionApiKey.mockRejectedValue(
      new AdminApiError("superseded", 409, "Credential state changed. Reload before submitting another change."),
    );

    const state = await setApiKeyAction(null, form(base));

    expect(state).toMatchObject({ ok: false, field: "api_key", kind: "superseded" });
    expect((state as { error: string }).error).toMatch(/reload/i);
    expect(JSON.stringify(state)).not.toContain("sk-live-secret-value");
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

describe("deleteConnectionAction", () => {
  it("disconnects the provider by pair and purges the console", async () => {
    deleteConnection.mockResolvedValue(undefined);

    const state = await deleteConnectionAction("a1", "openai");

    expect(deleteConnection).toHaveBeenCalledWith("a1", "openai");
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
    expect(state).toEqual({ ok: true });
  });

  it.each([
    { accountId: "", provider: "openai", missing: "account" },
    { accountId: "a1", provider: "", missing: "provider" },
  ])("refuses a credential with no $missing", async ({ accountId, provider }) => {
    const state = await deleteConnectionAction(accountId, provider);

    expect(state).toEqual({ ok: false, error: "That credential could not be identified." });
    expect(deleteConnection).not.toHaveBeenCalled();
  });

  it("carries a pair refusal's kind and leaves the cache alone", async () => {
    deleteConnection.mockRejectedValue(new AdminApiError("ambiguous", 409, "ambiguous"));

    const state = await deleteConnectionAction("a1", "openai");

    expect(state).toMatchObject({ ok: false, kind: "ambiguous" });
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("surfaces a gateway message for a refusal without its own advice", async () => {
    deleteConnection.mockRejectedValue(new AdminApiError("not_found", 404, "No such account."));

    const state = await deleteConnectionAction("a1", "openai");

    expect(state).toEqual({ ok: false, error: "No such account.", kind: "not_found" });
    expect(revalidatePath).not.toHaveBeenCalled();
  });
});

// This file uses vitest globals, so the top-level `await import` needs an explicit module marker.
export {};

describe("setApiKeyAction without saved defaults (OME-1322)", () => {
  const base = { account_id: "a1", provider: "openai", api_key: "sk-live-secret-value" };
  // Every field the retired "Defaults (optional)" fieldset once posted — the numeric ones
  // malformed, because a stale form must neither be forwarded nor be refused over them.
  const staleDefaults = {
    model: "gpt-4o",
    system_prompt: "Be brief.",
    max_tokens: "lots",
    temperature: "warm",
    timeout_seconds: "soon",
    reasoning_effort: "high",
  };

  it("forwards only the key, ignoring stale default fields in the submission", async () => {
    setConnectionApiKey.mockResolvedValue({ id: "p1" });

    const state = await setApiKeyAction(null, form({ ...base, name: "primary", ...staleDefaults }));

    expect(state).toEqual({ ok: true });
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
    expect(setConnectionApiKey).toHaveBeenCalledTimes(1);
    expect(setConnectionApiKey).toHaveBeenCalledWith("a1", "openai", {
      api_key: "sk-live-secret-value",
    });
    // INVARIANT: no `defaults` property at all — `null` would still be a defaults write.
    expect(Object.keys(setConnectionApiKey.mock.calls[0][2] as object)).toEqual(["api_key"]);
  });

  // INVARIANT (D18 §8): the pair is the address. A stale form that still posts `name` neither
  // selects a credential nor gets a `default` substituted for it.
  it("never forwards a profile name, posted or defaulted", async () => {
    setConnectionApiKey.mockResolvedValue({ provider: "openai" });

    await setApiKeyAction(null, form(base));
    await setApiKeyAction(null, form({ ...base, name: "batch" }));

    for (const call of setConnectionApiKey.mock.calls) {
      expect(call).toEqual(["a1", "openai", { api_key: "sk-live-secret-value" }]);
    }
    expect(JSON.stringify(setConnectionApiKey.mock.calls)).not.toMatch(/default|batch/);
  });
});
