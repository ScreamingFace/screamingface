import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { EngineClient } from "@/lib/engine/client";
import { EngineError } from "@/lib/engine/errors";
import type { Connection, EngineModel } from "@/lib/engine/types";

const client = vi.hoisted(() => ({
  listConnections: vi.fn(),
  connectApiKey: vi.fn(),
  startOAuth: vi.fn(),
  disconnect: vi.fn(),
  listModels: vi.fn(),
  health: vi.fn(),
}));

vi.mock("@/lib/engine", () => ({
  getEngineClient: async () => client as unknown as EngineClient,
}));

vi.mock("@/lib/tauri", () => ({
  openExternal: vi.fn(async () => undefined),
  tauriInvoke: () => null,
}));

import { useModelStore } from "@/lib/model-store";
import { type SoloNode, parseRecipe } from "@/lib/recipe";
import ModelsPage from "./page";

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

const MODELS: EngineModel[] = [
  { id: "openrouter/model-a", owned_by: "openrouter" },
  { id: "codex/gpt-5", owned_by: "codex" },
  { id: "mystery/m1", owned_by: "mystery" },
];

let connections: Connection[];

beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  useModelStore.setState({
    connections: [],
    models: [],
    load: "idle",
    error: null,
    library: [],
  });
  connections = [
    connection("openrouter", "OpenRouter"),
    connection("codex", "Codex", { auth_methods: ["oauth"] }),
    connection("openai", "OpenAI", { status: "connected" }),
  ];
  client.listConnections.mockImplementation(async () => connections);
  client.listModels.mockResolvedValue(MODELS);
});

async function openProvider(name: string) {
  const user = userEvent.setup();
  render(<ModelsPage />);
  const row = await screen.findByRole("button", { name: new RegExp(`^${name}`) });
  // The first connected provider is selected on load, and clicking a selected row deselects it.
  if (row.getAttribute("aria-pressed") !== "true") await user.click(row);
  return user;
}

