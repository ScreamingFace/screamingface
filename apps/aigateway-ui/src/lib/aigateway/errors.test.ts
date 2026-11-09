/**
 * The retired `credential_write_conflict` code (OME-1138 close-out L9).
 *
 * WHY: the gateway stopped sending it in E5a (`routes/provider_access_http.py`, "no 503
 * `credential_write_conflict` any more"), so the console keeps no advice of its own for it. A
 * gateway answer that still carried it would read as its status alone, like any code the
 * console does not know.
 */
import { describe, expect, it } from "vitest";

import { classify } from "./errors";

describe("a retired gateway code is not dispatched before the status", () => {
  it.each([503, 409])("reads %i credential_write_conflict as the bare status", (status) => {
    const detail = { code: "credential_write_conflict", message: "controlled" };

    expect(classify(status, detail)).toBe(classify(status, undefined));
  });

  it("keeps the legacy index conflict retryable", () => {
    // INVARIANT (close-out spec §2, "Keep"): `profile_index_conflict` keeps its mapping.
    expect(classify(503, { code: "profile_index_conflict" })).toBe("conflict");
  });
});
