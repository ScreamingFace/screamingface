// Runtime check of a run's `CandidateResult` before Studio trusts it. It mirrors the Engine's
// producer models and their validators exactly (owner decision 2026-10-21: parity, not a
// narrower reader): `apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py`
// and `operation_accounting.py`. Every model there is strict and closed (`extra="forbid"`), so
// an unknown key is refused here too.

import type { CandidateResult, CaseId } from "./run-types";

export const CANDIDATE_RESULT_SCHEMA = "screamingface.candidate-result.v1";

export type ResultCheck =
  | { ok: true; value: CandidateResult }
  | { ok: false; field: string; rule?: string };

class BadField extends Error {
  constructor(
    readonly field: string,
    readonly rule?: string,
  ) {
    super(field);
  }
}

type Json = Record<string, unknown>;

// The declared failure vocabulary (`contract.py` `DECLARED_FAILURE_CODES` and
// `_AIGATEWAY_HTTP_CODE`, :55-168). The SDK keeps its own copy (`_report_primitives.py`).
const DECLARED_FAILURE_CODES = new Set([
  "benchmark_unavailable",
  "benchmark_operation_unsupported",
  "benchmark_retrieval_unavailable",
  "provider_refusal",
  "model_token_cap",
  "model_empty_content",
  "model_parameter_invalid",
  "aigateway_bad_response",
  "aigateway_empty_response",
  "aigateway_transport_error",
  "gateway_internal_error",
  "attempt_grade_not_pass_fail",
  "provider_queue_timeout",
  "provider_execution_timeout",
  "caller_deadline_exceeded",
  "aigateway_deadline_exceeded",
  "frozen_copy_miss",
  "frozen_copy_unavailable",
  "invalid_candidate_input",
  "web_tool_loop_limit",
  "web_retrieval_invalid",
  "web_retrieval_unavailable",
  "result_too_large",
  "candidate_contract_error",
  "candidate_policy_invalid",
  "candidate_policy_escalation",
  "case_result_missing",
  "case_execution_failed",
  "corrective_role_failed",
  "judge_reply_invalid",
  "invalid_case_evaluation",
  "ifeval_checker_failed",
  "draco_grading_failed",
  "gdpval_grading_failed",
  "healthbench_grading_failed",
  "medxpert_grading_failed",
  "inspect_grading_failed",
  "contracteval_grading_failed",
  "polarity_mismatch",
  "missing_answer_asset",
  "missing_target_asset",
  "missing_case_row",
  "missing_rubric_asset",
  "case_error",
  "incomplete_verdicts",
  "no_positive_points",
  "missing_case_rubric",
  "scorer_error",
  "invalid_score_value",
  "grading_dependency_failed",
  "grading_failed",
  "resolution_failed",
  "judge_unavailable",
  "asset_unavailable",
  "provider_error",
  "rate_limited",
  "candidate_failed",
  "checker_failed",
  "judge_failed",
  "benchmark_contract_error",
  "benchmark_definition_error",
  "upstream_error",
  "combine_spec_invalid",
  "combine_operator_unknown",
  "combine_input_too_large",
]);
const AIGATEWAY_HTTP_CODE = /^aigateway_http_[1-5][0-9]{2}$/;

// ── Shapes ───────────────────────────────────────────────────────────────────

// A closed object: every key one of `required` or `optional`, and every `required` key there.
// A missing key is named by its own path; an unknown one by the object's.
// The result itself is `result`; its own fields are named bare (`benchmark_id`).
function model(value: unknown, at: string, required: string[], optional: string[] = []): Json {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new BadField(at);
  const item = value as Json;
  const path = (key: string) => (at === "result" ? key : `${at}.${key}`);
  for (const key of required) if (!(key in item)) throw new BadField(path(key));
  const known = new Set([...required, ...optional]);
  const extra = Object.keys(item).find((key) => !known.has(key));
  if (extra !== undefined) throw new BadField(at, `unexpected key "${extra}"`);
  return item;
}

function list(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw new BadField(field);
  return value;
}

function text(value: unknown, field: string, { nonEmpty = false, nonBlank = false } = {}) {
  if (typeof value !== "string") throw new BadField(field);
  if ((nonEmpty && value.length === 0) || (nonBlank && !value.trim())) throw new BadField(field);
  return value;
}

function number(value: unknown, field: string, { min = -Infinity, max = Infinity } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) {
    throw new BadField(field);
  }
  return value;
}

function integer(value: unknown, field: string, min = -Infinity) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < min) {
    throw new BadField(field);
  }
  return value;
}

