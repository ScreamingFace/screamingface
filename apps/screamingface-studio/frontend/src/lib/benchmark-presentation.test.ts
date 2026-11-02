import type { BenchmarkSummary } from "./engine/types";
import {
  WEB_SEARCH_UNAVAILABLE,
  benchmarkBlurb,
  benchmarkPresentation,
} from "./benchmark-presentation";

function summary(overrides: Partial<BenchmarkSummary> = {}): BenchmarkSummary {
  return {
    id: "x",
    title: "X",
    description: "A description.",
    revision: "r1",
    case_count: 10,
    origin: "screamingface",
    difficulty: "standard",
    interaction: "single_shot",
    failure_policy: "withhold",
    href: "/v1/benchmarks/x",
    ...overrides,
  };
}

describe("benchmarkPresentation", () => {
  it.each(["draco", "draco-3pass"])(
    "%s needs web search and is judged through OpenRouter",
    (id) => {
      expect(benchmarkPresentation(id)).toEqual({
        judgeProvider: "openrouter",
        needsWebSearch: true,
      });
    },
  );

  it.each(["healthbench-professional", "healthbench-worst30", "gdpval-text"])(
    "%s is judged through OpenRouter and needs no web search",
    (id) => {
      expect(benchmarkPresentation(id)).toEqual({
        judgeProvider: "openrouter",
        needsWebSearch: false,
      });
    },
  );

  it.each(["ifeval", "medxpert", "contracteval", "a-benchmark-studio-never-heard-of"])(
    "%s has no requirements",
    (id) => {
      expect(benchmarkPresentation(id)).toEqual({ needsWebSearch: false });
    },
  );

  it("names the missing web-search key in the label", () => {
    expect(WEB_SEARCH_UNAVAILABLE).toBe(
      "Needs a Tavily web-search key — not available in Studio yet",
    );
  });
});

describe("benchmarkBlurb", () => {
  it("prefers the focus", () => {
    expect(benchmarkBlurb(summary({ focus: "Medicine" }))).toBe("Medicine");
  });

  it("falls back to a short description as is", () => {
    expect(benchmarkBlurb(summary())).toBe("A description.");
  });

  it("truncates a long description on a word boundary", () => {
    const blurb = benchmarkBlurb(summary({ description: "word ".repeat(40).trim() }));
    expect(blurb.length).toBeLessThanOrEqual(81);
    expect(blurb.endsWith("…")).toBe(true);
    expect(blurb).not.toMatch(/\s…$/);
  });

  it("cuts a long description with no spaces at the limit", () => {
    expect(benchmarkBlurb(summary({ description: "x".repeat(200) }))).toBe(
      `${"x".repeat(80)}…`,
    );
  });
});
