/**
 * The BFF's server-side logger — the only reader of the chart's `LOG_LEVEL`.
 *
 * INVARIANT: one call is one line of JSON. A log pipeline splits on newlines; a record that spans
 * lines, or a free-text prefix in front of the JSON, is a record nobody can query.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// `server-only` throws outside the react-server condition, which is where vitest runs. The real
// guarantee is enforced by `next build`, not by the test runner.
vi.mock("server-only", () => ({}));

const { log } = await import("./log");

type Spies = Record<"debug" | "info" | "warn" | "error", ReturnType<typeof vi.spyOn>>;
let spies: Spies;

function emitted(): { method: keyof Spies; line: string }[] {
  return (Object.keys(spies) as (keyof Spies)[]).flatMap((method) =>
    spies[method].mock.calls.map((call: unknown[]) => ({ method, line: String(call[0]) })),
  );
}

beforeEach(() => {
  delete process.env.LOG_LEVEL;
  spies = {
    debug: vi.spyOn(console, "debug").mockImplementation(() => {}),
    info: vi.spyOn(console, "info").mockImplementation(() => {}),
    warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
  };
});

afterEach(() => {
  delete process.env.LOG_LEVEL;
  vi.restoreAllMocks();
});

describe("a record", () => {
  it("is exactly one line of JSON carrying level, time, msg and the fields", () => {
    log("error", "bff_admin_error", { path: "/v1/admin/accounts", status: 500 });

    const lines = emitted();
    expect(lines).toHaveLength(1);
    expect(lines[0].line).not.toContain("\n");
    const record = JSON.parse(lines[0].line);
    expect(record).toMatchObject({
      level: "error",
      msg: "bff_admin_error",
      path: "/v1/admin/accounts",
      status: 500,
    });
    expect(Number.isNaN(Date.parse(record.time))).toBe(false);
  });

  it("goes to the console method matching its level", () => {
    process.env.LOG_LEVEL = "debug";

    log("debug", "d");
    log("info", "i");
    log("warn", "w");
    log("error", "e");

    expect(emitted().map((entry) => [entry.method, JSON.parse(entry.line).msg])).toEqual([
      ["debug", "d"],
      ["info", "i"],
      ["warn", "w"],
      ["error", "e"],
    ]);
  });

  it("cannot have its level or message overwritten by a field", () => {
    log("warn", "real", { level: "debug", msg: "forged" });

    const record = JSON.parse(emitted()[0].line);
    expect(record.level).toBe("warn");
    expect(record.msg).toBe("real");
  });
});

describe("LOG_LEVEL", () => {
  it("defaults to info when unset: debug is dropped, info and above are written", () => {
    log("debug", "d");
    log("info", "i");
    log("warn", "w");

    expect(emitted().map((entry) => entry.method)).toEqual(["info", "warn"]);
  });

  it("at error, drops warn and keeps error", () => {
    process.env.LOG_LEVEL = "error";

    log("warn", "w");
    log("error", "e");

    expect(emitted().map((entry) => entry.method)).toEqual(["error"]);
  });

  it("at warn, drops info and keeps warn", () => {
    process.env.LOG_LEVEL = "warn";

    log("info", "i");
    log("warn", "w");

    expect(emitted().map((entry) => entry.method)).toEqual(["warn"]);
  });

  it("is case-insensitive and tolerates surrounding whitespace", () => {
    process.env.LOG_LEVEL = "  ERROR ";

    log("warn", "w");
    log("error", "e");

    expect(emitted().map((entry) => entry.method)).toEqual(["error"]);
  });

  it("falls back to info on an unrecognised value rather than going silent", () => {
    // WHY fall back to info, not to "log nothing": a typo in a Helm value must never be the
    // reason an outage left no trace.
    process.env.LOG_LEVEL = "verbose";

    log("debug", "d");
    log("info", "i");

    expect(emitted().map((entry) => entry.method)).toEqual(["info"]);
  });

  it("is read on every call, so a test or a runtime change takes effect immediately", () => {
    log("info", "before");
    process.env.LOG_LEVEL = "error";
    log("info", "after");

    expect(emitted().map((entry) => JSON.parse(entry.line).msg)).toEqual(["before"]);
  });
});
