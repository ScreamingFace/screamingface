// Wire shapes of one Engine run, as Studio reads them: the `CandidateResult` a run resolves to
// (`screamingface_engine/benchmarks/contract.py`, `screamingface.candidate-result.v1`) and the
// typed events `startRun` reports while it runs. Only the fields Studio reads are spelled out.

export type CaseId = string | number;

export type CaseFailure = {
  stage: "candidate" | "grading" | "aggregation";
  code: string;
  message: string;
  retryable: boolean | null;
  case_id: CaseId | null;
  metadata: Record<string, unknown>;
};

export type CaseCheck = {
  type: string;
  id: string;
  label: string;
  outcome?: "MET" | "UNMET" | null;
  score?: number | null;
  evidence: unknown[];
  metadata: Record<string, unknown>;
};

export type CaseGrade = {
  method: string;
  score: number | null;
  metrics: Record<string, unknown>;
  checks: CaseCheck[];
  scores?: Record<string, number | null>;
};

// `operation_accounting.py`: exact-only accounting for one model call. `cost_usd` is a decimal
// string, or null when the provider priced nothing.
export type OperationAccounting = {
  provider: string | null;
  request_model: string | null;
  response_model: string | null;
  usage: {
    input_tokens: number | null;
    output_tokens: number | null;
    cache_read_tokens: number | null;
    cache_creation_tokens: number | null;
    reasoning_tokens: number | null;
    cost_usd: string | null;
  };
  provider_latency_ms: number | null;
  provider_attempts: number | null;
  cache: { hits: number; misses: number; bypasses: number; unknown: number };
};

export type OperationOutput = {
  operation_id: string;
  output: string | null;
  finish_reason: string | null;
  accounting: OperationAccounting | null;
};

export type CaseResult = {
  status: "scored" | "failed";
  case_id: CaseId;
  input: string;
  output: string | null;
  finish_reason: string | null;
  refusal: string | null;
  grade: CaseGrade | null;
  failures: CaseFailure[];
  metadata: Record<string, unknown>;
  operations?: OperationOutput[] | null;
};

export type CandidateResult = {
  schema: "screamingface.candidate-result.v1";
  benchmark_id: string;
  benchmark_revision: string;
  case_count: number;
  // Null when no case was graded (a provider that is not connected still "succeeds"). It can
  // be negative for an inverted grade.
  score: number | null;
  coverage: number;
  metrics: Record<string, unknown>;
  cases: CaseResult[];
  failures: CaseFailure[];
  inverted_grade?: boolean;
  scores?: Record<string, number | null>;
};

export type LogAttributes = Record<string, string | number | boolean | null>;

// What `startRun` reports as frames arrive, in stream order.
export type RunEvent =
  | { type: "started" }
  // `sf.progress.*` (`screamingface.benchmark-progress.v1`): cases finished so far, how many
  // were graded, and the running score (null until one is graded).
  | { type: "progress"; completed: number; graded: number; score: number | null }
  // `sf.activity.*` (`screamingface.activity.v1`): one stage of the run changing state.
  | {
      type: "activity";
      kind: string;
      state: string;
      caseId?: CaseId;
      modelId?: string;
      failureCode?: string;
      body: string;
    }
  // `ai.url4.cost.usage` with `scope: "subtree"`: the run's cost so far, in USD. A decimal
  // string on the wire (`CostBreakdown.total_usd`).
  | { type: "cost"; totalUsd: number }
  // Any other log line.
  | {
      type: "log";
      severity: string;
      body: string;
      attributes: LogAttributes;
    };
