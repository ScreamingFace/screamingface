export type EngineErrorKind =
  | "unreachable"
  | "invalid"
  | "unauthenticated"
  | "not_found"
  | "unavailable"
  | "unknown";

const GENERIC_DETAIL: Record<EngineErrorKind, string> = {
  unreachable: "The ScreamingFace Engine could not be reached.",
  invalid: "The Engine rejected the request.",
  unauthenticated: "The provider credential was rejected.",
  not_found: "The Engine does not know this provider.",
  unavailable: "The Engine is temporarily unavailable.",
  unknown: "The Engine returned an unexpected response.",
};

export class EngineError extends Error {
  readonly kind: EngineErrorKind;
  readonly status?: number;
  readonly detail: string;

  constructor(kind: EngineErrorKind, detail?: string, status?: number) {
    const text = detail?.trim() || GENERIC_DETAIL[kind];
    super(text);
    this.name = "EngineError";
    this.kind = kind;
    this.status = status;
    this.detail = text;
  }
}

export function kindForStatus(status: number): EngineErrorKind {
  if (status === 400 || status === 422) return "invalid";
  if (status === 401 || status === 403) return "unauthenticated";
  if (status === 404) return "not_found";
  if (status === 502 || status === 503 || status === 504) return "unavailable";
  return "unknown";
}

export function isEngineError(value: unknown): value is EngineError {
  return value instanceof EngineError;
}
