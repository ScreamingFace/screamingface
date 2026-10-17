import type { EngineClient } from "./engine/client";
import { EngineError } from "./engine/errors";
import type { BenchmarkSummary } from "./engine/types";

const client = vi.hoisted(() => ({ listBenchmarks: vi.fn() }));

vi.mock("./engine", () => ({
  getEngineClient: async () => client as unknown as EngineClient,
}));

import { useBenchmarkStore } from "./benchmark-store";

const IFEVAL: BenchmarkSummary = {
  id: "ifeval",
  title: "IFEval",
  description: "Verifiable instruction following.",
  revision: "r1",
  case_count: 541,
  origin: "inspect_evals",
  difficulty: "standard",
  interaction: "single_shot",
  failure_policy: "withhold",
  href: "/v1/benchmarks/ifeval",
};

beforeEach(() => {
  vi.resetAllMocks();
  useBenchmarkStore.setState({ status: "idle", benchmarks: [], error: null });
});

describe("useBenchmarkStore", () => {
  it("starts idle with nothing loaded", () => {
    expect(useBenchmarkStore.getState()).toMatchObject({
      status: "idle",
      benchmarks: [],
      error: null,
    });
  });

  it("moves loading → ready with the Engine's catalog", async () => {
    let release: (rows: BenchmarkSummary[]) => void = () => {};
    client.listBenchmarks.mockReturnValue(
      new Promise<BenchmarkSummary[]>((resolve) => (release = resolve)),
    );

    const pending = useBenchmarkStore.getState().refresh();
    await vi.waitFor(() => expect(client.listBenchmarks).toHaveBeenCalled());
    expect(useBenchmarkStore.getState().status).toBe("loading");

    release([IFEVAL]);
    await pending;
    expect(useBenchmarkStore.getState()).toMatchObject({
      status: "ready",
      benchmarks: [IFEVAL],
      error: null,
    });
  });

  it("moves loading → error with the Engine's error, and a retry recovers", async () => {
    const failure = new EngineError("unreachable");
    client.listBenchmarks.mockRejectedValueOnce(failure);

    await useBenchmarkStore.getState().refresh();
    expect(useBenchmarkStore.getState()).toMatchObject({
      status: "error",
      error: failure,
    });

    client.listBenchmarks.mockResolvedValueOnce([IFEVAL]);
    await useBenchmarkStore.getState().refresh();
    expect(useBenchmarkStore.getState()).toMatchObject({
      status: "ready",
      benchmarks: [IFEVAL],
      error: null,
    });
  });

  it("wraps a non-Engine failure as an unknown EngineError", async () => {
    client.listBenchmarks.mockRejectedValueOnce(new Error("boom"));

    await useBenchmarkStore.getState().refresh();
    const { error } = useBenchmarkStore.getState();
    expect(error).toBeInstanceOf(EngineError);
    expect(error?.kind).toBe("unknown");
  });

  it("makes one request for two concurrent refreshes", async () => {
    client.listBenchmarks.mockResolvedValue([IFEVAL]);

    await Promise.all([
      useBenchmarkStore.getState().refresh(),
      useBenchmarkStore.getState().refresh(),
    ]);

    expect(client.listBenchmarks).toHaveBeenCalledTimes(1);
    expect(useBenchmarkStore.getState().status).toBe("ready");
  });

  it("keeps the loaded list on screen while a later refresh runs", async () => {
    client.listBenchmarks.mockResolvedValueOnce([IFEVAL]);
    await useBenchmarkStore.getState().refresh();

    let release: (rows: BenchmarkSummary[]) => void = () => {};
    client.listBenchmarks.mockReturnValueOnce(
      new Promise<BenchmarkSummary[]>((resolve) => (release = resolve)),
    );
    const pending = useBenchmarkStore.getState().refresh();

    expect(useBenchmarkStore.getState()).toMatchObject({
      status: "ready",
      benchmarks: [IFEVAL],
    });
    release([]);
    await pending;
  });

  it("refreshes again once the previous request has settled", async () => {
    client.listBenchmarks.mockResolvedValue([IFEVAL]);

    await useBenchmarkStore.getState().refresh();
    await useBenchmarkStore.getState().refresh();

    expect(client.listBenchmarks).toHaveBeenCalledTimes(2);
  });
});
