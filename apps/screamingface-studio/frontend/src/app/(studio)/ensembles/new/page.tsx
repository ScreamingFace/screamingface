"use client";

import {
  ArrowRight,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Cpu,
  BarChart3,
  Globe,
  History,
  LoaderCircle,
  Pencil,
  Play,
  Plug,
  Plus,
  Scale,
  Share2,
  Upload,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  type ModelParam,
  type SavedEnsemble,
  type SavedModel,
  type SavedRun,
  type SavedRunModelResult,
  useEnsembleStore,
} from "@/lib/ensemble-store";
import {
  ALL_MODELS,
  PROVIDER_COLORS,
  type ModelProvider,
  useModelStore,
} from "@/lib/model-store";
import { useOpenMinedStore } from "@/lib/openmined-store";
import {
  type FusionNode,
  type PipelineNode,
  type RecipeKind,
  type RecipeNode,
  type SoloNode,
  collectSolos,
  convertKind,
  createFusion,
  createSolo,
  describeRecipe,
  fusionFromSlots,
  memberSolos,
  recipeToUrl4,
  rootSynthesizerSolo,
} from "@/lib/recipe";
import { cn } from "@/lib/utils";
import { createUuid } from "@/lib/uuid";

type Model = SavedModel;

type Slot = {
  id: string;
  model: Model;
  systemPrompt: string;
  weight: number;
  params?: ModelParam[];
};

const PARAM_CATALOG: {
  key: string;
  label: string;
  kind: "number" | "int" | "text" | "select";
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
  placeholder?: string;
}[] = [
  { key: "temperature", label: "temperature", kind: "number", min: 0, max: 2, step: 0.1 },
  { key: "top_p", label: "top_p", kind: "number", min: 0, max: 1, step: 0.05 },
  { key: "top_k", label: "top_k", kind: "int" },
  { key: "max_output_tokens", label: "max_output_tokens", kind: "int" },
  { key: "frequency_penalty", label: "frequency_penalty", kind: "number", min: -2, max: 2, step: 0.1 },
  { key: "presence_penalty", label: "presence_penalty", kind: "number", min: -2, max: 2, step: 0.1 },
  { key: "reasoning_effort", label: "reasoning_effort", kind: "select", options: ["low", "medium", "high"] },
  { key: "seed", label: "seed", kind: "int" },
  { key: "stop", label: "stop", kind: "text", placeholder: "e.g. \\n\\n" },
];

function defaultParamValue(
  entry: (typeof PARAM_CATALOG)[number],
): string {
  if (entry.kind === "select") return entry.options?.[0] ?? "";
  if (entry.kind === "text") return "";
  return String(entry.min ?? 0);
}

const benchmarks = [
  {
    id: "gpqa",
    name: "GPQA Diamond",
    domain: "Science",
    questions: 448,
  },
  {
    id: "mmlu",
    name: "MMLU Pro",
    domain: "Multi-domain",
    questions: 12000,
  },
  {
    id: "heval",
    name: "HumanEval+",
    domain: "Coding",
    questions: 164,
  },
  {
    id: "arc",
    name: "ARC-Challenge",
    domain: "Reasoning",
    questions: 1172,
  },
  {
    id: "math",
    name: "MATH-500",
    domain: "Math",
    questions: 500,
  },
];

function ProviderDot({ provider }: { provider: string }) {
  return (
    <span
      className="inline-block size-2 shrink-0 rounded-full"
      style={{ background: PROVIDER_COLORS[provider] ?? "var(--primary)" }}
    />
  );
}

function StageSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string; description: string }[];
  onChange: (value: string) => void;
}) {
  const selected = options.find((option) => option.value === value)!;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="rounded-lg bg-card">
          {selected.label}
          <ChevronDown className="size-3.5 text-muted-foreground" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60 overflow-hidden p-0">
        <DropdownMenuRadioGroup value={value} onValueChange={onChange}>
          {options.map((option) => (
            <DropdownMenuRadioItem
              key={option.value}
              value={option.value}
              className="rounded-none py-2.5 pl-3 pr-8"
            >
              <span className="min-w-0">
                <span className="block text-xs font-medium">{option.label}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {option.description}
                </span>
              </span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function InlineModelPicker({
  providers,
  onAdd,
  label = "Add model",
}: {
  providers: ModelProvider[];
  onAdd: (model: Model) => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const connected = providers.filter(
    (provider) => provider.connected && provider.models.length > 0,
  );
  const needle = query.trim().toLowerCase();

  return (
    <div className="flex flex-col gap-2">
      <Button
        variant="outline"
        size="sm"
        className="w-fit rounded-lg"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Plus className="size-3.5" />
        {label}
      </Button>
      {open && (
        <div className="rounded-xl border bg-card p-2">
          {connected.length === 0 ? (
            <div className="flex flex-col items-start gap-2 p-2">
              <p className="text-xs text-muted-foreground">
                No connected providers yet — connect one to pick its models.
              </p>
              <Button variant="outline" size="sm" className="rounded-lg" asChild>
                <Link href="/models/" prefetch={false}>
                  <Plug className="size-3.5" />
                  Connect a provider
                </Link>
              </Button>
            </div>
          ) : (
            <>
              <Input
                autoFocus
                value={query}
                placeholder="Search models…"
                className="mb-2 h-8"
                onChange={(event) => setQuery(event.target.value)}
              />
              <div className="flex max-h-64 flex-col gap-2 overflow-y-auto">
                {connected.map((provider) => {
                  const models = provider.models.filter((model) =>
                    model.name.toLowerCase().includes(needle),
                  );
                  if (models.length === 0) return null;
                  return (
                    <div key={provider.id}>
                      <p className="px-2 py-1 font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
                        {provider.name}
                      </p>
                      {models.map((model) => (
                        <button
                          type="button"
                          key={model.id}
                          onClick={() => {
                            onAdd(model);
                            setOpen(false);
                            setQuery("");
                          }}
                          className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs transition-colors hover:bg-muted/50"
                        >
                          <ProviderDot provider={model.providerId} />
                          <span className="min-w-0 flex-1 truncate">
                            {model.name}
                          </span>
                          <Plus className="size-3.5 shrink-0 text-muted-foreground" />
                        </button>
                      ))}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ParamEditor({
  params,
  onChange,
}: {
  params: ModelParam[];
  onChange: (next: ModelParam[]) => void;
}) {
  const present = new Set(params.map((param) => param.key));
  const available = PARAM_CATALOG.filter((entry) => !present.has(entry.key));

  const setValue = (key: string, value: string) =>
    onChange(
      params.map((param) =>
        param.key === key ? { ...param, value } : param,
      ),
    );
  const removeParam = (key: string) =>
    onChange(params.filter((param) => param.key !== key));
  const addParam = (key: string) => {
    const entry = PARAM_CATALOG.find((item) => item.key === key);
    if (!entry) return;
    onChange([...params, { key: entry.key, value: defaultParamValue(entry) }]);
  };

  return (
    <div className="mt-3 flex flex-col gap-2">
      {params.map((param) => {
        const entry = PARAM_CATALOG.find((item) => item.key === param.key);
        return (
          <div
            key={param.key}
            className="flex items-center gap-2 border-t border-border/40 pt-2 first:border-t-0 first:pt-0"
          >
            <span className="w-36 shrink-0 truncate font-mono text-xs text-muted-foreground">
              {entry?.label ?? param.key}
            </span>
            {entry?.kind === "select" ? (
              <div className="min-w-0 flex-1">
                <StageSelect
                  value={param.value}
                  options={(entry.options ?? []).map((option) => ({
                    value: option,
                    label: option,
                    description: "",
                  }))}
                  onChange={(value) => setValue(param.key, value)}
                />
              </div>
            ) : (
              <Input
                type={
                  entry?.kind === "number" || entry?.kind === "int"
                    ? "number"
                    : "text"
                }
                inputMode={entry?.kind === "int" ? "numeric" : undefined}
                min={entry?.min}
                max={entry?.max}
                step={
                  entry?.kind === "int" ? 1 : entry?.step
                }
                placeholder={entry?.placeholder}
                value={param.value}
                className="h-8 min-w-0 flex-1 font-mono text-xs"
                onChange={(event) => setValue(param.key, event.target.value)}
              />
            )}
            <Button
              variant="ghost"
              size="icon"
              className="size-7 shrink-0 text-muted-foreground"
              aria-label={`Remove ${entry?.label ?? param.key}`}
              onClick={() => removeParam(param.key)}
            >
              <X className="size-3.5" />
            </Button>
          </div>
        );
      })}
      {available.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="w-fit rounded-lg bg-card"
            >
              <Plus className="size-3.5" />
              Add parameter
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-60 overflow-hidden p-0">
            <DropdownMenuRadioGroup value="" onValueChange={addParam}>
              {available.map((entry) => (
                <DropdownMenuRadioItem
                  key={entry.key}
                  value={entry.key}
                  className="rounded-none py-2 pl-3 pr-8 font-mono text-xs"
                >
                  {entry.label}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

function parseRecipe(raw: string) {
  const match = raw.match(/^url4:\/\/([^?]+)\?(.*)$/);
  if (!match) return null;
  const params = new URLSearchParams(match[2]);
  const slots = (params.get("models") ?? "")
    .split(/[+\s]+/)
    .map((id) => ALL_MODELS.find((model) => model.id === id))
    .filter((model): model is Model => Boolean(model))
    .map((model) => ({
      id: createUuid(),
      model,
      systemPrompt: "",
      weight: 0.5,
    }));
  return {
    name: decodeURIComponent(match[1]).replace(/\s+/g, "-").toLowerCase(),
    slots,
  };
}

function scoreForModel(modelId: string) {
  const seed = [...modelId].reduce(
    (total, character) => total + character.charCodeAt(0),
    0,
  );
  return 45 + (seed % 24);
}

type QuestionItem =
  | { kind: "mcq"; question: string; options: string[]; answer: number }
  | {
      kind: "free";
      question: string;
      answer: string;
      distractors: string[];
    };

const questionBank: QuestionItem[] = [
  {
    kind: "mcq",
    question:
      "A gas occupies 2.0 L at 300 K. At constant pressure, what is its volume at 450 K?",
    options: ["1.3 L", "3.0 L", "4.5 L", "2.0 L"],
    answer: 1,
  },
  {
    kind: "free",
    question:
      "Name the enzyme that unwinds the DNA double helix during replication.",
    answer: "Helicase",
    distractors: ["Ligase", "Primase", "Topoisomerase"],
  },
  {
    kind: "mcq",
    question: "What is the time complexity of binary search on a sorted array?",
    options: ["O(n)", "O(log n)", "O(n log n)", "O(1)"],
    answer: 1,
  },
  {
    kind: "free",
    question: "What is the capital of Australia?",
    answer: "Canberra",
    distractors: ["Sydney", "Melbourne", "Perth"],
  },
  {
    kind: "mcq",
    question: "Which particle mediates the electromagnetic force?",
    options: ["Gluon", "Photon", "W boson", "Graviton"],
    answer: 1,
  },
  {
    kind: "free",
    question:
      "In one word, name the process by which plants convert light to chemical energy.",
    answer: "Photosynthesis",
    distractors: ["Respiration", "Transpiration", "Fermentation"],
  },
  {
    kind: "mcq",
    question: "Evaluate ∫ 2x dx.",
    options: ["x² + C", "2 + C", "x + C", "2x² + C"],
    answer: 0,
  },
  {
    kind: "free",
    question: "What does len('hello') return in Python?",
    answer: "5",
    distractors: ["4", "6", "'hello'"],
  },
];

const answerLetters = ["A", "B", "C", "D"];
const reasoningTraces = [
  "I started from the governing principle, applied it to the values given, and checked the result against the boundary conditions.",
  "I eliminated the choices that violate the underlying constraint, then verified the remaining candidate directly.",
  "The standard result applies here. I used it and checked the units and limiting case before selecting an answer.",
  "I compared the mechanism behind each option instead of matching surface wording, which rules out the distractors.",
];
const synthesisTraces = [
  "The candidate answers mostly converge, and the judge selected the response with the strongest supporting argument.",
  "The judge compared each model's reasoning, discounted unsupported claims, and selected the best-supported result.",
  "After reconciling the disagreement between candidates, one answer remains consistent with the shared evidence.",
];

function stableFraction(value: string) {
  let hash = 2166136261;
  for (const character of value) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 100000) / 100000;
}

type InspectedAnswer = {
  short: string;
  reasoning: string;
};

type InspectedQuestion = {
  index: number;
  question: string;
  options?: string[];
  correctIndex?: number;
  correctText: string;
  correct: boolean;
  reduced: InspectedAnswer;
  models: {
    name: string;
    correct: boolean;
    answer: InspectedAnswer;
  }[];
};

function inspectedQuestions(run: SavedRun, count: number) {
  const visibleCount = Math.min(Math.max(1, count), run.sampleSize);
  return Array.from({ length: visibleCount }, (_, index) => {
    const item = questionBank[index % questionBank.length];
    const isMultipleChoice = item.kind === "mcq";
    const correctIndex = isMultipleChoice ? item.answer : -1;
    const label = (optionIndex: number) =>
      isMultipleChoice
        ? `${answerLetters[optionIndex]}. ${item.options[optionIndex]}`
        : "";
    const correctText = isMultipleChoice ? label(correctIndex) : item.answer;
    const wrongIndexes = [0, 1, 2, 3].filter(
      (optionIndex) => optionIndex !== correctIndex,
    );
    const reducedHit =
      stableFraction(`${run.id}:q${index}:reduce`) < run.score / 100;
    const chooseAnswer = (seed: string, hit: boolean) => {
      if (hit) return correctText;
      if (isMultipleChoice) {
        const wrongIndex =
          wrongIndexes[
            Math.floor(stableFraction(seed) * wrongIndexes.length)
          ];
        return label(wrongIndex);
      }
      return item.distractors[
        Math.floor(stableFraction(seed) * item.distractors.length)
      ];
    };
    const models = run.modelResults.map((result) => {
      const seedId = result.slotId ?? result.modelId;
      const hit =
        stableFraction(`${run.id}:q${index}:m${seedId}`) <
        result.score / 100;
      return {
        name: result.modelName,
        correct: hit,
        answer: {
          short: chooseAnswer(
            `${run.id}:q${index}:w${seedId}`,
            hit,
          ),
          reasoning:
            reasoningTraces[
              Math.floor(
                stableFraction(`${run.id}:q${index}:t${seedId}`) *
                  reasoningTraces.length,
              )
            ],
        },
      };
    });
    return {
      index,
      question: item.question,
      options: isMultipleChoice ? item.options : undefined,
      correctIndex: isMultipleChoice ? correctIndex : undefined,
      correctText,
      correct: reducedHit,
      models,
      reduced: {
        short: chooseAnswer(`${run.id}:q${index}:reduce-wrong`, reducedHit),
        reasoning:
          synthesisTraces[
            Math.floor(
              stableFraction(`${run.id}:q${index}:reduce-trace`) *
                synthesisTraces.length,
            )
          ],
      },
    } satisfies InspectedQuestion;
  });
}

function AnswerTrace({
  answer,
  accent,
}: {
  answer: InspectedAnswer;
  accent: boolean;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground/60">
          Reasoning trace
        </p>
        <p className="border-l-2 border-border/60 pl-3 text-xs italic leading-relaxed text-muted-foreground">
          {answer.reasoning}
        </p>
      </div>
      <div
        className={cn(
          "rounded-lg border px-3 py-2",
          accent ? "border-accent/25 bg-accent/10" : "bg-muted/40",
        )}
      >
        <p
          className={cn(
            "mb-0.5 text-xs uppercase tracking-wide",
            accent ? "text-accent" : "text-muted-foreground",
          )}
        >
          Answer
        </p>
        <p className="text-sm font-medium">{answer.short}</p>
      </div>
    </div>
  );
}

const publicRankingSeeds = [
  { recipe: "private-data-bridge-v1", author: "siddhant_r", score: 72.6 },
  { recipe: "5-model-heavy", author: "fusion_hunter", score: 69.1 },
  { recipe: "llama-boost-v2", author: "tauquir_m", score: 65.4 },
  { recipe: "claude-gemini-fusion", author: "mwatson", score: 62.8 },
];

function RunDetail({
  run,
  ensembleName,
  onBack,
  onNewRun,
  onPublish,
}: {
  run: SavedRun;
  ensembleName: string;
  onBack: () => void;
  onNewRun: () => void;
  onPublish: (run: SavedRun) => void;
}) {
  const ensembles = useEnsembleStore((state) => state.ensembles);
  const [ranking, setRanking] = useState<"local" | "public">("local");
  const [visibleQuestions, setVisibleQuestions] = useState(5);
  const [selectedQuestion, setSelectedQuestion] = useState(0);
  const [participant, setParticipant] = useState<"reduce" | number>("reduce");
  const questions = inspectedQuestions(run, visibleQuestions);
  const question =
    questions.find((item) => item.index === selectedQuestion) ?? questions[0];
  const localEntries = ensembles
    .flatMap((ensemble) =>
      (ensemble.runHistory ?? [])
        .filter((item) => item.benchmarkId === run.benchmarkId)
        .map((item) => ({
          id: item.id,
          recipe: ensemble.name,
          score: item.score,
          baseline: item.baseline,
          createdAt: item.createdAt,
          sample: item.full ? "Full" : `${item.sampleSize}q`,
          current: item.id === run.id,
        })),
    )
    .sort((a, b) => b.score - a.score);
  const publicEntries = [
    {
      id: run.id,
      recipe: ensembleName,
      author: "You",
      score: run.score,
      current: true,
      sample: run.full ? "Full" : `${run.sampleSize}q`,
    },
    ...publicRankingSeeds.map((entry) => ({
      id: `${entry.recipe}-${run.benchmarkId}`,
      ...entry,
      current: false,
      sample: "Full",
    })),
  ].sort((a, b) => b.score - a.score);
  const publicRank =
    publicEntries.findIndex((entry) => entry.current) + 1;
  const activeAnswer =
    participant === "reduce"
      ? question.reduced
      : question.models[participant]?.answer ?? question.reduced;

  return (
    <div className="h-full overflow-y-auto px-5 py-6 sm:px-8">
      <div className="mx-auto max-w-4xl">
        <Button
          variant="ghost"
          size="sm"
          className="mb-6 -ml-3 text-muted-foreground"
          onClick={onBack}
        >
          <ChevronLeft className="size-3.5" />
          Run history
        </Button>

        <section className="mb-14 max-w-3xl">
          <div className="mb-4">
            <p className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
              Scoreboard
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              How this run ranks
            </p>
          </div>
          <div className="mb-3 flex items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-xs text-muted-foreground">
                Ranking on {run.benchmarkName}
              </p>
              {ranking === "public" && (
                <Badge className="bg-primary/10 font-mono text-primary">
                  you rank #{publicRank} of {publicEntries.length}
                </Badge>
              )}
            </div>
            <Tabs
              value={ranking}
              onValueChange={(value) =>
                setRanking(value as "local" | "public")
              }
            >
              <TabsList className="gap-0 rounded-lg bg-muted/60 p-0.5">
                <TabsTrigger
                  value="local"
                  className="inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-md border-0 px-3 py-1.5 data-[state=active]:border-transparent data-[state=active]:bg-card data-[state=active]:shadow-sm"
                >
                  My Runs
                </TabsTrigger>
                <TabsTrigger
                  value="public"
                  className="inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-md border-0 px-3 py-1.5 data-[state=active]:border-transparent data-[state=active]:bg-card data-[state=active]:shadow-sm"
                >
                  <Globe className="size-3" />
                  Public
                </TabsTrigger>
              </TabsList>
            </Tabs>
          </div>
          {ranking === "public" && (
            <p className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Globe className="size-3" />
              Pulled live from
              <span className="font-mono">screamingface.ai/leaderboard</span>
            </p>
          )}
          <div className="overflow-hidden rounded-xl border">
            <table className="w-full">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="w-12 px-5 py-3 text-left font-normal">#</th>
                  <th className="px-5 py-3 text-left font-normal">Recipe</th>
                  <th className="px-5 py-3 text-right font-normal">Score</th>
                  <th className="px-5 py-3 text-right font-normal">Gain</th>
                </tr>
              </thead>
              <tbody>
                {ranking === "local"
                  ? localEntries.map((entry, index) => (
                      <tr
                        key={entry.id}
                        className={cn(
                          "border-b last:border-0",
                          entry.current && "bg-primary/5",
                        )}
                      >
                        <td className="px-5 py-3.5 font-mono text-sm text-muted-foreground">
                          {index + 1}
                        </td>
                        <td className="px-5 py-3.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-sm">
                              {entry.recipe}
                            </span>
                            {entry.current && (
                              <Badge className="bg-primary/20 text-primary">
                                this run
                              </Badge>
                            )}
                          </div>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {new Date(entry.createdAt).toLocaleString()} · {entry.sample}
                          </p>
                        </td>
                        <td className="px-5 py-3.5 text-right font-mono text-sm font-semibold">
                          {entry.score.toFixed(1)}%
                        </td>
                        <td className="px-5 py-3.5 text-right font-mono text-xs text-accent">
                          +{(entry.score - entry.baseline).toFixed(1)}
                        </td>
                      </tr>
                    ))
                  : publicEntries.map((entry, index) => (
                      <tr
                        key={entry.id}
                        className={cn(
                          "border-b last:border-0",
                          entry.current &&
                            "bg-primary/10 outline outline-1 -outline-offset-1 outline-primary/30",
                        )}
                      >
                        <td className="px-5 py-3.5 font-mono text-sm text-muted-foreground">
                          {index + 1}
                        </td>
                        <td className="px-5 py-3.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={cn(
                                "font-mono text-sm",
                                entry.current && "font-semibold text-primary",
                              )}
                            >
                              {entry.recipe}
                            </span>
                            {entry.current && (
                              <Badge className="bg-primary/20 text-primary">
                                your run
                              </Badge>
                            )}
                            <Badge variant="secondary" className="font-mono">
                              {entry.sample}
                            </Badge>
                          </div>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {entry.author} · {entry.current ? (run.published ? "published" : "not published") : "recently"}
                          </p>
                        </td>
                        <td className="px-5 py-3.5 text-right font-mono text-sm font-semibold">
                          {entry.score.toFixed(1)}%
                        </td>
                        <td className="px-5 py-3.5 text-right font-mono text-xs text-muted-foreground">
                          {entry.current
                            ? "—"
                            : run.score > entry.score
                              ? `you +${(run.score - entry.score).toFixed(1)}`
                              : `−${(entry.score - run.score).toFixed(1)}`}
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="mb-14 border-t pt-10">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <p className="font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
                Inspect results
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                Per-question answers and reasoning
              </p>
            </div>
            <p className="shrink-0 text-xs text-muted-foreground">
              {questions.length} of {run.sampleSize.toLocaleString()} loaded
            </p>
          </div>
          <div className="flex h-[30rem] min-h-[60vh] overflow-hidden rounded-xl border">
            <div className="flex w-72 shrink-0 flex-col overflow-y-auto border-r">
              {questions.map((item) => (
                <button
                  type="button"
                  key={item.index}
                  aria-current={item.index === question.index}
                  className={cn(
                    "flex items-center gap-2 border-b px-3 py-2.5 text-left transition-colors",
                    item.index === question.index
                      ? "bg-primary/5"
                      : "hover:bg-muted/20",
                  )}
                  onClick={() => {
                    setSelectedQuestion(item.index);
                    setParticipant("reduce");
                  }}
                >
                  <span className="w-4 shrink-0 font-mono text-xs text-muted-foreground">
                    {item.index + 1}
                  </span>
                  {item.correct ? (
                    <Check className="size-3.5 shrink-0 text-accent" />
                  ) : (
                    <X className="size-3.5 shrink-0 text-destructive" />
                  )}
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                    {item.question}
                  </span>
                </button>
              ))}
              {questions.length < run.sampleSize && (
                <button
                  type="button"
                  className="px-3 py-2.5 text-center text-xs text-muted-foreground transition-colors hover:bg-muted/20 hover:text-foreground"
                  onClick={() => setVisibleQuestions((current) => current + 5)}
                >
                  Load 5 more →
                </button>
              )}
            </div>
            <div className="min-w-0 flex-1 overflow-y-auto p-5">
              <p className="mb-2 text-sm leading-relaxed">
                {question.question}
              </p>
              {question.options ? (
                <div className="mb-4 flex flex-wrap gap-1.5">
                  {question.options.map((option, index) => (
                    <span
                      key={option}
                      className={cn(
                        "rounded border px-2 py-0.5 text-xs",
                        index === question.correctIndex
                          ? "border-accent/40 bg-accent/5"
                          : "border-border/50 text-muted-foreground",
                      )}
                    >
                      {answerLetters[index]}. {option}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="mb-4 text-xs text-muted-foreground">
                  Expected:{" "}
                  <span className="font-medium text-accent">
                    {question.correctText}
                  </span>
                </p>
              )}
              <div className="mb-3 flex flex-wrap gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  aria-pressed={participant === "reduce"}
                  className={cn(
                    "h-7 rounded-lg text-xs",
                    participant === "reduce" &&
                      "border-accent/50 bg-accent/10 text-accent",
                  )}
                  onClick={() => setParticipant("reduce")}
                >
                  <Scale className="size-3" />
                  Fusion
                  {question.correct ? (
                    <Check className="size-3" />
                  ) : (
                    <X className="size-3" />
                  )}
                </Button>
                {question.models.map((model, index) => (
                  <Button
                    key={`${model.name}-${index}`}
                    variant="outline"
                    size="sm"
                    aria-pressed={participant === index}
                    className={cn(
                      "h-7 rounded-lg text-xs",
                      participant === index &&
                        "border-primary/50 bg-primary/5",
                    )}
                    onClick={() => setParticipant(index)}
                  >
                    {model.name}
                  </Button>
                ))}
              </div>
              <AnswerTrace
                answer={activeAnswer}
                accent={participant === "reduce"}
              />
              {participant === "reduce" && !question.correct && (
                <p className="mt-2 text-xs text-destructive">
                  Correct answer: {question.correctText}
                </p>
              )}
            </div>
          </div>
        </section>

        <section className="flex max-w-3xl items-center justify-between gap-4 rounded-2xl border bg-card p-6">
          <div>
            <h2 className="mb-1 text-sm font-medium">
              Publish to Leaderboard
            </h2>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {run.full
                ? "Post this run publicly. Anyone can re-run your url4 to verify it on their own machine."
                : "Only full-benchmark runs can be published. This was a sample run — run the full benchmark to publish a verifiable score."}
            </p>
          </div>
          {run.published ? (
            <Badge className="shrink-0 border border-accent/20 bg-accent/10 px-4 py-2 text-accent">
              <Check className="size-3.5" />
              Published
            </Badge>
          ) : run.full ? (
            <Button className="shrink-0" onClick={() => onPublish(run)}>
              <BarChart3 className="size-3.5" />
              Publish Score
            </Button>
          ) : (
            <Button
              variant="outline"
              className="shrink-0 border-primary/40 text-primary"
              onClick={onNewRun}
            >
              <Play className="size-3.5" />
              Run full benchmark
            </Button>
          )}
        </section>
      </div>
    </div>
  );
}

function RunsPanel({
  slots,
  judge,
  runs,
  onComplete,
  onPublish,
  ensembleName,
  onBackToCompose,
}: {
  slots: Slot[];
  judge: Slot | null;
  runs: SavedRun[];
  onComplete: (run: SavedRun) => void;
  onPublish: (run: SavedRun) => void;
  ensembleName: string;
  onBackToCompose: () => void;
}) {
  const [mode, setMode] = useState<"history" | "new" | "detail">(
    runs.length > 0 ? "history" : "new",
  );
  const [benchmarkId, setBenchmarkId] = useState("gpqa");
  const [sampleSize, setSampleSize] = useState(100);
  const [full, setFull] = useState(false);
  const [custom, setCustom] = useState(false);
  const [useCache, setUseCache] = useState(true);
  const [saveCache, setSaveCache] = useState(true);
  const [compute, setCompute] = useState<"om" | "own">("om");
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [modelResults, setModelResults] = useState<
    (SavedRunModelResult & { status: "pending" | "running" | "done" })[]
  >([]);
  const [judgeStatus, setJudgeStatus] = useState<
    "idle" | "running" | "done"
  >("idle");
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const intervalRef = useRef<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [customBenchmarks, setCustomBenchmarks] = useState<
    typeof benchmarks
  >([]);
  const omConnected = useOpenMinedStore((state) => state.connected);
  const effectiveCompute = omConnected ? compute : "own";
  const allBenchmarks = [...benchmarks, ...customBenchmarks];
  const benchmark =
    allBenchmarks.find((item) => item.id === benchmarkId) ?? benchmarks[0];
  const selectedRun =
    runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;

  useEffect(
    () => () => {
      if (intervalRef.current) window.clearInterval(intervalRef.current);
    },
    [],
  );

  function cancelRun() {
    if (intervalRef.current) window.clearInterval(intervalRef.current);
    intervalRef.current = null;
    setRunning(false);
    setProgress(0);
    setModelResults([]);
    setJudgeStatus("idle");
  }

  function startRun() {
    if (slots.length === 0) return;
    setRunning(true);
    setProgress(0);
    setJudgeStatus("idle");
    setModelResults(
      slots.map((slot) => ({
        slotId: slot.id,
        modelId: slot.model.id,
        modelName: slot.model.name,
        score: 0,
        latencyMs: 0,
        status: "pending",
      })),
    );

    let tick = 0;
    intervalRef.current = window.setInterval(() => {
      tick += 1;
      const nextProgress = Math.min(100, tick * 5);
      setProgress(nextProgress);
      if (judge) {
        if (nextProgress === 100) {
          setJudgeStatus("done");
        } else if (nextProgress >= 85) {
          setJudgeStatus((current) =>
            current === "idle" ? "running" : current,
          );
        }
      }
      setModelResults((current) =>
        current.map((result, index) => {
          const startAt = index * 2;
          if (tick < startAt) return result;
          if (tick < startAt + 10) return { ...result, status: "running" };
          return {
            ...result,
            status: "done",
            score: scoreForModel(result.modelId),
            latencyMs: 1100 + index * 187,
          };
        }),
      );

      if (nextProgress === 100) {
        if (intervalRef.current) window.clearInterval(intervalRef.current);
        intervalRef.current = null;
        const finalResults = slots.map((slot, index) => ({
          slotId: slot.id,
          modelId: slot.model.id,
          modelName: slot.model.name,
          score: scoreForModel(slot.model.id),
          latencyMs: 1100 + index * 187,
        }));
        const baseline = Math.max(
          ...finalResults.map((result) => result.score),
        );
        const score = Math.min(95, baseline + 8 + slots.length * 3);
        const run: SavedRun = {
          id: createUuid(),
          benchmarkId: benchmark.id,
          benchmarkName: benchmark.name,
          sampleSize: full ? benchmark.questions : sampleSize,
          full,
          useCache,
          saveCache,
          compute: effectiveCompute,
          score,
          baseline,
          modelResults: finalResults,
          createdAt: new Date().toISOString(),
          published: false,
        };
        setRunning(false);
        setSelectedRunId(run.id);
        onComplete(run);
        setMode("detail");
      }
    }, 110);
  }

  function uploadDataset(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const rows = String(reader.result ?? "")
        .split(/\r?\n/)
        .filter((row) => row.trim().length > 0);
      const custom = {
        id: `custom-${createUuid()}`,
        name: file.name,
        domain: "Custom",
        questions: Math.max(1, rows.length),
      };
      setCustomBenchmarks((current) => [...current, custom]);
      setBenchmarkId(custom.id);
    };
    reader.readAsText(file);
    event.target.value = "";
  }

  if (mode === "history") {
    return (
      <div className="h-full overflow-y-auto px-5 py-6 sm:px-8">
        <div className="mx-auto max-w-4xl">
          <div className="mb-6 flex items-center justify-between gap-4">
            <div>
              <h2 className="text-sm font-medium">Run history</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Compare this fusion across benchmarks.
              </p>
            </div>
            <Button
              size="sm"
              disabled={slots.length === 0}
              onClick={() => setMode("new")}
            >
              <Play className="size-3.5" />
              New Run
            </Button>
          </div>
          {runs.length === 0 ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed py-20 text-muted-foreground">
              <History className="size-6 opacity-20" />
              <p className="text-sm opacity-50">
                No runs yet — evaluate this fusion against a benchmark.
              </p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border">
              <table className="w-full text-left">
                <thead className="border-b bg-muted/30 font-mono text-xs text-muted-foreground">
                  <tr>
                    <th className="px-5 py-3 font-medium">Benchmark</th>
                    <th className="px-5 py-3 font-medium">Sample</th>
                    <th className="px-5 py-3 text-right font-medium">Score</th>
                    <th className="px-5 py-3 text-right font-medium">Gain</th>
                  </tr>
                </thead>
                <tbody>
                  {[...runs].reverse().map((run) => (
                    <tr
                      key={run.id}
                      className="cursor-pointer border-b transition-colors last:border-0 hover:bg-muted/20"
                      onClick={() => {
                        setSelectedRunId(run.id);
                        setMode("detail");
                      }}
                    >
                      <td className="px-5 py-3.5">
                        <p className="text-sm">{run.benchmarkName}</p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {new Date(run.createdAt).toLocaleString()}
                        </p>
                      </td>
                      <td className="px-5 py-3.5 font-mono text-xs text-muted-foreground">
                        {run.full ? "Full" : `${run.sampleSize}q`}
                      </td>
                      <td className="px-5 py-3.5 text-right font-mono text-sm font-semibold">
                        {run.score.toFixed(1)}%
                      </td>
                      <td className="px-5 py-3.5 text-right font-mono text-xs text-accent">
                        +{(run.score - run.baseline).toFixed(1)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (mode === "detail" && selectedRun) {
    return (
      <RunDetail
        run={selectedRun}
        ensembleName={ensembleName}
        onBack={() => setMode("history")}
        onNewRun={() => {
          setFull(true);
          setMode("new");
        }}
        onPublish={onPublish}
      />
    );
  }

  return (
    <div className="h-full overflow-y-auto px-5 py-6 sm:px-8">
      <div className="mx-auto max-w-3xl">
        <div className="mb-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="sm"
              className="-ml-3 text-muted-foreground"
              onClick={onBackToCompose}
            >
              <ChevronLeft className="size-3.5" />
              Compose
            </Button>
            <h2 className="text-sm font-medium">New Run</h2>
          </div>
          {runs.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="text-muted-foreground"
              onClick={() => setMode("history")}
            >
              <History className="size-3.5" />
              History
            </Button>
          )}
        </div>

        <div className="grid gap-8 md:grid-cols-2">
          <section>
            <p className="mb-3 text-xs text-muted-foreground">Benchmark</p>
            <div className="flex flex-col gap-1.5">
              <RadioGroup
                value={benchmarkId}
                disabled={running}
                onValueChange={setBenchmarkId}
                aria-label="Benchmark"
                className="gap-1.5"
              >
                {allBenchmarks.map((item) => (
                  <label
                    key={item.id}
                    htmlFor={`benchmark-${item.id}`}
                    className={cn(
                      "flex cursor-pointer items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors",
                      running && "cursor-not-allowed opacity-50",
                      benchmarkId === item.id
                        ? "border-primary/50 bg-primary/5"
                        : "hover:bg-muted/20",
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <RadioGroupItem
                        id={`benchmark-${item.id}`}
                        value={item.id}
                      />
                      <span className="truncate text-xs">{item.name}</span>
                      <Badge variant="secondary" className="font-mono text-xs">
                        {item.domain}
                      </Badge>
                    </span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {item.questions.toLocaleString()}q
                    </span>
                  </label>
                ))}
              </RadioGroup>
              <button
                type="button"
                disabled={running}
                className="flex items-center gap-2 rounded-lg border border-dashed px-3 py-2.5 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
                onClick={() => fileRef.current?.click()}
              >
                <Upload className="size-3.5" />
                Upload custom dataset
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".csv,.jsonl,.json,.txt,text/plain"
                className="hidden"
                onChange={uploadDataset}
              />
            </div>
          </section>

          <div className="flex flex-col gap-6">
            <section>
              <p className="mb-3 text-xs text-muted-foreground">Sample Size</p>
              <div className="flex flex-wrap gap-2">
                {[1, 50, 100].map((size) => {
                  const active = !full && !custom && sampleSize === size;
                  return (
                    <Button
                      key={size}
                      type="button"
                      size="sm"
                      aria-pressed={active}
                      variant={active ? "default" : "outline"}
                      disabled={running}
                      className="font-mono"
                      onClick={() => {
                        setSampleSize(size);
                        setFull(false);
                        setCustom(false);
                      }}
                    >
                      {size}q
                    </Button>
                  );
                })}
                <Button
                  type="button"
                  size="sm"
                  aria-pressed={!full && custom}
                  variant={!full && custom ? "default" : "outline"}
                  disabled={running}
                  className="font-mono"
                  onClick={() => {
                    setCustom(true);
                    setFull(false);
                  }}
                >
                  Custom
                </Button>
                <Button
                  type="button"
                  size="sm"
                  aria-pressed={full}
                  variant={full ? "default" : "outline"}
                  disabled={running}
                  className="font-mono"
                  onClick={() => {
                    setFull(true);
                    setCustom(false);
                  }}
                >
                  Full
                </Button>
              </div>
              {!full && custom && (
                <div className="mt-3 flex items-center gap-2">
                  <Input
                    type="number"
                    min={1}
                    inputMode="numeric"
                    value={sampleSize}
                    disabled={running}
                    aria-label="Custom sample size"
                    className="h-8 w-28 font-mono"
                    onChange={(event) => {
                      const next = Number.parseInt(event.target.value, 10);
                      setSampleSize(Number.isNaN(next) ? 1 : Math.max(1, next));
                    }}
                  />
                  <span className="text-xs text-muted-foreground">questions</span>
                </div>
              )}
              {full && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Full benchmark — {benchmark.questions.toLocaleString()} questions.
                </p>
              )}
            </section>
            <section>
              <p className="mb-3 text-xs text-muted-foreground">Compute</p>
              {omConnected ? (
                <RadioGroup
                  value={compute}
                  disabled={running}
                  onValueChange={(value) =>
                    setCompute(value as "om" | "own")
                  }
                  aria-label="Compute"
                >
                  {[
                    {
                      id: "om" as const,
                      label: "OpenMined Compute",
                      description: "Subsidized — drawn from your OpenMined budget",
                    },
                    {
                      id: "own" as const,
                      label: "My Own Compute",
                      description: "Uses your connected provider credentials",
                    },
                  ].map((option) => (
                    <label
                      key={option.id}
                      htmlFor={`compute-${option.id}`}
                      className={cn(
                        "flex cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 text-left transition-colors",
                        running && "cursor-not-allowed opacity-50",
                        compute === option.id
                          ? "border-primary/50 bg-primary/5"
                          : "hover:bg-muted/20",
                      )}
                    >
                      <RadioGroupItem
                        id={`compute-${option.id}`}
                        value={option.id}
                      />
                      <span>
                        <span className="block text-xs font-medium">
                          {option.label}
                        </span>
                        <span className="mt-0.5 block text-xs text-muted-foreground">
                          {option.description}
                        </span>
                      </span>
                    </label>
                  ))}
                </RadioGroup>
              ) : (
                <div className="flex items-start gap-2.5 rounded-xl border bg-muted/20 px-4 py-3">
                  <Cpu className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    Using your own compute and connected provider credentials.
                    Connect an OpenMined key in the sidebar for subsidized compute.
                  </p>
                </div>
              )}
            </section>
            <section>
              <p className="mb-3 text-xs text-muted-foreground">Cache</p>
              <div className="flex flex-col gap-2">
                <label
                  htmlFor="run-use-cache"
                  className={cn(
                    "flex cursor-pointer items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-colors",
                    running && "cursor-not-allowed opacity-50",
                    useCache ? "border-primary/50 bg-primary/5" : "hover:bg-muted/20",
                  )}
                >
                  <span>
                    <span className="block text-xs font-medium">Use cache</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      Reuse cached answers when a matching request already ran.
                    </span>
                  </span>
                  <Switch
                    id="run-use-cache"
                    checked={useCache}
                    disabled={running}
                    onCheckedChange={setUseCache}
                    aria-label="Use cache"
                  />
                </label>
                <label
                  htmlFor="run-save-cache"
                  className={cn(
                    "flex cursor-pointer items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-colors",
                    running && "cursor-not-allowed opacity-50",
                    saveCache ? "border-primary/50 bg-primary/5" : "hover:bg-muted/20",
                  )}
                >
                  <span>
                    <span className="block text-xs font-medium">Save cache</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      Store this run&apos;s answers so future runs can reuse them.
                    </span>
                  </span>
                  <Switch
                    id="run-save-cache"
                    checked={saveCache}
                    disabled={running}
                    onCheckedChange={setSaveCache}
                    aria-label="Save cache"
                  />
                </label>
              </div>
            </section>
          </div>
        </div>

        <div className="mt-8">
          {!running ? (
            <Button
              disabled={slots.length === 0}
              className="rounded-xl"
              onClick={startRun}
            >
              <Play className="size-4" />
              Run Evaluation
            </Button>
          ) : (
            (() => {
              const totalQuestions = full ? benchmark.questions : sampleSize;
              const answeredQuestions = Math.min(
                totalQuestions,
                Math.round((progress / 100) * totalQuestions),
              );
              return (
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-3">
                <LoaderCircle className="size-4 animate-spin text-primary" />
                <p className="min-w-0 flex-1 truncate text-sm">
                  Running {benchmark.name} · {full ? "Full" : `${sampleSize}q`} · {effectiveCompute === "om" ? "OM compute" : "own compute"}
                </p>
                <span className="font-mono text-xs text-muted-foreground">
                  {answeredQuestions.toLocaleString()} / {totalQuestions.toLocaleString()} questions
                </span>
                <span className="font-mono text-xs text-muted-foreground">
                  {progress}%
                </span>
                <Button variant="outline" size="sm" onClick={cancelRun}>
                  <X className="size-3.5" />
                  Cancel
                </Button>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="flex flex-col gap-3">
                <div>
                  <p className="mb-2 font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
                    Members
                  </p>
                  <div className="overflow-hidden rounded-xl border">
                    {modelResults.map((result) => (
                      <div
                        key={result.slotId ?? result.modelId}
                        className="flex items-center justify-between border-b px-5 py-3 last:border-0"
                      >
                        <span className="text-sm">{result.modelName}</span>
                        {result.status === "pending" ? (
                          <span className="text-xs text-muted-foreground">queued</span>
                        ) : result.status === "running" ? (
                          <span className="flex items-center gap-2 text-xs text-primary">
                            <span className="size-1.5 animate-pulse rounded-full bg-primary" />
                            answering…
                          </span>
                        ) : (
                          <span className="flex items-center gap-1.5 text-xs text-accent">
                            <Check className="size-3.5" />
                            answered
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
                {judge && (
                  <div>
                    <p className="mb-2 font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
                      Judge
                    </p>
                    <div className="overflow-hidden rounded-xl border">
                      <div className="flex items-center justify-between border-b px-5 py-3 last:border-0">
                        <span className="flex min-w-0 items-center gap-2">
                          <ProviderDot provider={judge.model.providerId} />
                          <span className="truncate text-sm">
                            {judge.model.name}
                          </span>
                        </span>
                        {judgeStatus === "idle" ? (
                          <span className="text-xs text-muted-foreground">waiting</span>
                        ) : judgeStatus === "running" ? (
                          <span className="flex items-center gap-2 text-xs text-primary">
                            <span className="size-1.5 animate-pulse rounded-full bg-primary" />
                            arbitrating…
                          </span>
                        ) : (
                          <span className="flex items-center gap-1.5 text-xs text-accent">
                            <Check className="size-3.5" />
                            done
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
              );
            })()
          )}
        </div>
      </div>
    </div>
  );
}

function deriveSlots(root: RecipeNode): Slot[] {
  return memberSolos(root)
    .filter((solo) => solo.model)
    .map((solo) => ({
      id: solo.id,
      model: solo.model as Model,
      systemPrompt: solo.prompt,
      weight: 0.5,
      params: solo.params,
    }));
}

function deriveJudge(root: RecipeNode): Slot | null {
  const synth = rootSynthesizerSolo(root);
  return synth
    ? { id: synth.id, model: synth.model as Model, systemPrompt: synth.prompt, weight: 0 }
    : null;
}

function buildDraft(
  id: string,
  name: string,
  root: RecipeNode,
  runHistory: SavedRun[],
): SavedEnsemble {
  const judge = deriveJudge(root);
  return {
    id,
    name,
    root,
    slots: deriveSlots(root),
    strategy: "majority_vote",
    customReduce: false,
    reduceScriptId: null,
    loopMode: "parallel",
    loopScriptId: null,
    judge,
    judgeId: judge?.model.id ?? null,
    runs: runHistory.length,
    runHistory,
    updatedAt: 0,
  };
}

type NodeRole = "root" | "member" | "stage" | "synthesizer";

function kindLabel(kind: RecipeKind): string {
  return kind === "solo" ? "Solo" : kind === "fusion" ? "Fusion" : "Pipeline";
}

// Only leaf model units (and the synthesizer) are drawn as blocks; fusions/pipelines are
// bare structural groupings, so the composition reads like a node diagram.
function soloChrome(): string {
  return "rounded-lg border bg-card p-2.5 shadow-sm";
}

function roleTagClass(): string {
  return "shrink-0 font-mono text-[10px] uppercase tracking-wider text-muted-foreground";
}

function KindDropdown({
  node,
  onChange,
}: {
  node: RecipeNode;
  onChange: (next: RecipeNode) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="inline-flex h-6 shrink-0 items-center gap-0.5 rounded-md border px-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted/40"
        >
          {kindLabel(node.kind)}
          <ChevronDown className="size-3" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-[8rem]">
        <DropdownMenuRadioGroup
          value={node.kind}
          onValueChange={(value) => onChange(convertKind(node, value as RecipeKind))}
        >
          <DropdownMenuRadioItem value="solo">Solo model</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="fusion">Fusion</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="pipeline">Pipeline</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function RemoveButton({ onRemove }: { onRemove: () => void }) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-6 shrink-0 text-muted-foreground"
      aria-label="Remove element"
      onClick={onRemove}
    >
      <X className="size-3.5" />
    </Button>
  );
}

function SoloConfig({
  node,
  onChange,
}: {
  node: SoloNode;
  onChange: (next: RecipeNode) => void;
}) {
  const [showParams, setShowParams] = useState((node.params?.length ?? 0) > 0);
  const paramCount = node.params?.length ?? 0;
  return (
    <div className="flex flex-col gap-2.5">
      <Textarea
        rows={2}
        value={node.prompt}
        placeholder="System prompt (optional) — You are a helpful assistant specializing in…"
        className="resize-none text-xs"
        onChange={(event) => onChange({ ...node, prompt: event.target.value })}
      />
      <div className="flex items-center justify-between gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-muted-foreground"
          aria-expanded={showParams}
          onClick={() => setShowParams((value) => !value)}
        >
          <ChevronRight
            className={cn("size-3.5 transition-transform", showParams && "rotate-90")}
          />
          Parameters{paramCount > 0 ? ` (${paramCount})` : ""}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs text-muted-foreground"
          onClick={() => onChange({ ...node, model: null })}
        >
          Change model
        </Button>
      </div>
      {showParams && (
        <ParamEditor
          params={node.params ?? []}
          onChange={(next) => onChange({ ...node, params: next })}
        />
      )}
    </div>
  );
}

// Fusion: parallel member blocks on a rail, converging into the synthesizer block.
function FusionBody({
  node,
  onChange,
  providers,
  onUseModels,
  depth,
}: {
  node: FusionNode;
  onChange: (next: RecipeNode) => void;
  providers: ModelProvider[];
  onUseModels: (models: Model[]) => void;
  depth: number;
}) {
  const setMembers = (members: RecipeNode[]) => onChange({ ...node, members });
  return (
    <div className="flex flex-row items-center gap-1.5">
      <div className="flex shrink-0 flex-col gap-2 rounded-lg border border-dashed border-border/60 p-2">
        <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
          Parallel members
        </p>
        {node.members.map((member, index) => (
          <RecipeNodeCard
            key={member.id}
            node={member}
            index={index}
            depth={depth + 1}
            role="member"
            providers={providers}
            onUseModels={onUseModels}
            onChange={(next) =>
              setMembers(node.members.map((item, i) => (i === index ? next : item)))
            }
            onRemove={
              node.members.length > 1
                ? () => setMembers(node.members.filter((_, i) => i !== index))
                : undefined
            }
          />
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 self-start text-xs"
          onClick={() => setMembers([...node.members, createSolo()])}
        >
          <Plus className="size-3.5" />
          Add member
        </Button>
      </div>
      <div className="flex shrink-0 flex-col items-center">
        <ArrowRight className="size-4 text-muted-foreground/70" />
        <span className="mt-0.5 text-[9px] font-medium uppercase tracking-wider text-muted-foreground/70">
          synthesize
        </span>
      </div>
      <div className="shrink-0">
        <RecipeNodeCard
          node={node.synthesizer}
          depth={depth + 1}
          role="synthesizer"
          providers={providers}
          onUseModels={onUseModels}
          onChange={(next) => onChange({ ...node, synthesizer: next })}
        />
      </div>
    </div>
  );
}

// Pipeline: stage blocks on a left-to-right timeline.
function PipelineBody({
  node,
  onChange,
  providers,
  onUseModels,
  depth,
}: {
  node: PipelineNode;
  onChange: (next: RecipeNode) => void;
  providers: ModelProvider[];
  onUseModels: (models: Model[]) => void;
  depth: number;
}) {
  const setStages = (stages: RecipeNode[]) => onChange({ ...node, stages });
  return (
    <div className="flex flex-row items-center gap-1.5 pb-1">
      {node.stages.map((stage, index) => (
        <div key={stage.id} className="flex items-start gap-1.5">
          {index > 0 && (
            <ArrowRight className="size-4 shrink-0 text-muted-foreground/70" />
          )}
          <div className="min-w-[16rem] shrink-0">
            <RecipeNodeCard
              node={stage}
              index={index}
              depth={depth + 1}
              role="stage"
              providers={providers}
              onUseModels={onUseModels}
              onChange={(next) =>
                setStages(node.stages.map((item, i) => (i === index ? next : item)))
              }
              onRemove={
                node.stages.length > 1
                  ? () => setStages(node.stages.filter((_, i) => i !== index))
                  : undefined
              }
            />
          </div>
        </div>
      ))}
      <div className="flex items-center gap-1.5 self-center">
        <ArrowRight className="size-4 shrink-0 text-muted-foreground/70" />
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 text-xs"
          onClick={() => setStages([...node.stages, createSolo()])}
        >
          <Plus className="size-3.5" />
          Add stage
        </Button>
      </div>
    </div>
  );
}

function NodeLabel({
  node,
  roleLabel,
  onChange,
}: {
  node: RecipeNode;
  roleLabel: string;
  onChange: (next: RecipeNode) => void;
}) {
  const [editing, setEditing] = useState(false);
  const named = Boolean(node.name && node.name.trim());
  if (editing) {
    return (
      <Input
        autoFocus
        value={node.name ?? ""}
        placeholder={roleLabel}
        aria-label="Rename"
        className="h-6 w-36 px-2 text-xs"
        onClick={(event) => event.stopPropagation()}
        onChange={(event) => onChange({ ...node, name: event.target.value })}
        onBlur={() => setEditing(false)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === "Escape") {
            event.preventDefault();
            event.currentTarget.blur();
          }
        }}
      />
    );
  }
  return (
    <span className="group/label flex min-w-0 items-center gap-1">
      <span
        className={cn(
          "min-w-0 truncate",
          named
            ? "max-w-[11rem] text-xs font-medium text-foreground/90"
            : roleTagClass(),
        )}
      >
        {named ? node.name : roleLabel}
      </span>
      <button
        type="button"
        aria-label="Rename"
        title="Rename"
        onClick={(event) => {
          event.stopPropagation();
          setEditing(true);
        }}
        className="shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover/label:opacity-100"
      >
        <Pencil className="size-3" />
      </button>
    </span>
  );
}

function RecipeNodeCard({
  node,
  onChange,
  providers,
  onUseModels,
  onRemove,
  role = "root",
  index,
  depth = 0,
}: {
  node: RecipeNode;
  onChange: (next: RecipeNode) => void;
  providers: ModelProvider[];
  onUseModels: (models: Model[]) => void;
  onRemove?: () => void;
  role?: NodeRole;
  index?: number;
  depth?: number;
}) {
  const [collapsed, setCollapsed] = useState(
    () => node.kind === "solo" && Boolean((node as SoloNode).model),
  );
  const roleLabel =
    role === "member"
      ? `Member ${(index ?? 0) + 1}`
      : role === "stage"
        ? `Stage ${(index ?? 0) + 1}`
        : role === "synthesizer"
          ? "Synthesizer"
          : "Recipe";
  const controls = (
    <div className="flex shrink-0 items-center gap-1">
      <KindDropdown node={node} onChange={onChange} />
      {onRemove && <RemoveButton onRemove={onRemove} />}
    </div>
  );

  // Solo — a drawn block.
  if (node.kind === "solo") {
    const model = node.model;
    return (
      <article className={cn("min-w-[16rem]", soloChrome())}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            {model ? (
              <button
                type="button"
                aria-label={collapsed ? "Expand" : "Collapse"}
                aria-expanded={!collapsed}
                onClick={() => setCollapsed((value) => !value)}
                className="grid size-5 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
              >
                <ChevronRight
                  className={cn("size-3.5 transition-transform", !collapsed && "rotate-90")}
                />
              </button>
            ) : (
              <span className="grid size-5 shrink-0 place-items-center">
                <span className="size-1.5 rounded-full bg-muted-foreground/40" />
              </span>
            )}
            <NodeLabel node={node} roleLabel={roleLabel} onChange={onChange} />
            {model ? (
              <button
                type="button"
                onClick={() => setCollapsed((value) => !value)}
                className="flex min-w-0 items-center gap-1.5"
              >
                <ProviderDot provider={model.providerId} />
                <span className="truncate font-mono text-xs text-foreground/90">
                  {model.name}
                </span>
              </button>
            ) : (
              <span className="truncate text-xs text-muted-foreground/70">
                · pick a model
              </span>
            )}
          </div>
          {controls}
        </div>
        {!model && (
          <div className="mt-2.5">
            <InlineModelPicker
              providers={providers}
              onAdd={(picked) => {
                onChange({ ...node, model: picked });
                onUseModels([picked]);
                setCollapsed(true);
              }}
            />
          </div>
        )}
        {model && !collapsed && (
          <div className="mt-2.5">
            <SoloConfig node={node} onChange={onChange} />
          </div>
        )}
      </article>
    );
  }

  // Fusion / Pipeline — a bare structural grouping.
  return (
    <div className={cn("flex flex-col gap-2", depth > 0 && "pl-0.5")}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          <button
            type="button"
            aria-label={collapsed ? "Expand" : "Collapse"}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((value) => !value)}
            className="grid size-5 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
          >
            <ChevronRight
              className={cn("size-3.5 transition-transform", !collapsed && "rotate-90")}
            />
          </button>
          <NodeLabel node={node} roleLabel={roleLabel} onChange={onChange} />
          <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            {kindLabel(node.kind)}
          </span>
          {collapsed && (
            <span className="min-w-0 truncate font-mono text-[11px] text-foreground/70">
              {describeRecipe(node)}
            </span>
          )}
        </div>
        {controls}
      </div>
      {!collapsed && (
        <div>
          {node.kind === "fusion" ? (
            <FusionBody
              node={node}
              onChange={onChange}
              providers={providers}
              onUseModels={onUseModels}
              depth={depth}
            />
          ) : (
            <PipelineBody
              node={node}
              onChange={onChange}
              providers={providers}
              onUseModels={onUseModels}
              depth={depth}
            />
          )}
        </div>
      )}
    </div>
  );
}

function EnsembleComposer() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedId = searchParams.get("id");
  const importedRecipe = searchParams.get("recipe");
  const [newEnsembleId] = useState(() =>
    typeof window === "undefined"
      ? "new-ensemble"
      : createUuid(),
  );
  const ensembleId = requestedId ?? newEnsembleId;
  const storeHasHydrated = useEnsembleStore((state) => state.hasHydrated);
  const upsertEnsemble = useEnsembleStore((state) => state.upsertEnsemble);
  const setActiveEnsemble = useEnsembleStore(
    (state) => state.setActiveEnsemble,
  );
  const providers = useModelStore((state) => state.providers);
  const addLibraryModels = useModelStore((state) => state.addLibraryModels);
  const [name, setName] = useState("fusion-1");
  const [editingName, setEditingName] = useState(false);
  const [root, setRoot] = useState<RecipeNode>(() => createFusion());
  const [runHistory, setRunHistory] = useState<SavedRun[]>([]);
  const [tab, setTab] = useState<"compose" | "runs">("compose");
  const [copied, setCopied] = useState(false);
  const [zoom, setZoom] = useState(1);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [autoSave, setAutoSave] = useState(true);
  const [loadedEnsembleId, setLoadedEnsembleId] = useState<string | null>(null);
  const [savedSnapshot, setSavedSnapshot] = useState("");
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    if (!storeHasHydrated) return;
    const storedEnsembles = useEnsembleStore.getState().ensembles;
    const saved = requestedId
      ? storedEnsembles.find((ensemble) => ensemble.id === requestedId) ?? null
      : null;
    const parsed = importedRecipe ? parseRecipe(importedRecipe) : null;
    const frame = window.requestAnimationFrame(() => {
      if (saved) {
        const savedRunHistory = saved.runHistory ?? [];
        const nextRoot =
          saved.root ?? fusionFromSlots(saved.slots, saved.judge ?? null);
        setName(saved.name);
        setRoot(nextRoot);
        addLibraryModels(
          collectSolos(nextRoot)
            .map((solo) => solo.model)
            .filter((model): model is Model => Boolean(model)),
        );
        setRunHistory(savedRunHistory);
        setSavedSnapshot(
          JSON.stringify(buildDraft(ensembleId, saved.name, nextRoot, savedRunHistory)),
        );
      } else if (parsed) {
        const nextRoot = fusionFromSlots(parsed.slots, null);
        setName(parsed.name);
        setRoot(nextRoot);
        addLibraryModels(
          collectSolos(nextRoot)
            .map((solo) => solo.model)
            .filter((model): model is Model => Boolean(model)),
        );
        setRunHistory([]);
        setSavedSnapshot("");
      } else {
        const nextRoot = createFusion();
        setName("fusion-1");
        setRoot(nextRoot);
        setRunHistory([]);
        setSavedSnapshot(
          JSON.stringify(buildDraft(ensembleId, "fusion-1", nextRoot, [])),
        );
      }
      setActiveEnsemble(ensembleId);
      setLoadedEnsembleId(ensembleId);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [
    ensembleId,
    addLibraryModels,
    importedRecipe,
    requestedId,
    setActiveEnsemble,
    storeHasHydrated,
  ]);

  const slots = useMemo(() => deriveSlots(root), [root]);
  const judge = useMemo(() => deriveJudge(root), [root]);
  const recipe = useMemo(() => recipeToUrl4(root), [root]);
  const draft = useMemo<SavedEnsemble>(
    () => buildDraft(ensembleId, name, root, runHistory),
    [ensembleId, name, root, runHistory],
  );
  const draftSnapshot = JSON.stringify(draft);
  const ready = loadedEnsembleId === ensembleId;
  const dirty = ready && draftSnapshot !== savedSnapshot;

  useEffect(() => {
    if (!ready || !autoSave || !dirty) return;
    const timer = window.setTimeout(() => {
      upsertEnsemble({ ...draft, updatedAt: Date.now() });
      setSavedSnapshot(draftSnapshot);
      if (!requestedId) {
        router.replace(`/ensembles/new/?id=${encodeURIComponent(ensembleId)}`, {
          scroll: false,
        });
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [
    autoSave,
    dirty,
    draft,
    draftSnapshot,
    ensembleId,
    ready,
    requestedId,
    router,
    upsertEnsemble,
  ]);

  function saveDraft() {
    upsertEnsemble({ ...draft, updatedAt: Date.now() });
    setSavedSnapshot(draftSnapshot);
    if (!requestedId) {
      router.replace(`/ensembles/new/?id=${encodeURIComponent(ensembleId)}`, {
        scroll: false,
      });
    }
    setSavedFlash(true);
    window.setTimeout(() => setSavedFlash(false), 1500);
  }

  function completeRun(run: SavedRun) {
    const nextRunHistory = [...runHistory, run];
    const savedDraft: SavedEnsemble = {
      ...draft,
      runs: nextRunHistory.length,
      runHistory: nextRunHistory,
    };
    setRunHistory(nextRunHistory);
    upsertEnsemble({ ...savedDraft, updatedAt: Date.now() });
    setSavedSnapshot(JSON.stringify(savedDraft));
    if (!requestedId) {
      router.replace(`/ensembles/new/?id=${encodeURIComponent(ensembleId)}`, {
        scroll: false,
      });
    }
  }

  function publishRun(run: SavedRun) {
    const nextRunHistory = runHistory.map((item) =>
      item.id === run.id ? { ...item, published: true } : item,
    );
    const savedDraft: SavedEnsemble = {
      ...draft,
      runs: nextRunHistory.length,
      runHistory: nextRunHistory,
    };
    setRunHistory(nextRunHistory);
    upsertEnsemble({ ...savedDraft, updatedAt: Date.now() });
    setSavedSnapshot(JSON.stringify(savedDraft));
  }

  async function copyRecipe() {
    await navigator.clipboard.writeText(recipe);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  return (
    <Tabs
      value={tab}
      onValueChange={(value) => setTab(value as "compose" | "runs")}
      className="flex h-full flex-col overflow-hidden bg-background"
    >
      <header className="shrink-0 border-b px-5 py-4 sm:px-8">
        <Link
          href="/ensembles/"
          prefetch={false}
          className="mb-3 inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="size-3.5" />
          All fusions
        </Link>

        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex min-w-0 flex-wrap items-center gap-3">
            {editingName ? (
              <Input
                autoFocus
                value={name}
                className="h-8 w-52 font-mono text-base font-semibold"
                onChange={(event) =>
                  setName(
                    event.target.value.replace(/\s+/g, "-").toLowerCase(),
                  )
                }
                onBlur={() => setEditingName(false)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === "Escape") {
                    setEditingName(false);
                  }
                }}
              />
            ) : (
              <button
                type="button"
                className="group flex min-w-0 items-center gap-2"
                onClick={() => setEditingName(true)}
                title="Rename fusion"
              >
                <span className="truncate font-mono text-base font-semibold">
                  {name}
                </span>
                <Pencil className="size-3 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </button>
            )}
            <span className="text-xs text-muted-foreground">
              {slots.length} models · {runHistory.length} runs
            </span>
            {!autoSave && dirty && (
              <Badge variant="secondary" className="bg-primary/15 text-primary">
                unsaved
              </Badge>
            )}
          </div>

          <div className="flex items-center gap-2 sm:gap-3">
            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              Auto-save
              <Switch
                checked={autoSave}
                onCheckedChange={(checked) => setAutoSave(checked)}
              />
            </label>
            <Button
              variant="outline"
              size="sm"
              disabled={autoSave || !dirty}
              onClick={saveDraft}
            >
              {savedFlash ? (
                <Check className="size-3.5 text-accent" />
              ) : (
                <Upload className="size-3.5 rotate-180" />
              )}
              {savedFlash ? "Saved" : "Save"}
            </Button>
            <Button variant="outline" size="sm" onClick={copyRecipe}>
              {copied ? (
                <Check className="size-3.5 text-accent" />
              ) : (
                <Share2 className="size-3.5" />
              )}
              {copied ? "Copied" : "Share url4"}
            </Button>
          </div>
        </div>

        <TabsList className="-mb-4 mt-4">
          <TabsTrigger value="compose">Compose</TabsTrigger>
          <TabsTrigger value="runs">
            Runs
            {runHistory.length > 0 && (
              <span className="ml-1.5 rounded-md bg-primary/15 px-1.5 py-0.5 font-mono text-xs font-semibold text-primary ring-1 ring-primary/20">
                {runHistory.length}
              </span>
            )}
          </TabsTrigger>
        </TabsList>
      </header>

      <TabsContent
        value="compose"
        className="m-0 flex min-h-0 flex-1 overflow-hidden"
      >
          <main className="flex min-w-0 flex-1 flex-col overflow-hidden px-6 py-6 lg:px-10">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted-foreground">
                A unit is a solo model, a fusion (parallel members → a synthesizer), or a
                pipeline (sequential stages). Nest to any depth.
              </p>
              <div className="flex shrink-0 items-center gap-1.5">
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-7"
                    aria-label="Scroll left"
                    onClick={() =>
                      canvasRef.current?.scrollBy({ left: -360, behavior: "smooth" })
                    }
                  >
                    <ChevronLeft className="size-3.5" />
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-7"
                    aria-label="Scroll right"
                    onClick={() =>
                      canvasRef.current?.scrollBy({ left: 360, behavior: "smooth" })
                    }
                  >
                    <ChevronRight className="size-3.5" />
                  </Button>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-7"
                    aria-label="Zoom out"
                    disabled={zoom <= 0.5}
                    onClick={() =>
                      setZoom((value) => Math.max(0.5, Math.round((value - 0.1) * 10) / 10))
                    }
                  >
                    <ZoomOut className="size-3.5" />
                  </Button>
                  <button
                    type="button"
                    className="w-11 text-center font-mono text-xs tabular-nums text-muted-foreground transition-colors hover:text-foreground"
                    title="Reset zoom"
                    onClick={() => setZoom(1)}
                  >
                    {Math.round(zoom * 100)}%
                  </button>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    className="size-7"
                    aria-label="Zoom in"
                    disabled={zoom >= 1.3}
                    onClick={() =>
                      setZoom((value) => Math.min(1.3, Math.round((value + 0.1) * 10) / 10))
                    }
                  >
                    <ZoomIn className="size-3.5" />
                  </Button>
                </div>
              </div>
            </div>
            <div ref={canvasRef} className="min-h-0 flex-1 overflow-auto">
              <div
                className="w-max min-w-full pb-6 pr-6 transition-transform"
                style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
              >
                <RecipeNodeCard
                  node={root}
                  role="root"
                  depth={0}
                  providers={providers}
                  onUseModels={(models) => addLibraryModels(models)}
                  onChange={setRoot}
                />
              </div>
            </div>
          </main>

          <aside className="flex w-80 shrink-0 flex-col gap-6 overflow-y-auto border-l bg-muted/10 px-5 py-6">
            <div>
              <p className="mb-3 font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
                Recipe
              </p>
              <p className="text-xs">
                <span className="font-mono text-primary">{describeRecipe(root)}</span>
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {slots.length} model{slots.length === 1 ? "" : "s"} in play
              </p>
            </div>

            <div>
              <p className="mb-3 font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
                url4 preview
              </p>
              <div className="rounded-lg border bg-card p-2">
                <code className="block break-all font-mono text-[11px] text-primary/90">
                  {recipe}
                </code>
              </div>
              <p className="mt-1.5 text-[11px] text-muted-foreground">
                Structural preview — the engine emits the canonical url4 at run time.
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2 w-full"
                onClick={copyRecipe}
              >
                {copied ? (
                  <Check className="size-3.5 text-accent" />
                ) : (
                  <Copy className="size-3.5" />
                )}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>

            <div>
              <Button
                className="w-full rounded-xl"
                onClick={() => setTab("runs")}
              >
                Next: Run
                <ArrowRight className="size-4" />
              </Button>
            </div>
          </aside>
      </TabsContent>
      <TabsContent
        value="runs"
        className="m-0 min-h-0 flex-1 overflow-hidden"
      >
        <RunsPanel
          slots={slots}
          judge={judge}
          runs={runHistory}
          ensembleName={name}
          onComplete={completeRun}
          onPublish={publishRun}
          onBackToCompose={() => setTab("compose")}
        />
      </TabsContent>
    </Tabs>
  );
}

export default function EnsembleComposerPage() {
  return (
    <Suspense>
      <EnsembleComposer />
    </Suspense>
  );
}
