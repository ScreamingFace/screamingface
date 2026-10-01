import type { EngineClient } from "./engine/client";
import { EngineError } from "./engine/errors";
import type { Connection, EngineModel } from "./engine/types";

const client = vi.hoisted(() => ({
  listConnections: vi.fn(),
  connectApiKey: vi.fn(),
  startOAuth: vi.fn(),
  disconnect: vi.fn(),
  listModels: vi.fn(),
  health: vi.fn(),
}));

vi.mock("./engine", () => ({
  getEngineClient: async () => client as unknown as EngineClient,
}));

import {
  MODEL_STORE_KEY,
  buildProviders,
  toSavedModel,
  useModelStore,
} from "./model-store";

function connection(
  provider: string,
  display_name: string,
  overrides: Partial<Connection> = {},
): Connection {
  return {
    object: "connection",
    provider,
    display_name,
    auth_methods: ["api_key"],
    status: "not_connected",
    ...overrides,
  };
}

function model(id: string): EngineModel {
  return { id, owned_by: id.split("/")[0] };
}

const CONNECTIONS = [
  connection("openrouter", "OpenRouter", { status: "connected" }),
  connection("codex", "Codex", { auth_methods: ["oauth"] }),
  connection("openai", "OpenAI", { status: "connected" }),
  connection("mystery", "Mystery"),
];

const MODELS = [
  model("openrouter/b"),
  model("openrouter/a"),
  model("codex/gpt-5"),
  model("ollama/llama3"),
];

