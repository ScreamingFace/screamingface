/**
 * What this file exists for, above everything else: the API key control is WRITE-ONLY. No `value`,
 * no `defaultValue`, no re-render that puts a submitted key back on screen. The first two tests
 * hold that line from both directions — a fresh form, and a form that has just come back from a
 * failure carrying an error message about the key.
 *
 * The rest covers the failure routing: a message from the action has to land under the control it
 * is about, and an `invalid` key error has to be described as the provider's refusal rather than
 * as a validation problem in this form.
 */

import { render, screen } from "@testing-library/react";

import type { ActionState, FormState } from "@/app/actions";

import { CredentialFields, CredentialForm } from "./form";

const stubAction = async (): Promise<ActionState> => ({ ok: true });

function renderFields(overrides: Partial<Parameters<typeof CredentialFields>[0]> = {}) {
  return render(
    <CredentialFields
      accountId="acct-1"
      providers={["anthropic", "openai"]}
      cancelHref="/accounts/acct-1"
      state={null}
      pending={false}
      {...overrides}
    />,
  );
}

function keyInput(): HTMLInputElement {
  return screen.getByLabelText(/api key/i) as HTMLInputElement;
}

describe("the API key control", () => {
  it("is a write-only password field with no value of any kind", () => {
    render(
      <CredentialForm
        accountId="acct-1"
        providers={["openai"]}
        cancelHref="/accounts/acct-1"
        action={stubAction}
      />,
    );

    const key = keyInput();
    expect(key).toHaveAttribute("type", "password");
    expect(key).toHaveAttribute("autocomplete", "off");
    expect(key).toBeRequired();
    // `defaultValue` would surface as a `value` attribute; a controlled `value` as both. Neither
    // may exist — the key must never be renderable back out of the form.
    expect(key).not.toHaveAttribute("value");
    expect(key.getAttribute("value")).toBeNull();
    expect(key.value).toBe("");
  });

  it("still holds nothing after a failure that came back about the key", () => {
    const state: FormState = {
      ok: false,
      error: "Input should be a valid key.",
      field: "api_key",
      kind: "invalid",
    };
    renderFields({ state });

    const key = keyInput();
    expect(key).not.toHaveAttribute("value");
    expect(key.value).toBe("");
    expect(key).toHaveAttribute("aria-invalid", "true");
  });

  it("says who refused the key when the gateway kind is invalid", () => {
    renderFields({
      state: {
        ok: false,
        error: "The gateway rejected that key. Check the value and try again.",
        field: "api_key",
        kind: "invalid",
      },
    });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/the provider refused this key/i);
    expect(alert).toHaveTextContent(/gateway said/i);
    expect(alert).toHaveTextContent(/check the value and try again/i);
  });

  it("does not blame the provider when the gateway itself was the problem", () => {
    renderFields({
      state: {
        ok: false,
        error: "The gateway did not answer.",
        field: "api_key",
        kind: "unreachable",
      },
    });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The gateway did not answer.");
    expect(alert).not.toHaveTextContent(/the provider refused/i);
  });

  it("shows a pre-flight refusal as it was written", () => {
    renderFields({ state: { ok: false, error: "Paste the provider API key.", field: "api_key" } });

    expect(screen.getByRole("alert")).toHaveTextContent("Paste the provider API key.");
  });
});

describe("the provider control", () => {
  it("offers the providers the gateway advertises", () => {
    renderFields();

    const select = screen.getByLabelText(/provider/i) as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect([...select.options].map((option) => option.value)).toEqual(["anthropic", "openai"]);
    expect(select.value).toBe("anthropic");
  });

  it("falls back to a typed id when discovery came back empty", () => {
    renderFields({ providers: [] });

    const input = screen.getByLabelText(/provider/i) as HTMLInputElement;
    expect(input.tagName).toBe("INPUT");
    expect(input).toBeRequired();
    expect(screen.getByText(/model list could not be read/i)).toBeInTheDocument();
  });

  it("carries a provider failure on the provider control", () => {
    renderFields({ state: { ok: false, error: "Choose a provider.", field: "provider" } });

    expect(screen.getByLabelText(/provider/i)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a provider.");
  });
});

describe("the rest of the form", () => {
  it("submits the account from the URL as a hidden field", () => {
    const { container } = renderFields();

    const hidden = container.querySelector<HTMLInputElement>('input[name="account_id"]');
    expect(hidden).not.toBeNull();
    expect(hidden).toHaveValue("acct-1");
  });

  it("names the default profile and explains what the name is for", () => {
    renderFields();

    expect(screen.getByLabelText(/profile name/i)).toHaveValue("default");
    expect(screen.getByText(/X-Profile/)).toBeInTheDocument();
  });

  it("speaks a failure with no control of its own at the top of the form", () => {
    renderFields({
      state: { ok: false, error: "No account was identified for this key.", field: "account_id" },
    });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("The key was not attached");
    expect(alert).toHaveTextContent("No account was identified for this key.");
    // No control is at fault, so nothing is marked invalid.
    expect(screen.getByLabelText(/api key/i)).not.toHaveAttribute("aria-invalid", "true");
  });

  it("announces the success the redirect normally beats to the screen", () => {
    renderFields({ state: { ok: true } });

    expect(screen.getByRole("status")).toHaveTextContent("Key attached");
  });

  it("blocks a second submit while the first is in flight", () => {
    renderFields({ pending: true });

    const submit = screen.getByRole("button", { name: /attaching/i });
    expect(submit).toBeDisabled();
  });

  it("offers a way back that leaves the form behind", () => {
    renderFields();

    expect(screen.getByRole("link", { name: /cancel/i })).toHaveAttribute(
      "href",
      "/accounts/acct-1",
    );
  });
});

describe("saved request defaults (OME-1322)", () => {
  // FEATURE: OME-1138 Stage C — request parameters are the caller's, per request; the console no
  // longer offers to save them on a credential.
  it("offers no control for a saved default", () => {
    const { container } = renderFields();

    expect(screen.queryByText(/defaults/i)).toBeNull();
    for (const label of [/^model$/i, /temperature/i, /max tokens/i]) {
      expect(screen.queryByLabelText(label)).toBeNull();
    }
    for (const name of [
      "model",
      "system_prompt",
      "max_tokens",
      "temperature",
      "timeout_seconds",
      "reasoning_effort",
    ]) {
      expect(container.querySelector(`[name="${name}"]`)).toBeNull();
    }
    expect(container.querySelector("fieldset")).toBeNull();
  });

  it("still submits the account, provider, name and write-only key", () => {
    const { container } = renderFields();

    const names = Array.from(container.querySelectorAll("[name]"), (el) => el.getAttribute("name"));
    expect(names).toEqual(["account_id", "provider", "name", "api_key"]);
  });
});
