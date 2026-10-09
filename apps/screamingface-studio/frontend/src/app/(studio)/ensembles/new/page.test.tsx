import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { EngineClient } from "@/lib/engine/client";
import { EngineError } from "@/lib/engine/errors";
import type { BenchmarkSummary, EngineModel } from "@/lib/engine/types";

const client = vi.hoisted(() => ({
  listConnections: vi.fn(),
  listModels: vi.fn(),
  listBenchmarks: vi.fn(),
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

import { useBenchmarkStore } from "@/lib/benchmark-store";
import { useEnsembleStore } from "@/lib/ensemble-store";
import { toSavedModel, useModelStore } from "@/lib/model-store";
import { fusionOf, recipeToUrl4 } from "@/lib/recipe";
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

// What Share url4 copies for a fusion of these models: the only form `?recipe=` imports.
function fusionRecipe(...ids: string[]) {
  return recipeToUrl4(fusionOf(ids.map((id) => toSavedModel({ id, owned_by: id.split("/")[0] }))));
}

function openRecipe(recipe: string) {
  search.params = new URLSearchParams({ recipe });
  render(<EnsembleComposerPage />);
}

describe("EnsembleComposerPage recipe import", () => {
  it("waits for a failed catalog load and imports once a retry succeeds", async () => {
    client.listConnections.mockRejectedValueOnce(new EngineError("unreachable"));
    const user = userEvent.setup();
    openRecipe(fusionRecipe("ollama/llama3", "ollama/qwen"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "this recipe can't be imported yet",
    );
    expect(screen.queryByText("2 models · 0 runs")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("2 models · 0 runs")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("names the models it left out because the catalog doesn't have them", async () => {
    openRecipe(fusionRecipe("ollama/llama3", "gone/old"));

    expect(await screen.findByText("1 models · 0 runs")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("gone/old");
  });

  it("refuses the old url4:// form with a message instead of a guess", async () => {
    openRecipe("url4://shared?models=ollama/llama3+ollama/qwen");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This isn't a recipe Studio can import",
    );
    expect(screen.getByText("0 models · 0 runs")).toBeInTheDocument();
  });
});

function benchmark(id: string, title: string, case_count: number): BenchmarkSummary {
  return {
    object: "benchmark",
    id,
    title,
    description: `${title} description.`,
    revision: "r1",
    case_count,
    origin: "screamingface",
    focus: `${title} focus`,
    difficulty: "standard",
    interaction: "single_shot",
    failure_policy: "withhold",
    href: `/v1/benchmarks/${id}`,
  };
}

// The live catalog's ids and case counts (checked 2026-10-05).
const CATALOG: BenchmarkSummary[] = [
  benchmark("contracteval", "ContractEval", 4182),
  benchmark("draco", "DRACO", 100),
  benchmark("draco-3pass", "DRACO 3-Pass", 100),
  benchmark("gdpval-text", "GDPval Text", 102),
  benchmark("healthbench-professional", "HealthBench Professional", 525),
  benchmark("healthbench-worst30", "HealthBench Worst-30", 157),
  benchmark("ifeval", "IFEval", 541),
  benchmark("medxpert", "MedXpertQA", 2450),
];

const TAVILY = "Needs a Tavily web-search key — not available in Studio yet";

describe("EnsembleComposerPage run benchmark picker", () => {
  beforeEach(() => {
    useBenchmarkStore.setState({ status: "idle", benchmarks: [], error: null });
    client.listBenchmarks.mockResolvedValue(CATALOG);
  });

  // A two-model fusion, so only the benchmark choice can hold Run back.
  async function openRuns() {
    const user = userEvent.setup();
    openRecipe(fusionRecipe("ollama/llama3", "ollama/qwen"));
    expect(await screen.findByText("2 models · 0 runs")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Runs" }));
    return user;
  }

  function picker() {
    return screen.getByRole("radiogroup", { name: "Benchmark" });
  }

  it("lists the Engine's benchmarks with title, focus and case count", async () => {
    await openRuns();

    const options = await within(await screen.findByRole("radiogroup", { name: "Benchmark" }))
      .findAllByRole("radio");
    expect(options).toHaveLength(8);
    expect(within(picker()).getByText("IFEval")).toBeInTheDocument();
    expect(within(picker()).getByText("IFEval focus")).toBeInTheDocument();
    expect(within(picker()).getByText("541 cases")).toBeInTheDocument();
    expect(within(picker()).getByText("4,182 cases")).toBeInTheDocument();
    expect(screen.queryByText("GPQA Diamond")).not.toBeInTheDocument();
  });

  it("lists DRACO but disables it with the Tavily label", async () => {
    await openRuns();
    await screen.findByRole("radiogroup", { name: "Benchmark" });

    expect(screen.getByRole("radio", { name: "DRACO" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "DRACO 3-Pass" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "IFEval" })).toBeEnabled();
    expect(screen.getByRole("radio", { name: "DRACO" })).toHaveAccessibleDescription(
      `DRACO focus ${TAVILY}`,
    );
    expect(within(picker()).getAllByText(TAVILY)).toHaveLength(2);
  });

  it("keeps Run disabled until a runnable benchmark is chosen", async () => {
    const user = await openRuns();
    await screen.findByRole("radiogroup", { name: "Benchmark" });

    const run = screen.getByRole("button", { name: /Run Evaluation/ });
    expect(run).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "IFEval" }));
    expect(run).toBeEnabled();
  });

  it("disables a preset larger than the benchmark", async () => {
    client.listBenchmarks.mockResolvedValue([benchmark("small", "Small", 52)]);
    const user = await openRuns();
    await user.click(await screen.findByRole("radio", { name: "Small" }));

    expect(screen.getByRole("button", { name: "100q" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "50q" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "1q" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Full" }));
    expect(screen.getByText("Full benchmark — 52 cases.")).toBeInTheDocument();
  });

  it("clamps a custom sample size to the benchmark's case count", async () => {
    client.listBenchmarks.mockResolvedValue([benchmark("small", "Small", 52)]);
    const user = await openRuns();
    await user.click(await screen.findByRole("radio", { name: "Small" }));
    await user.click(screen.getByRole("button", { name: "Custom" }));

    const input = screen.getByRole("spinbutton", { name: "Custom sample size" });
    await user.clear(input);
    await user.type(input, "9999");

    expect(input).toHaveValue(52);
  });

  it("shows a loading message while the catalog loads", async () => {
    let release: (rows: BenchmarkSummary[]) => void = () => {};
    client.listBenchmarks.mockReturnValue(
      new Promise<BenchmarkSummary[]>((resolve) => (release = resolve)),
    );
    await openRuns();

    expect(await screen.findByText("Loading benchmarks…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run Evaluation/ })).toBeDisabled();

    release(CATALOG);
    expect(await screen.findAllByRole("radio")).toHaveLength(8);
  });

  it("shows an empty catalog inline", async () => {
    client.listBenchmarks.mockResolvedValue([]);
    await openRuns();

    expect(
      await screen.findByText("The Engine has no benchmarks installed."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Run Evaluation/ })).toBeDisabled();
  });

  it("shows a failed load with Retry, and Retry recovers", async () => {
    client.listBenchmarks.mockRejectedValueOnce(new EngineError("unreachable"));
    const user = await openRuns();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load benchmarks");
    expect(alert).toHaveTextContent("The ScreamingFace Engine could not be reached.");

    await user.click(within(alert).getByRole("button", { name: "Retry" }));

    expect(
      await within(await screen.findByRole("radiogroup", { name: "Benchmark" })).findAllByRole(
        "radio",
      ),
    ).toHaveLength(8);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("offers no custom dataset upload", async () => {
    await openRuns();
    await screen.findByRole("radiogroup", { name: "Benchmark" });

    expect(screen.queryByRole("button", { name: /upload/i })).not.toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });
});
