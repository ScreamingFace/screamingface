import type { EngineClient } from "./client";
import { EngineError } from "./errors";
import { runOAuth } from "./oauth";
import type { Connection, ConnectionStatus } from "./types";

function row(status: ConnectionStatus, provider = "codex"): Connection {
  return {
    object: "connection",
    provider,
    display_name: "Codex",
    auth_methods: ["oauth"],
    status,
  };
}

function fakeClient(statuses: Array<ConnectionStatus | EngineError>) {
  const queue = [...statuses];
  const client: EngineClient = {
    listConnections: vi.fn(async () => {
      const next = queue.length > 1 ? queue.shift()! : queue[0];
      if (next instanceof EngineError) throw next;
      return [row("connected", "other"), row(next)];
    }),
    connectApiKey: vi.fn(),
    startOAuth: vi.fn(async (provider: string) => ({
      object: "oauth_authorization" as const,
      provider,
      authorize_url: "https://auth.example/authorize",
      expires_in: 5,
    })),
    disconnect: vi.fn(async () => row("not_connected")),
    listModels: vi.fn(),
    listBenchmarks: vi.fn(),
    health: vi.fn(),
  };
  return client;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("runOAuth", () => {
  it("opens the authorize URL and resolves once the provider is connected", async () => {
    const client = fakeClient(["pending", "pending", "connected"]);
    const open = vi.fn(async () => undefined);

    const result = runOAuth(client, "codex", { open, intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(3000);

    await expect(result).resolves.toMatchObject({ status: "connected" });
    expect(client.startOAuth).toHaveBeenCalledWith("codex");
    expect(open).toHaveBeenCalledWith("https://auth.example/authorize");
    expect(client.listConnections).toHaveBeenCalledTimes(3);
  });

  it("stops on an error status", async () => {
    const client = fakeClient(["pending", "error"]);
    const result = runOAuth(client, "codex", { open: vi.fn(), intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(2000);

    await expect(result).resolves.toMatchObject({ status: "error" });
  });

  it("gives up when the authorization expires and clears the pending flow", async () => {
    const client = fakeClient(["pending"]);
    const result = runOAuth(client, "codex", { open: vi.fn(), intervalMs: 1000 });
    const outcome = result.catch((caught: unknown) => caught);
    await vi.advanceTimersByTimeAsync(6000);

    expect(await outcome).toMatchObject({ kind: "invalid", detail: "Sign-in expired. Try again." });
    expect(client.disconnect).toHaveBeenCalledWith("codex");
  });

  it("cancels the flow on abort", async () => {
    const client = fakeClient(["pending"]);
    const controller = new AbortController();
    const result = runOAuth(client, "codex", {
      open: vi.fn(),
      intervalMs: 1000,
      signal: controller.signal,
    });
    await vi.advanceTimersByTimeAsync(1500);
    controller.abort();
    await vi.advanceTimersByTimeAsync(0);

    await expect(result).resolves.toMatchObject({ status: "not_connected" });
    expect(client.disconnect).toHaveBeenCalledWith("codex");
  });

  it("retries a poll that could not reach the Engine", async () => {
    const client = fakeClient([
      "pending",
      new EngineError("unreachable"),
      "connected",
    ]);
    const result = runOAuth(client, "codex", { open: vi.fn(), intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(3000);

    await expect(result).resolves.toMatchObject({ status: "connected" });
  });

  it("fails on any other poll error", async () => {
    const client = fakeClient(["pending", new EngineError("unavailable")]);
    const result = runOAuth(client, "codex", { open: vi.fn(), intervalMs: 1000 });
    const outcome = result.catch((caught: unknown) => caught);
    await vi.advanceTimersByTimeAsync(2000);

    expect(await outcome).toMatchObject({ kind: "unavailable" });
  });

  it("fails when the provider disappears from the connection list", async () => {
    const client = fakeClient(["pending"]);
    vi.mocked(client.listConnections).mockResolvedValue([row("connected", "other")]);
    const result = runOAuth(client, "codex", { open: vi.fn(), intervalMs: 1000 });
    const outcome = result.catch((caught: unknown) => caught);
    await vi.advanceTimersByTimeAsync(1000);

    expect(await outcome).toMatchObject({ kind: "not_found" });
  });
});
