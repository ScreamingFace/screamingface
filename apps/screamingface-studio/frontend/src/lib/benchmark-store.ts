"use client";

import { create } from "zustand";

import { getEngineClient } from "@/lib/engine";
import { EngineError, isEngineError } from "@/lib/engine/errors";
import type { BenchmarkSummary } from "@/lib/engine/types";
import type { LoadState } from "@/lib/model-store";

type BenchmarkState = {
  status: LoadState;
  benchmarks: BenchmarkSummary[];
  error: EngineError | null;
  refresh: () => Promise<void>;
};

// WHY one shared in-flight request: the Run panel and a Retry click can both ask at once, and the
// catalog is the same answer for both. A second caller waits for the first request.
let inFlight: Promise<void> | null = null;

// The Engine's installed benchmarks (`GET /v1/benchmarks`). Server state only: kept in memory,
// never persisted, so a restarted runtime with other datasets is picked up on the next refresh.
export const useBenchmarkStore = create<BenchmarkState>()((set, get) => ({
  status: "idle",
  benchmarks: [],
  error: null,

  refresh: () => {
    if (inFlight) return inFlight;
    // A loaded list stays on screen while it refreshes.
    if (get().status !== "ready") set({ status: "loading" });
    inFlight = (async () => {
      try {
        const client = await getEngineClient();
        const benchmarks = await client.listBenchmarks();
        set({ benchmarks, status: "ready", error: null });
      } catch (error) {
        set({
          status: "error",
          error: isEngineError(error) ? error : new EngineError("unknown"),
        });
      } finally {
        inFlight = null;
      }
    })();
    return inFlight;
  },
}));
