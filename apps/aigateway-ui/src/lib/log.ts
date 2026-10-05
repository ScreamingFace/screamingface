import "server-only";

/**
 * The BFF's server-side logger: one JSON object per line, on the console method matching its
 * level, so the container runtime ships it and a log pipeline can query its fields.
 *
 * FEATURE: BFF error traceability (OME-943) — and the one reader of the chart's `LOG_LEVEL`
 * (`config.logLevel` → configmap), which until this module existed was rendered and ignored.
 *
 * WHY no logging library: four levels and `JSON.stringify` are the whole requirement, and a
 * dependency would be one more thing for `npm ci` to drift on.
 *
 * INVARIANT: server-only. A log line from this module may carry paths and request ids the browser
 * has no business seeing, and a client import must fail the build rather than ship it.
 *
 * AIDEV-NOTE: never pass an upstream response body, `AdminApiError.detail` or its `message` as a
 * field — they can carry provider text, and a key write's refusal can echo the key.
 */

export type LogLevel = "debug" | "info" | "warn" | "error";

const RANK: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };

const DEFAULT_LEVEL: LogLevel = "info";

function isLevel(value: string): value is LogLevel {
  return Object.hasOwn(RANK, value);
}

/**
 * The configured threshold.
 *
 * WHY read per call rather than once at module load: the cost is one env lookup on a path that
 * only runs when something failed, and it keeps the module free of import-order state.
 *
 * WHY an unrecognised value falls back to `info` rather than silencing everything: a typo in a
 * Helm value must never be the reason an outage left no trace.
 */
function threshold(): LogLevel {
  const configured = process.env.LOG_LEVEL?.trim().toLowerCase() ?? "";
  return isLevel(configured) ? configured : DEFAULT_LEVEL;
}

export function log(level: LogLevel, msg: string, fields: Record<string, unknown> = {}): void {
  if (RANK[level] < RANK[threshold()]) return;
  // INVARIANT: `level`, `time` and `msg` are written AFTER the fields, so no caller-supplied field
  // can forge them.
  const line = JSON.stringify({ ...fields, level, time: new Date().toISOString(), msg });
  console[level](line);
}
