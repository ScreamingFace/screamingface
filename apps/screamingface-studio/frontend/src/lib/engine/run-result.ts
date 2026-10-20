// Runtime check of a run's `CandidateResult` before Studio trusts it. The rules follow the Engine's
// wire models (`apps/screamingface-engine/src/screamingface_engine/benchmarks/contract.py`:
// `CandidateResult` :431-479, `CaseResult` :262-278, `CaseGrade` :205-219, `Failure` :234-242) for
// the fields Studio reads; anything else is passed through untouched.

import type { CandidateResult } from "./run-types";

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

// `Failure`: Studio shows `code` and `message`, both non-empty text.
function failures(value: unknown, field: string) {
  list(value, field).forEach((item, index) => {
    const failure = object(item, `${field}[${index}]`);
    text(failure.code, `${field}[${index}].code`, { nonEmpty: true });
    text(failure.message, `${field}[${index}].message`, { nonEmpty: true });
  });
}

function grade(value: unknown, field: string) {
  const graded = object(value, field);
  text(graded.method, `${field}.method`, { nonEmpty: true });
  nullable(graded.score, (score) => number(score, `${field}.score`, { max: 1 }));
  object(graded.metrics, `${field}.metrics`);
  list(graded.checks, `${field}.checks`);
}

function caseResult(value: unknown, field: string) {
  const item = object(value, field);
  if (item.status !== "scored" && item.status !== "failed") throw new BadField(`${field}.status`);
  // `CaseId = StrictInt | StrictStr`.
  const id = item.case_id;
  if (!(typeof id === "string" || (typeof id === "number" && Number.isInteger(id)))) {
    throw new BadField(`${field}.case_id`);
  }
  text(item.input, `${field}.input`, { nonEmpty: true });
  nullable(item.output, (output) => text(output, `${field}.output`));
  nullable(item.grade, (graded) => grade(graded, `${field}.grade`));
  failures(item.failures, `${field}.failures`);
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
    failures(result.failures, "failures");
    list(result.cases, "cases").forEach((item, index) => caseResult(item, `cases[${index}]`));
    return { ok: true, value: result as CandidateResult };
  } catch (error) {
    if (error instanceof BadField) return { ok: false, field: error.field };
    throw error;
  }
}
