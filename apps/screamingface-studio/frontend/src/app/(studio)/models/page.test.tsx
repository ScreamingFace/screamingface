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
});