function nullable<T>(value: unknown, read: (value: unknown) => T): T | null {
  return value === null ? null : read(value);
}

// Absent or null (`default=None`, `exclude_if=... is None`), or valid.
function optional<T>(value: unknown, read: (value: unknown) => T): T | null | undefined {
  return value === undefined || value === null ? value : read(value);
}

// `_json_value` / `_is_json_value` (:698-716): open fields (`metadata`, `metrics`, `raw_output`) hold JSON values
// only, and every number in them is finite, however deep.
function jsonValue(value: unknown): boolean {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(jsonValue);
  if (typeof value === "object") return Object.values(value as Json).every(jsonValue);
  return false;
}

function jsonMapping(value: unknown, field: string): Json {
  if (!value || typeof value !== "object" || Array.isArray(value) || !jsonValue(value)) {
    throw new BadField(field);
  }
  return value as Json;
}

// `validate_case_id` (:678-685): a non-boolean integer or a non-blank string.
function caseId(value: unknown, field: string): CaseId {
  if (typeof value === "number" && Number.isInteger(value)) return value;
  if (typeof value === "string" && value.trim()) return value;
  throw new BadField(field);
}

// `validate_finish_reason` (:688-695): non-blank text or null.
function finishReason(value: unknown, field: string) {
  return nullable(value, (reason) => text(reason, field, { nonBlank: true }));
}

// `_finite_score` (:719-724) with the field's bounds.
function score(value: unknown, field: string, bounds: { min?: number; max?: number }) {
  return nullable(value, (item) => number(item, field, bounds));
}

// `_named_scores` (:727-738): non-blank names, each a finite number or null.
function namedScores(value: unknown, field: string) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new BadField(field);
  for (const [name, item] of Object.entries(value as Json)) {
    if (!name.trim()) throw new BadField(field, "a score name is blank");
    if (item !== null && (typeof item !== "number" || !Number.isFinite(item))) {
      throw new BadField(`${field}.${name}`);
    }
  }
  return value as Record<string, number | null>;
}

// ── operation_accounting.py ──────────────────────────────────────────────────

const FIXED_POINT_USD = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;

// `OperationAccounting` / `OperationUsage` / `OperationCache` (operation_accounting.py:22-75).
function accounting(value: unknown, at: string) {
  const item = model(value, at, [
    "provider",
    "request_model",
    "response_model",
    "usage",
    "provider_latency_ms",
    "provider_attempts",
    "cache",
  ]);
  for (const key of ["provider", "request_model", "response_model"]) {
    nullable(item[key], (identity) => text(identity, `${at}.${key}`, { nonBlank: true }));
  }
  const usage = model(item.usage, `${at}.usage`, [
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "reasoning_tokens",
    "cost_usd",
  ]);
  for (const key of [
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
    "reasoning_tokens",
  ]) {
    nullable(usage[key], (count) => integer(count, `${at}.usage.${key}`, 0));
  }
  nullable(usage.cost_usd, (cost) => {
    if (typeof cost !== "string" || !FIXED_POINT_USD.test(cost)) {
      throw new BadField(`${at}.usage.cost_usd`);
    }
    return cost;
  });
  nullable(item.provider_latency_ms, (ms) => integer(ms, `${at}.provider_latency_ms`, 0));
  nullable(item.provider_attempts, (count) => integer(count, `${at}.provider_attempts`, 0));
  const cache = model(item.cache, `${at}.cache`, ["hits", "misses", "bypasses", "unknown"]);
  const responses = ["hits", "misses", "bypasses", "unknown"].reduce(
    (sum, key) => sum + integer(cache[key], `${at}.cache.${key}`, 0),
    0,
  );
  if (responses < 1) {
    throw new BadField(`${at}.cache`, "operation cache accounting requires at least one response");
  }
}

// ── contract.py ──────────────────────────────────────────────────────────────

const OUTCOMES = new Set(["MET", "UNMET", "PASS", "FAIL"]);
const STAGES = new Set(["candidate", "grading", "aggregation"]);

