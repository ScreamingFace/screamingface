// Runtime check of a run's `CandidateResult` before Studio trusts it. The rules follow the Engine's
// wire models (`apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py`:
// `CandidateResult` :431-479, `CaseResult` :262-278, `CaseGrade` :205-219, `Failure` :234-242) for
// the fields Studio reads; anything else is passed through untouched.

import type { CandidateResult, CaseId } from "./run-types";

export const CANDIDATE_RESULT_SCHEMA = "screamingface.candidate-result.v1";

export type ResultCheck = { ok: true; value: CandidateResult } | { ok: false; field: string };

class BadField extends Error {
  constructor(readonly field: string) {
    super(field);
  }
}

type Json = Record<string, unknown>;

function object(value: unknown, field: string): Json {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new BadField(field);
  return value as Json;
}

function list(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw new BadField(field);
  return value;
}

function text(value: unknown, field: string, { nonEmpty = false } = {}): string {
  if (typeof value !== "string" || (nonEmpty && value.length === 0)) throw new BadField(field);
  return value;
}

function number(value: unknown, field: string, { min = -Infinity, max = Infinity } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < min || value > max) {
    throw new BadField(field);
  }
  return value;
}

function nullable<T>(value: unknown, read: (value: unknown) => T): T | null {
  return value === null ? null : read(value);
}

function caseId(value: unknown, field: string): CaseId {
  // `CaseId = StrictInt | StrictStr`.
  if (!(typeof value === "string" || (typeof value === "number" && Number.isInteger(value)))) {
    throw new BadField(field);
  }
  return value;
}

const STAGES = new Set(["candidate", "grading", "aggregation"]);

// `Failure` (:234-242): every field is required. `owner` is the case a Case Failure must name
// (`CaseResult._enforce_status`), or null for a Candidate-level Failure, which names none
// (`CandidateResult._enforce_result_contract`).
function failures(value: unknown, field: string, owner: CaseId | null) {
  list(value, field).forEach((item, index) => {
    const at = `${field}[${index}]`;
    const failure = object(item, at);
    if (!STAGES.has(failure.stage as string)) throw new BadField(`${at}.stage`);
    text(failure.code, `${at}.code`, { nonEmpty: true });
    text(failure.message, `${at}.message`, { nonEmpty: true });
    if (failure.retryable !== null && typeof failure.retryable !== "boolean") {
      throw new BadField(`${at}.retryable`);
    }
    const id = nullable(failure.case_id, (value) => caseId(value, `${at}.case_id`));
    if (!("case_id" in failure) || id !== owner) throw new BadField(`${at}.case_id`);
    object(failure.metadata, `${at}.metadata`);
  });
}

// An optional field (`exclude_if=... is None`): absent, null, or valid.
function optional<T>(value: unknown, read: (value: unknown) => T): T | null | undefined {
  return value === undefined || value === null ? value : read(value);
}

// `Check` (:184-202).
function check(value: unknown, field: string) {
  const item = object(value, field);
  text(item.type, `${field}.type`, { nonEmpty: true });
  text(item.id, `${field}.id`, { nonEmpty: true });
  text(item.label, `${field}.label`);
  if (item.outcome !== undefined && item.outcome !== null && item.outcome !== "MET" && item.outcome !== "UNMET") {
    throw new BadField(`${field}.outcome`);
  }
  optional(item.score, (score) => number(score, `${field}.score`, { min: 0, max: 1 }));
  list(item.evidence, `${field}.evidence`).forEach((evidence, index) =>
    object(evidence, `${field}.evidence[${index}]`),
  );
  object(item.metadata, `${field}.metadata`);
}

function grade(value: unknown, field: string) {
  const graded = object(value, field);
  text(graded.method, `${field}.method`, { nonEmpty: true });
  nullable(graded.score, (score) => number(score, `${field}.score`, { max: 1 }));
  object(graded.metrics, `${field}.metrics`);
  list(graded.checks, `${field}.checks`).forEach((item, index) =>
    check(item, `${field}.checks[${index}]`),
  );
}

// `OperationOutput` (:314-331); its accounting is passed through as an object or null.
function operation(value: unknown, field: string) {
  const item = object(value, field);
  text(item.operation_id, `${field}.operation_id`, { nonEmpty: true });
  nullable(item.output, (output) => text(output, `${field}.output`));
  nullable(item.finish_reason, (reason) => text(reason, `${field}.finish_reason`));
  nullable(item.accounting, (accounting) => object(accounting, `${field}.accounting`));
}

// `CaseResult` (:262-312).
function caseResult(value: unknown, field: string): CaseId {
  const item = object(value, field);
  if (item.status !== "scored" && item.status !== "failed") throw new BadField(`${field}.status`);
  const id = caseId(item.case_id, `${field}.case_id`);
  text(item.input, `${field}.input`, { nonEmpty: true });
  nullable(item.output, (output) => text(output, `${field}.output`));
  if (item.finish_reason === undefined) throw new BadField(`${field}.finish_reason`);
  nullable(item.finish_reason, (reason) => text(reason, `${field}.finish_reason`));
  // `refusal` is non-empty text or null.
  if (item.refusal !== null && (typeof item.refusal !== "string" || !item.refusal.trim())) {
    throw new BadField(`${field}.refusal`);
  }
  if (item.grade === undefined) throw new BadField(`${field}.grade`);
  nullable(item.grade, (graded) => grade(graded, `${field}.grade`));
  failures(item.failures, `${field}.failures`, id);
  object(item.metadata, `${field}.metadata`);
  optional(item.operations, (operations) =>
    list(operations, `${field}.operations`).forEach((entry, index) =>
      operation(entry, `${field}.operations[${index}]`),
    ),
  );
  return id;
}

export function checkCandidateResult(value: unknown): ResultCheck {
  try {
    const result = object(value, "result");
    if (result.schema !== CANDIDATE_RESULT_SCHEMA) throw new BadField("schema");
    text(result.benchmark_id, "benchmark_id");
    text(result.benchmark_revision, "benchmark_revision");
    if (!Number.isInteger(result.case_count) || (result.case_count as number) < 0) {
      throw new BadField("case_count");
    }
    // The score may be negative (an inverted grade) but never above 1.
    nullable(result.score, (score) => number(score, "score", { max: 1 }));
    number(result.coverage, "coverage", { min: 0, max: 1 });
    object(result.metrics, "metrics");
    failures(result.failures, "failures", null);
    const ids = new Set<CaseId>();
    const cases = list(result.cases, "cases");
    cases.forEach((item, index) => {
      const id = caseResult(item, `cases[${index}]`);
      // `CandidateResult` cannot contain duplicate case_id values.
      if (ids.has(id)) throw new BadField(`cases[${index}].case_id`);
      ids.add(id);
    });
    // `case_count` is exact: one entry per selected Case.
    if (result.case_count !== cases.length) throw new BadField("case_count");
    return { ok: true, value: result as CandidateResult };
  } catch (error) {
    if (error instanceof BadField) return { ok: false, field: error.field };
    throw error;
  }
}
