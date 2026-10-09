import { EngineError, kindForStatus } from "./errors";
import type {
  BenchmarkSummary,
  Connection,
  EngineModel,
  OAuthAuthorization,
} from "./types";

export type EngineClient = {
  listConnections(): Promise<Connection[]>;
  connectApiKey(provider: string, apiKey: string): Promise<Connection>;
  startOAuth(provider: string): Promise<OAuthAuthorization>;
  disconnect(provider: string): Promise<Connection>;
  listModels(): Promise<EngineModel[]>;
  listBenchmarks(): Promise<BenchmarkSummary[]>;
  health(): Promise<void>;
};

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  // A value that must never reach an error message, even if the server echoes it.
  secret?: string;
};

function redact(text: string | undefined, secret: string | undefined) {
  if (!text || !secret) return text;
  return text.split(secret).join("[redacted]");
}

export async function problemDetail(response: Response): Promise<string | undefined> {
  // WHY only problem+json / JSON: a proxy's HTML error page is noise, not a message for the user.
  const type = response.headers.get("content-type") ?? "";
  if (!type.includes("json")) return undefined;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const { detail } = body as { detail: unknown };
      if (typeof detail === "string") return detail;
    }
  } catch {
    // Malformed error body: fall back to the generic detail.
  }
  return undefined;
}

function listData<T>(body: unknown): T[] {
  if (
    body &&
    typeof body === "object" &&
    Array.isArray((body as { data?: unknown }).data)
  ) {
    return (body as { data: T[] }).data;
  }
  throw new EngineError("unknown");
}

// A thin typed client for the Engine routes Studio uses. It never sends `X-Profile` (the Engine
// answers 400) and never puts an API key in an error.
export function createEngineClient(
  baseUrl: string,
  fetchImpl: typeof fetch = (...args) => fetch(...args),
): EngineClient {
  const origin = baseUrl.replace(/\/+$/, "");

  async function request(path: string, options: RequestOptions = {}) {
    const { method = "GET", body, secret } = options;
    const headers: Record<string, string> = { accept: "application/json" };
    if (body !== undefined) headers["content-type"] = "application/json";

    let response: Response;
    try {
      response = await fetchImpl(`${origin}${path}`, {
        method,
        headers,
        cache: "no-store",
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new EngineError("unreachable");
    }

    if (!response.ok) {
      const detail = redact(await problemDetail(response), secret);
      throw new EngineError(kindForStatus(response.status), detail, response.status);
    }
    try {
      return (await response.json()) as unknown;
    } catch {
      throw new EngineError("unknown", undefined, response.status);
    }
  }

  const connectionPath = (provider: string) =>
    `/v1/connections/${encodeURIComponent(provider)}`;

  return {
    async listConnections() {
      return listData<Connection>(await request("/v1/connections"));
    },
    async connectApiKey(provider, apiKey) {
      return (await request(connectionPath(provider), {
        method: "PUT",
        body: { api_key: apiKey },
        secret: apiKey,
      })) as Connection;
    },
    async startOAuth(provider) {
      return (await request(`${connectionPath(provider)}/oauth`, {
        method: "POST",
      })) as OAuthAuthorization;
    },
    async disconnect(provider) {
      return (await request(connectionPath(provider), {
        method: "DELETE",
      })) as Connection;
    },
    async listModels() {
      return listData<EngineModel>(await request("/v1/models"));
    },
    async listBenchmarks() {
      return listData<BenchmarkSummary>(await request("/v1/benchmarks"));
    },
    async health() {
      await request("/healthz");
    },
  };
}
