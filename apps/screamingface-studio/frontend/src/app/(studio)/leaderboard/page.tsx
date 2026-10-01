"use client";

import {
  Check,
  Copy,
  ExternalLink,
  GitFork,
  Globe,
  Lock,
  Trophy,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useEnsembleStore } from "@/lib/ensemble-store";
import { providerPresentation } from "@/lib/provider-presentation";
import { cn } from "@/lib/utils";

type LeaderboardEntry = {
  id: string;
  recipe: string;
  author: string;
  models: string[];
  modelIds?: string[];
  benchmark: string;
  score: number;
  baseline: number;
  submittedAt: string;
  kind: "ensemble" | "single";
  source?: string;
  isOwn?: boolean;
  hasPrivateData?: boolean;
};

const seedEntries: LeaderboardEntry[] = [
  { id: "fusion", recipe: "claude-gemini-fusion", author: "mwatson", models: ["anthropic", "deepmind"], benchmark: "GPQA Diamond", score: 54.1, baseline: 34.2, submittedAt: "Jun 26", kind: "ensemble" },
  { id: "private", recipe: "private-data-bridge-v1", author: "siddhant_r", models: ["anthropic", "deepmind", "openai"], benchmark: "GPQA Diamond", score: 52.7, baseline: 27.1, submittedAt: "Jun 25", kind: "ensemble", hasPrivateData: true },
  { id: "heavy", recipe: "5-model-heavy", author: "fusion_hunter", models: ["anthropic", "deepmind", "openai", "ollama", "mistral"], benchmark: "GPQA Diamond", score: 51.9, baseline: 29.8, submittedAt: "Jun 24", kind: "ensemble" },
  { id: "opus", recipe: "opus-gemini-v3", author: "elena_k", models: ["anthropic", "deepmind"], benchmark: "GPQA Diamond", score: 49.2, baseline: 34.2, submittedAt: "Jun 23", kind: "ensemble" },
  { id: "llama", recipe: "llama-boost-v2", author: "tauquir_m", models: ["ollama", "openai"], benchmark: "GPQA Diamond", score: 44, baseline: 22.1, submittedAt: "Jun 22", kind: "ensemble" },
  { id: "mmlu", recipe: "mmlu-powerhouse", author: "sameer_k", models: ["anthropic", "deepmind", "openai"], benchmark: "MMLU Pro", score: 86.9, baseline: 84.1, submittedAt: "Jun 26", kind: "ensemble" },
  { id: "code", recipe: "code-triad", author: "dmitry_b", models: ["anthropic", "openai", "deepmind"], benchmark: "HumanEval+", score: 94.2, baseline: 90.6, submittedAt: "Jun 25", kind: "ensemble" },
  { id: "opus-gpqa", recipe: "Claude Opus 4.8", author: "Anthropic", models: ["anthropic"], benchmark: "GPQA Diamond", score: 38.4, baseline: 38.4, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "gpt-gpqa", recipe: "GPT-5", author: "OpenAI", models: ["openai"], benchmark: "GPQA Diamond", score: 37.2, baseline: 37.2, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "o3-gpqa", recipe: "o3", author: "OpenAI", models: ["openai"], benchmark: "GPQA Diamond", score: 36.8, baseline: 36.8, submittedAt: "official", kind: "single", source: "Artificial Analysis" },
  { id: "gemini-gpqa", recipe: "Gemini 2.5 Pro", author: "Google", models: ["deepmind"], benchmark: "GPQA Diamond", score: 35.6, baseline: 35.6, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "kimi-gpqa", recipe: "Kimi 2.7", author: "Moonshot AI", models: ["moonshot"], benchmark: "GPQA Diamond", score: 36.2, baseline: 36.2, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "grok-gpqa", recipe: "Grok 4", author: "xAI", models: ["xai"], benchmark: "GPQA Diamond", score: 33.8, baseline: 33.8, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "deepseek-gpqa", recipe: "DeepSeek-R1", author: "DeepSeek", models: ["openrouter"], benchmark: "GPQA Diamond", score: 30.1, baseline: 30.1, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "maverick-gpqa", recipe: "Llama 4 Maverick", author: "Meta", models: ["meta"], benchmark: "GPQA Diamond", score: 27.4, baseline: 27.4, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "opus-mmlu", recipe: "Claude Opus 4.8", author: "Anthropic", models: ["anthropic"], benchmark: "MMLU Pro", score: 84.1, baseline: 84.1, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "gpt-mmlu", recipe: "GPT-5", author: "OpenAI", models: ["openai"], benchmark: "MMLU Pro", score: 83.5, baseline: 83.5, submittedAt: "official", kind: "single", source: "Artificial Analysis" },
  { id: "gemini-mmlu", recipe: "Gemini 2.5 Pro", author: "Google", models: ["deepmind"], benchmark: "MMLU Pro", score: 82.7, baseline: 82.7, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "opus-heval", recipe: "Claude Opus 4.8", author: "Anthropic", models: ["anthropic"], benchmark: "HumanEval+", score: 90.6, baseline: 90.6, submittedAt: "official", kind: "single", source: "LMArena" },
  { id: "gpt-heval", recipe: "GPT-5", author: "OpenAI", models: ["openai"], benchmark: "HumanEval+", score: 89.1, baseline: 89.1, submittedAt: "official", kind: "single", source: "Artificial Analysis" },
  { id: "gemini-heval", recipe: "Gemini 2.5 Pro", author: "Google", models: ["deepmind"], benchmark: "HumanEval+", score: 88.3, baseline: 88.3, submittedAt: "official", kind: "single", source: "LMArena" },
];

