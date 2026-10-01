import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { EngineClient } from "@/lib/engine/client";
import { EngineError } from "@/lib/engine/errors";
import type { EngineModel } from "@/lib/engine/types";

const client = vi.hoisted(() => ({
  listConnections: vi.fn(),
  listModels: vi.fn(),
}));

const search = vi.hoisted(() => ({ params: new URLSearchParams() }));

vi.mock("@/lib/engine", () => ({
  getEngineClient: async () => client as unknown as EngineClient,
}));

vi.mock("@/lib/tauri", () => ({
  openExternal: vi.fn(async () => undefined),
  tauriInvoke: () => null,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => search.params,
}));

import { useEnsembleStore } from "@/lib/ensemble-store";
import { useModelStore } from "@/lib/model-store";
import EnsembleComposerPage from "./page";

const MODELS: EngineModel[] = [
  { id: "ollama/llama3", owned_by: "ollama" },
  { id: "ollama/qwen", owned_by: "ollama" },
];

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
  useEnsembleStore.setState({ hasHydrated: true });
  client.listConnections.mockResolvedValue([]);
  client.listModels.mockResolvedValue(MODELS);
});

function openRecipe(recipe: string) {
  search.params = new URLSearchParams({ recipe });
  render(<EnsembleComposerPage />);
}

describe("EnsembleComposerPage recipe import", () => {
  it("waits for a failed catalog load and imports once a retry succeeds", async () => {
    client.listConnections.mockRejectedValueOnce(new EngineError("unreachable"));
    const user = userEvent.setup();
    openRecipe("url4://shared?models=ollama/llama3+ollama/qwen");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "this recipe can't be imported yet",
    );
    expect(screen.queryByText("shared")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("shared")).toBeInTheDocument();
    expect(await screen.findByText("2 models · 0 runs")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names the models it left out because the catalog doesn't have them", async () => {
    openRecipe("url4://shared?models=ollama/llama3+gone/old");

    expect(await screen.findByText("shared")).toBeInTheDocument();
    expect(await screen.findByText("1 models · 0 runs")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("gone/old");
  });
});
