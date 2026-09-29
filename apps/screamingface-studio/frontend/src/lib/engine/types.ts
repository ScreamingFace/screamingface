// Wire shapes of the SF Engine's provider-connection and catalog routes
// (`screamingface_engine/rest/connections.py`, `rest/catalog.py`). Only the fields Studio reads.

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
