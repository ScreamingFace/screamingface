// What Studio knows about a benchmark that the Engine catalog does not say (plan U3).
//
// `GET /v1/benchmarks` names each benchmark and counts its cases, but it does not say which
// provider grades it or whether it needs web search. Studio needs both before a run: a judge
// whose provider is not connected fails every case at grading, after the answers are paid for,
// and the local runtime has no Tavily key for web search. Until the catalog carries these
// fields, this table records them, the same way `provider-presentation.ts` records a provider's
// group and color.
//
// TEMPORARY: the follow-up unit "Notebook parity: Tavily connection + catalog requirements"
// (spec docs/spec/2026-10-01-studio-compose-fusion-run.md §5) adds `judge` and `requires` to
// the catalog and deletes this table.
//
// An id missing from the table has no requirements, so a benchmark the Engine adds later still
// shows and runs; if it does need a judge, the run row reports the grading failure.

import type { BenchmarkSummary } from "@/lib/engine/types";

export type BenchmarkPresentation = {
  // The provider the benchmark's fixed judge model runs on.
  judgeProvider?: string;
  needsWebSearch: boolean;
};

export const WEB_SEARCH_UNAVAILABLE =
  "Needs a Tavily web-search key — not available in Studio yet";

// Judges as of 2026-10-09: DRACO, DRACO 3-Pass and GDPval Text use
// openrouter/google/gemini-3.1-pro-preview; both HealthBench sets use openrouter/openai/gpt-5.4.
// IFEval, MedXpertQA and ContractEval grade without a judge.
const REQUIREMENTS: Record<string, { judgeProvider?: string; needsWebSearch?: true }> = {
  draco: { judgeProvider: "openrouter", needsWebSearch: true },
  "draco-3pass": { judgeProvider: "openrouter", needsWebSearch: true },
  "gdpval-text": { judgeProvider: "openrouter" },
  "healthbench-professional": { judgeProvider: "openrouter" },
  "healthbench-worst30": { judgeProvider: "openrouter" },
};

export function benchmarkPresentation(id: string): BenchmarkPresentation {
  const { needsWebSearch, ...rest } = REQUIREMENTS[id] ?? {};
  return { ...rest, needsWebSearch: Boolean(needsWebSearch) };
}

const BLURB_LENGTH = 80;

// One line under the title: the catalog's short `focus`, else the description cut to a line.
export function benchmarkBlurb(benchmark: BenchmarkSummary): string {
  if (benchmark.focus) return benchmark.focus;
  const text = benchmark.description.trim();
  if (text.length <= BLURB_LENGTH) return text;
  const cut = text.slice(0, BLURB_LENGTH);
  const space = cut.lastIndexOf(" ");
  return `${(space > 0 ? cut.slice(0, space) : cut).trimEnd()}…`;
}
