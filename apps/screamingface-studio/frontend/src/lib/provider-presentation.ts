// How Studio *presents* a provider. The Engine decides which providers exist, their names and
// how they sign in (`GET /v1/connections`); it carries no category, so the grouping, blurb and
// accent color live here. A provider missing from the table still shows, under "Other".

export type ProviderGroup = "Local & Sessions" | "Providers" | "Hubs" | "Other";

export type ProviderPresentation = {
  group: ProviderGroup;
  description: string;
  color: string;
};

export const GROUP_ORDER: ProviderGroup[] = [
  "Local & Sessions",
  "Providers",
  "Hubs",
  "Other",
];

export const FALLBACK_PROVIDER_COLOR = "#8a8f98";

const PRESENTATION: Record<string, ProviderPresentation> = {
  ollama: {
    group: "Local & Sessions",
    description: "Local models on your machine, no API key",
    color: "#52aec5",
  },
  anthropic: {
    group: "Local & Sessions",
    description: "Claude subscription sign-in or API key",
    color: "#ca492c",
  },
  codex: {
    group: "Local & Sessions",
    description: "ChatGPT / Codex subscription sign-in",
    color: "#256b24",
  },
  "gemini-cli": {
    group: "Local & Sessions",
    description: "Google sign-in or Gemini API key",
    color: "#4392c5",
  },
  antigravity: {
    group: "Local & Sessions",
    description: "Antigravity sign-in",
    color: "#6976ae",
  },
  openai: {
    group: "Providers",
    description: "GPT and o-series models",
    color: "#53bea9",
  },
  huggingface: {
    group: "Hubs",
    description: "Serverless open-source inference",
    color: "#f79763",
  },
  openrouter: {
    group: "Hubs",
    description: "300+ models behind one API key",
    color: "#937098",
  },
};

export function providerPresentation(id: string): ProviderPresentation {
  return (
    PRESENTATION[id] ?? {
      group: "Other",
      description: "",
      color: FALLBACK_PROVIDER_COLOR,
    }
  );
}
