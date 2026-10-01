import type { EngineClient } from "./client";
import { EngineError } from "./errors";
import type { Connection } from "./types";

export type OAuthOptions = {
  open: (url: string) => Promise<void> | void;
  intervalMs?: number;
  signal?: AbortSignal;
};

function sleep(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

async function cancel(client: EngineClient, provider: string) {
  return client.disconnect(provider);
}

// Runs one OAuth sign-in the way the Python Client's `OAuthFlow.wait` does: open the provider's
// authorize page, then poll the connection until it leaves `pending`.
//
// WHY no deep link: on the local runtime AI Gateway owns the redirect — a loopback listener or
// its own `/callback` — and finishes the code exchange itself. Studio only watches the status.
export async function runOAuth(
  client: EngineClient,
  provider: string,
  { open, intervalMs = 1000, signal }: OAuthOptions,
): Promise<Connection> {
  const authorization = await client.startOAuth(provider);
  const deadline = Date.now() + authorization.expires_in * 1000;
  await open(authorization.authorize_url);

  while (true) {
    if (signal?.aborted) return cancel(client, provider);
    if (Date.now() >= deadline) {
      // Clears the pending row so the page doesn't keep showing a flow nobody can finish.
      await cancel(client, provider).catch(() => undefined);
      throw new EngineError("invalid", "Sign-in expired. Try again.");
    }

    await sleep(intervalMs, signal);
    if (signal?.aborted) return cancel(client, provider);

    let connections: Connection[];
    try {
      connections = await client.listConnections();
    } catch (error) {
      if (error instanceof EngineError && error.kind === "unreachable") continue;
      throw error;
    }
    const current = connections.find((row) => row.provider === provider);
    if (!current) throw new EngineError("not_found");
    if (current.status !== "pending") return current;
  }
}