// `Evidence` (:189-210).
function evidence(value: unknown, at: string) {
  const item = model(
    value,
    at,
    ["sequence", "producer", "valid", "raw_output", "metadata", "accounting"],
    ["outcome", "explanation"],
  );
  integer(item.sequence, `${at}.sequence`, 1);
  const producer = model(item.producer, `${at}.producer`, ["type", "id"]);
  text(producer.type, `${at}.producer.type`, { nonEmpty: true });
  text(producer.id, `${at}.producer.id`, { nonEmpty: true });
  if (typeof item.valid !== "boolean") throw new BadField(`${at}.valid`);
  optional(item.outcome, (outcome) => {
    if (!OUTCOMES.has(outcome as string)) throw new BadField(`${at}.outcome`);
    return outcome;
  });
  optional(item.explanation, (explanation) => text(explanation, `${at}.explanation`));
  if (!jsonValue(item.raw_output)) throw new BadField(`${at}.raw_output`);
  jsonMapping(item.metadata, `${at}.metadata`);
  nullable(item.accounting, (entry) => accounting(entry, `${at}.accounting`));
  if (!item.valid && ((item.outcome ?? null) !== null || (item.explanation ?? null) !== null)) {
    throw new BadField(at, "invalid Evidence cannot claim an outcome or explanation");
  }
}

// `Check` (:213-231).
function check(value: unknown, at: string) {
  const item = model(value, at, ["type", "id", "label", "evidence", "metadata"], ["outcome", "score"]);
  text(item.type, `${at}.type`, { nonEmpty: true });
  text(item.id, `${at}.id`, { nonEmpty: true });
  text(item.label, `${at}.label`);
  optional(item.outcome, (outcome) => {
    if (outcome !== "MET" && outcome !== "UNMET") throw new BadField(`${at}.outcome`);
    return outcome;
  });
  optional(item.score, (value) => number(value, `${at}.score`, { min: 0, max: 1 }));
  list(item.evidence, `${at}.evidence`).forEach((entry, index) =>
    evidence(entry, `${at}.evidence[${index}]`),
  );
  jsonMapping(item.metadata, `${at}.metadata`);
}

// `CaseGrade` (:234-260). HealthBench permits negative case scores; never above 1.
function grade(value: unknown, at: string): { score: number | null } {
  const item = model(value, at, ["method", "score", "metrics", "checks"], ["scores"]);
  text(item.method, `${at}.method`, { nonEmpty: true });
  const graded = score(item.score, `${at}.score`, { max: 1 });
  jsonMapping(item.metrics, `${at}.metrics`);
  list(item.checks, `${at}.checks`).forEach((entry, index) => check(entry, `${at}.checks[${index}]`));
  if (item.scores !== undefined) namedScores(item.scores, `${at}.scores`);
  return { score: graded };
}

type Failure = { code: string; caseId: CaseId | null };

// `Failure` (:263-288): every field is required, and the code is a declared one.
function failures(value: unknown, at: string): Failure[] {
  return list(value, at).map((entry, index) => {
    const field = `${at}[${index}]`;
    const item = model(entry, field, ["stage", "code", "message", "retryable", "case_id", "metadata"]);
    if (!STAGES.has(item.stage as string)) throw new BadField(`${field}.stage`);
    const code = text(item.code, `${field}.code`, { nonEmpty: true });
    if (!DECLARED_FAILURE_CODES.has(code) && !AIGATEWAY_HTTP_CODE.test(code)) {
      throw new BadField(`${field}.code`, `undeclared failure code "${code}"`);
    }
    text(item.message, `${field}.message`, { nonEmpty: true });
    if (item.retryable !== null && typeof item.retryable !== "boolean") {
      throw new BadField(`${field}.retryable`);
    }
    const id = nullable(item.case_id, (value) => caseId(value, `${field}.case_id`));
    jsonMapping(item.metadata, `${field}.metadata`);
    return { code, caseId: id };
  });
}

// `OperationOutput` (:349-373). `combine` (OME-1289 combine evidence) is checked as an object
// carrying its schema: it only appears on a reducer's combine step, which Studio's recipes
// (no reducers, spec D6) never produce.
function operations(value: unknown, at: string) {
  list(value, at).forEach((entry, index) => {
    const field = `${at}[${index}]`;
    const item = model(entry, field, ["operation_id", "output", "finish_reason", "accounting"], ["combine"]);
    text(item.operation_id, `${field}.operation_id`, { nonEmpty: true });
    nullable(item.output, (output) => text(output, `${field}.output`));
    finishReason(item.finish_reason, `${field}.finish_reason`);
    nullable(item.accounting, (entry) => accounting(entry, `${field}.accounting`));
    optional(item.combine, (combine) => {
      const evidence = combine as Json;
      if (!combine || typeof combine !== "object" || evidence.schema !== "screamingface.combine-evidence.v1") {
        throw new BadField(`${field}.combine`);
      }
      return combine;
    });
  });
}

type Outcome = {
  status: unknown;
  output: string | null;
  refusal: string | null;
  grade: { score: number | null } | null;
  failures: Failure[];
};

