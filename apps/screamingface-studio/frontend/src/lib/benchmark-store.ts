"use client";

import { create } from "zustand";

import { getEngineClient } from "@/lib/engine";
import { asEngineError, type EngineError } from "@/lib/engine/errors";
import type { BenchmarkSummary } from "@/lib/engine/types";
import type { LoadState } from "@/lib/model-store";

type BenchmarkState = {
  status: LoadState;
  benchmarks: BenchmarkSummary[];
  error: EngineError | null;
  refresh: () => Promise<void>;
};

// WHY a sequence number, not one shared request: the Run panel and a Retry click can both ask at
// once. Only the newest request may write, and a request that never settles can't hold up the next.
let refreshSequence = 0;

// The Engine's installed benchmarks (`GET /v1/benchmarks`). Server state only: kept in memory,
// never persisted, so a restarted runtime with other datasets is picked up on the next refresh.
export const useBenchmarkStore = create<BenchmarkState>()((set, get) => ({
  status: "idle",
  benchmarks: [],
  error: null,

  refresh: async () => {
    const sequence = ++refreshSequence;
    // A loaded list stays on screen while it refreshes.
    if (get().status !== "ready") set({ status: "loading" });
    try {
      const client = await getEngineClient();
      const benchmarks = await client.listBenchmarks();
      if (sequence !== refreshSequence) return;
      set({ benchmarks, status: "ready", error: null });
    } catch (error) {
      if (sequence !== refreshSequence) return;
      set({ status: "error", error: asEngineError(error) });
    }
  },
}));
