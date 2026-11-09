// Wire shapes of the SF Engine's provider-connection and catalog routes
// (`screamingface_engine/rest/connections.py`, `rest/catalog.py`, `rest/benchmarks.py`). Only the
// fields Studio reads.

export type AuthMethod = "api_key" | "oauth";

export type ConnectionStatus =
  | "not_connected"
  | "pending"
  | "connected"
  | "needs_reauth"
  | "error";

export type Connection = {
  object: "connection";
  provider: string;
  display_name: string;
  auth_methods: AuthMethod[];
  status: ConnectionStatus;
  auth_method?: AuthMethod | null;
  account_label?: string | null;
};

export type OAuthAuthorization = {
  object: "oauth_authorization";
  provider: string;
  authorize_url: string;
  expires_in: number;
};

export type EngineModel = {
  id: string;
  object?: "model";
  owned_by: string;
  supported_parameters?: string[];
  supported_tools?: string[];
};

// One row of `GET /v1/benchmarks` (`benchmarks/definition.py` `catalog_entry`). The catalog says
// nothing about judges or web search; Studio's `benchmark-presentation.ts` fills that gap.
export type BenchmarkSummary = {
  object?: "benchmark";
  id: string;
  title: string;
  description: string;
  revision: string;
  case_count: number;
  origin: string;
  focus?: string;
  difficulty: string;
  interaction: string;
  failure_policy: string;
  dataset_url?: string;
  href: string;
};