describe("ModelsPage", () => {
  it("shows the unreachable state and retries", async () => {
    client.listConnections.mockRejectedValueOnce(new EngineError("unreachable"));
    const user = userEvent.setup();
    render(<ModelsPage />);

    expect(
      await screen.findByText("The local ScreamingFace runtime isn't reachable."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("button", { name: /^OpenRouter/ })).toBeInTheDocument();
  });

  it("groups providers, including one Studio does not know under Other", async () => {
    render(<ModelsPage />);

    await screen.findByRole("button", { name: /^OpenRouter/ });
    expect(screen.getByRole("heading", { name: "Other" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Mystery/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Hubs" })).toBeInTheDocument();
  });

  it("connects an API key, refreshes, and clears the field", async () => {
    client.connectApiKey.mockImplementation(async () => {
      connections = [
        connection("openrouter", "OpenRouter", { status: "connected" }),
        ...connections.slice(1),
      ];
      return connections[0];
    });
    const user = await openProvider("OpenRouter");

    const field = screen.getByLabelText("API Key");
    await user.type(field, "sk-or-good");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(client.connectApiKey).toHaveBeenCalledWith("openrouter", "sk-or-good");
    expect(screen.getByRole("button", { name: "Star openrouter/model-a" })).toBeEnabled();
  });

  it("shows a rejected key's detail inline and clears the field", async () => {
    client.connectApiKey.mockRejectedValue(
      new EngineError("unauthenticated", "the provider connection was rejected", 401),
    );
    const user = await openProvider("OpenRouter");

    const field = screen.getByLabelText("API Key");
    await user.type(field, "sk-or-bad");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "the provider connection was rejected",
    );
    expect(field).toHaveValue("");
  });

  it("waits on OAuth sign-in and cancels it", async () => {
    client.startOAuth.mockResolvedValue({
      object: "oauth_authorization",
      provider: "codex",
      authorize_url: "https://auth.example/a",
      expires_in: 600,
    });
    client.disconnect.mockResolvedValue(connection("codex", "Codex"));
    connections = connections.map((row) =>
      row.provider === "codex" ? { ...row, status: "pending" } : row,
    );
    const user = await openProvider("Codex");
    connections = connections.map((row) =>
      row.provider === "codex" ? { ...row, status: "not_connected" } : row,
    );

    // A pending flow the page did not start offers only a cancel.
    expect(screen.getByRole("button", { name: "Cancel sign-in" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel sign-in" }));
    await waitFor(() => expect(client.disconnect).toHaveBeenCalledWith("codex"));

    await user.click(await screen.findByRole("button", { name: "Sign in with Codex" }));
    expect(await screen.findByText("Waiting for sign-in…")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(client.disconnect).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("button", { name: "Sign in with Codex" })).toBeEnabled();
  });

  it("clears an expired OAuth credential before signing in again", async () => {
    connections = connections.map((row) =>
      row.provider === "codex" ? { ...row, status: "needs_reauth" } : row,
    );
    client.disconnect.mockResolvedValue(connection("codex", "Codex"));
    client.startOAuth.mockRejectedValue(new EngineError("unreachable"));
    const user = await openProvider("Codex");

    expect(screen.getByText(/credential stopped working/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Sign in with Codex" }));

    await waitFor(() => expect(client.startOAuth).toHaveBeenCalled());
    expect(client.disconnect).toHaveBeenCalledWith("codex");
    expect(client.disconnect.mock.invocationCallOrder[0]).toBeLessThan(
      client.startOAuth.mock.invocationCallOrder[0],
    );
  });

  it("clears an errored credential before connecting an API key", async () => {
    connections = connections.map((row) =>
      row.provider === "openrouter" ? { ...row, status: "error" } : row,
    );
    client.disconnect.mockResolvedValue(connection("openrouter", "OpenRouter"));
    client.connectApiKey.mockResolvedValue(
      connection("openrouter", "OpenRouter", { status: "connected" }),
    );
    const user = await openProvider("OpenRouter");

    await user.type(screen.getByLabelText("API Key"), "sk-or-new");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() =>
      expect(client.connectApiKey).toHaveBeenCalledWith("openrouter", "sk-or-new"),
    );
    expect(client.disconnect.mock.invocationCallOrder[0]).toBeLessThan(
      client.connectApiKey.mock.invocationCallOrder[0],
    );
  });

  it("does not clear a working credential before connecting an API key", async () => {
    client.connectApiKey.mockResolvedValue(
      connection("openrouter", "OpenRouter", { status: "connected" }),
    );
    const user = await openProvider("OpenRouter");

    await user.type(screen.getByLabelText("API Key"), "sk-or-good");
    await user.click(screen.getByRole("button", { name: "Connect" }));

    await waitFor(() => expect(client.connectApiKey).toHaveBeenCalled());
    expect(client.disconnect).not.toHaveBeenCalled();
  });

  it("previews an unconnected provider's models with starring disabled", async () => {
    await openProvider("OpenRouter");

    expect(
      screen.getByText("Preview. Connect OpenRouter to star these models."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Connect OpenRouter to star openrouter/model-a",
      }),
    ).toBeDisabled();
  });

  it("says so when a connected provider has no models on this Engine", async () => {
    await openProvider("OpenAI");
    expect(
      screen.getByText("This Engine lists no models for OpenAI yet."),
    ).toBeInTheDocument();
  });

  it("disconnects a connected provider", async () => {
    client.disconnect.mockResolvedValue(connection("openai", "OpenAI"));
    const user = await openProvider("OpenAI");

    await user.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(client.disconnect).toHaveBeenCalledWith("openai"));
  });

  it("keeps the OpenMined key switch disabled", async () => {
    await openProvider("OpenRouter");
    expect(
      screen.getByRole("switch", { name: "Use OpenMined key (subsidized)" }),
    ).toBeDisabled();
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
  });

  it("stars a model and marks a starred model the Engine no longer lists", async () => {
    connections = [connection("openrouter", "OpenRouter", { status: "connected" })];
    useModelStore.setState({
      library: [
        { id: "gone/old", name: "gone/old", providerId: "gone", providerName: "Gone" },
      ],
    });
    const user = await openProvider("OpenRouter");

    await user.click(screen.getByRole("button", { name: "Star openrouter/model-a" }));
    await user.click(screen.getByRole("button", { name: /^Starred/ }));

    const main = screen.getByRole("main");
    expect(within(main).getByText("openrouter/model-a")).toBeInTheDocument();
    expect(within(main).getByText("Unavailable")).toBeInTheDocument();
    expect(
      within(main).getByRole("checkbox", { name: "Select gone/old for composing" }),
    ).toBeDisabled();
  });

  it("marks a starred model unavailable when its provider is not connected", async () => {
    useModelStore.setState({
      library: [
        {
          id: "openrouter/model-a",
          name: "openrouter/model-a",
          providerId: "openrouter",
          providerName: "OpenRouter",
        },
      ],
    });
    const user = userEvent.setup();
    render(<ModelsPage />);

    await screen.findByRole("button", { name: /^OpenRouter/ });
    await user.click(screen.getByRole("button", { name: /^Starred/ }));

    const main = screen.getByRole("main");
    expect(within(main).getByText("Unavailable")).toBeInTheDocument();
    expect(
      within(main).getByRole("checkbox", {
        name: "Select openrouter/model-a for composing",
      }),
    ).toBeDisabled();
  });
  it("composes the checked models into a recipe the builder can import", async () => {
    connections = [connection("openrouter", "OpenRouter", { status: "connected" })];
    useModelStore.setState({
      library: [
        {
          id: "openrouter/model-a",
          name: "openrouter/model-a",
          providerId: "openrouter",
          providerName: "OpenRouter",
        },
      ],
    });
    const user = await openProvider("OpenRouter");
    await user.click(screen.getByRole("button", { name: /^Starred/ }));
    await user.click(
      within(screen.getByRole("main")).getByRole("checkbox", {
        name: "Select openrouter/model-a for composing",
      }),
    );

    const link = screen.getByRole("link", { name: "Compose a Fusion" });
    const recipe = new URL(link.getAttribute("href") ?? "", "http://studio").searchParams.get(
      "recipe",
    );
    const parsed = parseRecipe(recipe ?? "");
    expect(parsed.ok).toBe(true);
    if (!parsed.ok || parsed.root.kind !== "fusion") throw new Error("not a fusion");
    expect(parsed.root.members.map((member) => (member as SoloNode).model?.id)).toEqual([
      "openrouter/model-a",
    ]);
  });
});