// `_require_case_outcome` / `_require_scored_case` / `_require_failed_case` (:474-486, :515-547):
// the scored-or-failed rules every Case Result, and every Attempt, obeys.
function caseOutcome(outcome: Outcome, id: CaseId, at: string) {
  outcome.failures.forEach((failure, index) => {
    if (failure.caseId !== id) {
      throw new BadField(`${at}.failures[${index}].case_id`, "every Case Failure must reference its own case_id");
    }
  });
  const numeric = outcome.grade !== null && outcome.grade.score !== null;
  if (outcome.status === "scored") {
    if (!numeric || (outcome.output === null) === (outcome.refusal === null) || outcome.failures.length) {
      throw new BadField(
        at,
        "a scored Case requires a numeric grade and exactly one of output and refusal, and cannot carry failures",
      );
    }
    return;
  }
  if (!outcome.failures.length || numeric) {
    throw new BadField(at, "a failed Case requires failures and no numeric grade");
  }
  if (outcome.refusal !== null && outcome.failures.every((failure) => failure.code !== "provider_refusal")) {
    throw new BadField(at, "a failed Case carries refusal text only with a provider_refusal failure");
  }
}

function status(value: unknown, field: string) {
  if (value !== "scored" && value !== "failed") throw new BadField(field);
  return value;
}

// `CaseAttempt` (:374-395); its outcome is checked against the owning Case's id.
function attempt(value: unknown, at: string, id: CaseId): number {
  const item = model(
    value,
    at,
    ["attempt", "status", "output", "finish_reason", "refusal", "grade", "failures"],
    ["operations"],
  );
  const number = integer(item.attempt, `${at}.attempt`, 1);
  const outcome: Outcome = {
    status: status(item.status, `${at}.status`),
    output: nullable(item.output, (output) => text(output, `${at}.output`)),
    refusal: nullable(item.refusal, (refusal) => text(refusal, `${at}.refusal`)),
    grade: nullable(item.grade, (graded) => grade(graded, `${at}.grade`)),
    failures: failures(item.failures, `${at}.failures`),
  };
  nullable(item.finish_reason, (reason) => text(reason, `${at}.finish_reason`));
  optional(item.operations, (entries) => operations(entries, `${at}.operations`));
  caseOutcome(outcome, id, at);
  return number;
}

// `CaseResult` (:291-346).
function caseResult(value: unknown, at: string): { id: CaseId; numeric: boolean; scored: boolean } {
  const item = model(
    value,
    at,
    ["status", "case_id", "input", "output", "finish_reason", "refusal", "grade", "failures", "metadata"],
    ["stop_reason", "rounds_executed", "operations", "attempts", "abstained"],
  );
  const caseStatus = status(item.status, `${at}.status`);
  const id = caseId(item.case_id, `${at}.case_id`);
  text(item.input, `${at}.input`, { nonEmpty: true });
  const output = nullable(item.output, (output) => text(output, `${at}.output`));
  finishReason(item.finish_reason, `${at}.finish_reason`);
  // `refusal` is non-empty text or null.
  const refusal = nullable(item.refusal, (refusal) => text(refusal, `${at}.refusal`, { nonBlank: true }));
  optional(item.stop_reason, (reason) => {
    if (reason !== "passed" && reason !== "max_rounds") throw new BadField(`${at}.stop_reason`);
    return reason;
  });
  optional(item.rounds_executed, (rounds) => integer(rounds, `${at}.rounds_executed`, 1));
  const graded = nullable(item.grade, (entry) => grade(entry, `${at}.grade`));
  const caseFailures = failures(item.failures, `${at}.failures`);
  jsonMapping(item.metadata, `${at}.metadata`);
  optional(item.operations, (entries) => operations(entries, `${at}.operations`));
  const attempts = optional(item.attempts, (entries) => list(entries, `${at}.attempts`));
  if (item.abstained !== undefined && typeof item.abstained !== "boolean") {
    throw new BadField(`${at}.abstained`);
  }
  if ((item.stop_reason ?? null) === null !== ((item.rounds_executed ?? null) === null)) {
    throw new BadField(at, "stop_reason and rounds_executed must be present together");
  }
  caseOutcome({ status: caseStatus, output, refusal, grade: graded, failures: caseFailures }, id, at);
  if (attempts) {
    // `_require_case_attempts` (:489-512): numbered 1..N with N ≥ 2; each Attempt carries its
    // own operations, so the Case carries none.
    const numbers = attempts.map((entry, index) => attempt(entry, `${at}.attempts[${index}]`, id));
    if (numbers.length < 2 || numbers.some((number, index) => number !== index + 1)) {
      throw new BadField(`${at}.attempts`, "Case attempts must be numbered 1..N with N of at least 2");
    }
    if ((item.operations ?? null) !== null) {
      throw new BadField(`${at}.operations`, "a Case with attempts carries its operations on each attempt");
    }
  }
  // `_require_abstained_case` (:526-536).
  if (item.abstained === true && (caseStatus !== "scored" || graded?.score !== 0 || output !== "" || refusal !== null)) {
    throw new BadField(at, "an abstained Case is a scored empty answer with score 0.0");
  }
  return { id, numeric: graded !== null && graded.score !== null, scored: caseStatus === "scored" };
}