const representativeModelIds: Record<string, string> = {
  anthropic: "an-1",
  deepmind: "dm-1",
  openai: "oa-1",
  ollama: "ol-1",
  mistral: "hf-1",
  openrouter: "or-6",
};

function recipeFor(entry: LeaderboardEntry) {
  const ids =
    entry.modelIds ??
    entry.models
      .map((provider) => representativeModelIds[provider])
      .filter(Boolean);
  const name = `${entry.recipe}-remix`.replace(/\s+/g, "-").toLowerCase();
  return `url4://${name}?models=${ids.join("+")}&reduce=majority_vote&loop=parallel`;
}

function ProviderDots({ providers }: { providers: string[] }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="flex -space-x-0.5" aria-hidden="true">
        {providers.map((provider, index) => (
          <span
            key={`${provider}-${index}`}
            className="size-2.5 rounded-full border border-background"
            style={{
              background: providerPresentation(provider).color,
            }}
          />
        ))}
      </span>
      <span className="text-xs text-muted-foreground">{providers.length}</span>
    </span>
  );
}

export default function LeaderboardPage() {
  const ensembles = useEnsembleStore((state) => state.ensembles);
  const [benchmark, setBenchmark] = useState("GPQA Diamond");
  const [filter, setFilter] = useState<"all" | "mine">("all");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const publishedEntries = useMemo<LeaderboardEntry[]>(
    () =>
      ensembles.flatMap((ensemble) =>
        (ensemble.runHistory ?? [])
          .filter((run) => run.published)
          .map((run) => ({
            id: `own-${run.id}`,
            recipe: ensemble.name,
            author: "You",
            models: ensemble.slots.map((slot) => slot.model.providerId),
            modelIds: ensemble.slots.map((slot) => slot.model.id),
            benchmark: run.benchmarkName,
            score: run.score,
            baseline: run.baseline,
            submittedAt: "just now",
            kind: "ensemble",
            isOwn: true,
          })),
      ),
    [ensembles],
  );
  const entries = [...publishedEntries, ...seedEntries];
  const benchmarks = Array.from(
    new Set(entries.map((entry) => entry.benchmark)),
  );
  const filtered = entries
    .filter((entry) => entry.benchmark === benchmark)
    .filter((entry) => filter === "all" || entry.isOwn)
    .sort((a, b) => b.score - a.score);

  async function copyRecipe(entry: LeaderboardEntry) {
    await navigator.clipboard.writeText(recipeFor(entry));
    setCopiedId(entry.id);
    window.setTimeout(
      () => setCopiedId((current) => (current === entry.id ? null : current)),
      1600,
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b px-5 py-5 sm:px-8">
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-semibold">Leaderboard</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Fusions ranked against published single-model results from public
            leaderboards.
          </p>
        </div>
        <a
          href="https://screamingface.ai/leaderboard"
          target="_blank"
          rel="noreferrer"
          className="hidden items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground sm:flex"
        >
          <Globe className="size-3.5" />
          <span className="font-mono">screamingface.ai/leaderboard</span>
          <ExternalLink className="size-3" />
        </a>
      </header>

      <div className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 border-b px-5 sm:px-8">
        <Tabs value={benchmark} onValueChange={setBenchmark}>
          <TabsList className="min-w-0 flex-wrap gap-0">
            {benchmarks.map((item) => (
              <TabsTrigger
                key={item}
                value={item}
                className="-mb-px shrink-0 py-3 font-mono"
              >
                {item}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <Tabs
          value={filter}
          onValueChange={(value) => setFilter(value as "all" | "mine")}
          className="shrink-0"
        >
          <TabsList className="gap-0 rounded-lg bg-muted/60 p-0.5">
            <TabsTrigger
              value="all"
              className="h-7 rounded-md border-0 px-3 py-1.5 data-[state=active]:border-transparent data-[state=active]:bg-card data-[state=active]:shadow-sm"
            >
              All systems
            </TabsTrigger>
            <TabsTrigger
              value="mine"
              className="h-7 rounded-md border-0 px-3 py-1.5 data-[state=active]:border-transparent data-[state=active]:bg-card data-[state=active]:shadow-sm"
            >
              Your fusions
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <main className="min-h-0 flex-1 overflow-auto">
        {filtered.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
            <Trophy className="size-7 opacity-20" />
            <p className="text-sm opacity-60">
              No published runs for this benchmark yet.
            </p>
          </div>
        ) : (
          <table className="w-full min-w-4xl">
            <thead className="sticky top-0 z-10 border-b bg-background">
              <tr className="text-xs text-muted-foreground">
                <th className="w-12 px-6 py-4 text-left font-normal">#</th>
                <th className="px-6 py-4 text-left font-normal">Recipe</th>
                <th className="px-6 py-4 text-left font-normal">Models</th>
                <th className="px-6 py-4 text-right font-normal">Score</th>
                <th className="px-6 py-4 text-right font-normal">Gain</th>
                <th className="w-44 px-6 py-4" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((entry, index) => {
                const rank = index + 1;
                const delta = entry.score - entry.baseline;
                const single = entry.kind === "single";
                const recipe = recipeFor(entry);
                return (
                  <tr
                    key={entry.id}
                    className={cn(
                      "border-b transition-colors hover:bg-muted/20",
                      entry.isOwn && "bg-primary/5",
                      single && "bg-muted/20",
                    )}
                  >
                    <td className="px-6 py-4">
                      <span
                        className={cn(
                          "font-mono text-sm tabular-nums",
                          rank === 1
                            ? "text-primary"
                            : rank <= 3
                              ? "text-foreground/60"
                              : "text-muted-foreground",
                        )}
                      >
                        {rank}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={cn(
                            "font-mono text-sm",
                            single ? "text-muted-foreground" : "text-foreground",
                          )}
                        >
                          {entry.recipe}
                        </span>
                        {entry.isOwn && (
                          <Badge className="bg-primary/20 text-primary">you</Badge>
                        )}
                        {entry.hasPrivateData && (
                          <Badge variant="secondary" className="text-muted-foreground">
                            <Lock className="size-2.5" />
                            private
                          </Badge>
                        )}
                        {single && (
                          <Badge variant="secondary" className="font-mono text-muted-foreground">
                            <Globe className="size-2.5" />
                            imported · {entry.source}
                          </Badge>
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {entry.author}
                        {!single && ` · ${entry.submittedAt}`}
                      </p>
                    </td>
                    <td className="px-6 py-4">
                      <ProviderDots providers={entry.models} />
                    </td>
                    <td className="px-6 py-4 text-right font-mono text-sm font-semibold tabular-nums">
                      {entry.score.toFixed(1)}%
                    </td>
                    <td className="px-6 py-4 text-right">
                      {single ? (
                        <span className="font-mono text-xs text-muted-foreground/60">
                          baseline
                        </span>
                      ) : (
                        <span className="font-mono text-xs tabular-nums text-accent">
                          {delta > 0 ? "+" : ""}
                          {delta.toFixed(1)}pts
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      {!single && (
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-8 rounded-lg text-xs"
                            title="Copy url4 recipe"
                            onClick={() => void copyRecipe(entry)}
                          >
                            {copiedId === entry.id ? (
                              <Check className="size-3.5 text-accent" />
                            ) : (
                              <Copy className="size-3.5" />
                            )}
                            {copiedId === entry.id ? "Copied" : "url4"}
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-8 rounded-lg text-xs"
                            asChild
                          >
                            <Link
                              href={`/ensembles/new/?recipe=${encodeURIComponent(recipe)}`}
                              prefetch={false}
                            >
                              <GitFork className="size-3.5" />
                              Remix
                            </Link>
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </main>
    </div>
  );
}