function resetStore() {
  useModelStore.setState({
    connections: [],
    models: [],
    load: "idle",
    error: null,
    library: [],
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  resetStore();
});

describe("buildProviders", () => {
  const providers = buildProviders(CONNECTIONS, MODELS);

  it("orders providers by presentation group, then by name", () => {
    expect(providers.map((provider) => provider.id)).toEqual([
      "codex",
      "ollama",
      "openai",
      "openrouter",
      "mystery",
    ]);
  });

  it("adds a keyless row for a model owner with no connection", () => {
    const ollama = providers.find((provider) => provider.id === "ollama")!;
    expect(ollama).toMatchObject({
      name: "Ollama",
      keyless: true,
      connected: true,
      authMethods: [],
      group: "Local & Sessions",
    });
    expect(ollama.models.map((item) => item.id)).toEqual(["ollama/llama3"]);
  });

  it("is connected only when the Engine says so", () => {
    const byId = Object.fromEntries(providers.map((p) => [p.id, p]));
    expect(byId.openrouter.connected).toBe(true);
    expect(byId.codex.connected).toBe(false);
  });

  it("keeps a connected provider with no models", () => {
    const openai = providers.find((provider) => provider.id === "openai")!;
    expect(openai.connected).toBe(true);
    expect(openai.models).toEqual([]);
  });

  it("maps models to saved models under the Engine's display name, sorted by id", () => {
    const openrouter = providers.find((provider) => provider.id === "openrouter")!;
    expect(openrouter.models).toEqual([
      {
        id: "openrouter/a",
        name: "openrouter/a",
        providerId: "openrouter",
        providerName: "OpenRouter",
      },
      {
        id: "openrouter/b",
        name: "openrouter/b",
        providerId: "openrouter",
        providerName: "OpenRouter",
      },
    ]);
  });

  it("puts an unknown provider under Other", () => {
    const mystery = providers.find((provider) => provider.id === "mystery")!;
    expect(mystery.group).toBe("Other");
  });
});

describe("toSavedModel", () => {
  it("falls back to the owner id when no display name is known", () => {
    expect(toSavedModel(model("x/y"))).toEqual({
      id: "x/y",
      name: "x/y",
      providerId: "x",
      providerName: "x",
    });
  });
});

describe("refresh", () => {
  it("loads connections and models", async () => {
    client.listConnections.mockResolvedValue(CONNECTIONS);
    client.listModels.mockResolvedValue(MODELS);

    await useModelStore.getState().refresh();

    const state = useModelStore.getState();
    expect(state.load).toBe("ready");
    expect(state.connections).toEqual(CONNECTIONS);
    expect(state.models).toEqual(MODELS);
    expect(state.error).toBeNull();
  });

  it("records the error when the Engine is unreachable", async () => {
    client.listConnections.mockRejectedValue(new EngineError("unreachable"));
    client.listModels.mockResolvedValue([]);

    await useModelStore.getState().refresh();

    const state = useModelStore.getState();
    expect(state.load).toBe("error");
    expect(state.error).toMatchObject({ kind: "unreachable" });
  });

  it("wraps a non-Engine failure", async () => {
    client.listConnections.mockRejectedValue(new Error("boom"));
    client.listModels.mockResolvedValue([]);

    await useModelStore.getState().refresh();
    expect(useModelStore.getState().error).toMatchObject({ kind: "unknown" });
  });

  it("ignores a stale response that lands after a newer one", async () => {
    let releaseFirst!: (value: Connection[]) => void;
    client.listConnections
      .mockImplementationOnce(
        () => new Promise<Connection[]>((resolve) => (releaseFirst = resolve)),
      )
      .mockResolvedValueOnce([CONNECTIONS[0]]);
    client.listModels.mockResolvedValue([]);

    const first = useModelStore.getState().refresh();
    await useModelStore.getState().refresh();
    releaseFirst(CONNECTIONS);
    await first;

    expect(useModelStore.getState().connections).toEqual([CONNECTIONS[0]]);
  });
});

describe("connection actions", () => {
  beforeEach(() => {
    client.listConnections.mockResolvedValue(CONNECTIONS);
    client.listModels.mockResolvedValue(MODELS);
  });

  it("connects an API key, then refreshes", async () => {
    client.connectApiKey.mockResolvedValue(CONNECTIONS[0]);

    await useModelStore.getState().connectApiKey("openrouter", "sk-1");

    expect(client.connectApiKey).toHaveBeenCalledWith("openrouter", "sk-1");
    expect(client.listConnections).toHaveBeenCalled();
    expect(JSON.stringify(useModelStore.getState())).not.toContain("sk-1");
  });

  it("lets a rejected key reach the caller", async () => {
    client.connectApiKey.mockRejectedValue(new EngineError("unauthenticated"));

    await expect(
      useModelStore.getState().connectApiKey("openrouter", "bad"),
    ).rejects.toMatchObject({ kind: "unauthenticated" });
  });

  it("disconnects, then refreshes", async () => {
    client.disconnect.mockResolvedValue(CONNECTIONS[1]);

    await useModelStore.getState().disconnect("openrouter");

    expect(client.disconnect).toHaveBeenCalledWith("openrouter");
    expect(client.listConnections).toHaveBeenCalled();
  });

  it("signs in with OAuth, then refreshes", async () => {
    vi.useFakeTimers();
    try {
      client.startOAuth.mockResolvedValue({
        object: "oauth_authorization",
        provider: "codex",
        authorize_url: "https://auth.example/a",
        expires_in: 60,
      });
      client.listConnections.mockResolvedValue([
        connection("codex", "Codex", { auth_methods: ["oauth"], status: "connected" }),
      ]);
      const open = vi.fn();

      const result = useModelStore.getState().signIn("codex", { open });
      await vi.advanceTimersByTimeAsync(1000);

      await expect(result).resolves.toMatchObject({ status: "connected" });
      expect(open).toHaveBeenCalledWith("https://auth.example/a");
      expect(useModelStore.getState().connections[0].status).toBe("connected");
    } finally {
      vi.useRealTimers();
    }
  });

  it("refreshes even when sign-in fails", async () => {
    client.startOAuth.mockRejectedValue(new EngineError("invalid", "no"));

    await expect(
      useModelStore.getState().signIn("codex", { open: vi.fn() }),
    ).rejects.toMatchObject({ kind: "invalid" });
    expect(client.listConnections).toHaveBeenCalled();
  });
});

describe("library", () => {
  const saved = toSavedModel(model("openrouter/a"), "OpenRouter");

  it("toggles a model in and out", () => {
    useModelStore.getState().toggleLibraryModel(saved);
    expect(useModelStore.getState().library).toEqual([saved]);
    useModelStore.getState().toggleLibraryModel(saved);
    expect(useModelStore.getState().library).toEqual([]);
  });

  it("adds models without duplicates", () => {
    useModelStore.getState().addLibraryModels([saved, saved]);
    useModelStore.getState().addLibraryModels([saved]);
    expect(useModelStore.getState().library).toEqual([saved]);
  });

  it("persists only the library", async () => {
    client.listConnections.mockResolvedValue(CONNECTIONS);
    client.listModels.mockResolvedValue(MODELS);
    await useModelStore.getState().refresh();
    useModelStore.getState().toggleLibraryModel(saved);

    const stored = JSON.parse(localStorage.getItem(MODEL_STORE_KEY)!);
    expect(stored.version).toBe(2);
    expect(Object.keys(stored.state)).toEqual(["library"]);
  });

  it("drops the v1 mock library and providers on migration", async () => {
    localStorage.setItem(
      MODEL_STORE_KEY,
      JSON.stringify({
        version: 0,
        state: {
          library: [{ id: "ol-1", name: "ollama/llama-3.3-70b", providerId: "ollama", providerName: "Ollama" }],
          providers: [{ id: "ollama", apiKey: "", connected: true, models: [] }],
        },
      }),
    );

    await useModelStore.persist.rehydrate();

    const state = useModelStore.getState();
    expect(state.library).toEqual([]);
    expect("providers" in state).toBe(false);
  });
});