// Python's `round(x, 4)` (`candidate_coverage`, :633-642): round-half-even on the binary value.
function pythonRound4(value: number): number {
  const digits = value.toFixed(20);
  const [whole, fraction] = digits.split(".");
  const kept = Number(`${whole}.${fraction.slice(0, 4)}`);
  const rest = fraction.slice(4);
  const step = 1e-4;
  if (/^50*$/.test(rest)) {
    const last = Number(fraction[3]);
    return last % 2 === 0 ? kept : Number((kept + step).toFixed(4));
  }
  return rest[0] >= "5" ? Number((kept + step).toFixed(4)) : kept;
}

export function checkCandidateResult(value: unknown): ResultCheck {
  try {
    const result = model(
      value,
      "result",
      ["schema", "benchmark_id", "benchmark_revision", "case_count", "score", "coverage", "metrics", "cases", "failures"],
      ["inverted_grade", "scores"],
    );
    if (result.schema !== CANDIDATE_RESULT_SCHEMA) throw new BadField("schema");
    text(result.benchmark_id, "benchmark_id");
    text(result.benchmark_revision, "benchmark_revision");
    const caseCount = integer(result.case_count, "case_count", 0);
    // The score may be negative (an inverted grade) but never above 1.
    const candidateScore = score(result.score, "score", { max: 1 });
    const coverage = number(result.coverage, "coverage", { min: 0, max: 1 });
    const metrics = jsonMapping(result.metrics, "metrics");
    const seen = new Set<CaseId>();
    const cases = list(result.cases, "cases").map((entry, index) => {
      const checked = caseResult(entry, `cases[${index}]`);
      // `CandidateResult` cannot contain duplicate case_id values (:614-626).
      if (seen.has(checked.id)) throw new BadField(`cases[${index}].case_id`);
      seen.add(checked.id);
      return checked;
    });
    const candidateFailures = failures(result.failures, "failures");
    if (result.inverted_grade !== undefined && typeof result.inverted_grade !== "boolean") {
      throw new BadField("inverted_grade");
    }
    const scores = result.scores === undefined ? {} : namedScores(result.scores, "scores");

    // `_enforce_result_contract` (:614-626).
    if (caseCount !== cases.length) throw new BadField("case_count");
    candidateFailures.forEach((failure, index) => {
      if (failure.caseId !== null) {
        throw new BadField(`failures[${index}].case_id`, "a Candidate-level Failure cannot claim a case_id");
      }
    });
    // `_candidate_outcome` / `_unscored_candidate_outcome` (:645-675).
    if ("coverage" in metrics) {
      throw new BadField("metrics", "metrics.coverage is replaced by top-level coverage");
    }
    const gradeable = cases.filter((item) => item.numeric).length;
    const expected = caseCount ? pythonRound4(gradeable / caseCount) : 0;
    if (coverage !== expected) {
      throw new BadField("coverage", `coverage must equal numeric Case grades / selected Cases (${expected})`);
    }
    if (candidateScore === null) {
      if (Object.keys(metrics).length) {
        throw new BadField("metrics", "a failed or unscored Candidate cannot contain metrics");
      }
      if (Object.keys(scores).length) {
        throw new BadField("scores", "a failed or unscored Candidate cannot contain scores");
      }
      if (gradeable) throw new BadField("score", "an unscored Candidate cannot contain a numeric Case grade");
      if (!candidateFailures.length && cases.every((item) => item.scored)) {
        throw new BadField("score", "an unscored Candidate must be explained by a non-scored Case or Failure");
      }
    } else if (!gradeable) {
      throw new BadField("score", "a scored Candidate requires at least one numeric Case grade");
    }
    return { ok: true, value: result as CandidateResult };
  } catch (error) {
    if (error instanceof BadField) return { ok: false, field: error.field, rule: error.rule };
    throw error;
  }
}
