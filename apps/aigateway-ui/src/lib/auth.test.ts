/**
 * `describeFailure` is the one place an error kind becomes advice. D18 §7 makes that advice a
 * contract: a retryable lost CAS says "try again"; a superseded, ambiguous or unresolved pair never
 * does — repeating the same write would either clobber a change the operator has not seen or hit
 * the same refusal; and a credential storage outage is temporary, not "the admin API is disabled".
 */
vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ headers: async () => ({ get: () => null }) }));

const { AdminApiError } = await import("./aigateway/client");
const { describeFailure } = await import("./auth");

describe("describeFailure for the pair-addressed credential API", () => {
  it("keeps the retryable conflict for a lost CAS", () => {
    const failure = describeFailure(new AdminApiError("conflict", 503, "m"));

    expect(failure.retryable).toBe(true);
    expect(failure.message).toMatch(/try again/i);
  });

  it("tells the operator to reload, never to resubmit, when the credential changed", () => {
    const failure = describeFailure(new AdminApiError("superseded", 409, "m"));

    expect(failure.retryable).toBe(false);
    expect(failure.message).toMatch(/reload/i);
    expect(failure.message).not.toMatch(/try again/i);
  });

  it("asks for the duplicate to be resolved when the pair is ambiguous", () => {
    const failure = describeFailure(new AdminApiError("ambiguous", 409, "m"));

    expect(failure.retryable).toBe(false);
    expect(failure.message).toMatch(/more than one credential/i);
    expect(failure.message).not.toMatch(/try again/i);
  });

  it("routes an unresolved pair to an operator", () => {
    const failure = describeFailure(new AdminApiError("unresolved", 409, "m"));

    expect(failure.retryable).toBe(false);
    expect(failure.message).toMatch(/operator/i);
    expect(failure.message).not.toMatch(/try again/i);
  });

  it("reads a storage or authority outage as temporary, not as a disabled admin API", () => {
    const temporary = describeFailure(new AdminApiError("temporary", 503, "m"));
    const disabled = describeFailure(new AdminApiError("unavailable", 503, "m"));

    expect(temporary.retryable).toBe(true);
    expect(temporary.title).not.toBe(disabled.title);
    expect(temporary.message).not.toMatch(/deployment setting/i);
  });

  it("says what was temporarily unavailable in the gateway's own words", () => {
    // Storage outages and a provider key check that could not run share the kind; only the
    // gateway's controlled message tells them apart.
    const failure = describeFailure(
      new AdminApiError("temporary", 503, "The provider could not complete validation. Try again later."),
    );

    expect(failure.message).toBe("The provider could not complete validation. Try again later.");
    expect(failure.retryable).toBe(true);
  });

  it("still rethrows anything that is not an AdminApiError", () => {
    expect(() => describeFailure(new TypeError("boom"))).toThrow(TypeError);
  });
});

// This file uses vitest globals, so the top-level `await import` needs an explicit module marker.
export {};
