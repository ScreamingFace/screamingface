import {
  FALLBACK_PROVIDER_COLOR,
  GROUP_ORDER,
  providerPresentation,
} from "./provider-presentation";

describe("providerPresentation", () => {
  it.each([
    ["ollama", "Local & Sessions"],
    ["anthropic", "Local & Sessions"],
    ["codex", "Local & Sessions"],
    ["gemini-cli", "Local & Sessions"],
    ["antigravity", "Local & Sessions"],
    ["openai", "Providers"],
    ["huggingface", "Hubs"],
    ["openrouter", "Hubs"],
  ])("puts %s in %s", (id, group) => {
    const presentation = providerPresentation(id);
    expect(presentation.group).toBe(group);
    expect(presentation.description).not.toBe("");
    expect(presentation.color).toMatch(/^#[0-9a-f]{6}$/);
  });

  it("puts an unknown provider in Other, with the neutral color and no description", () => {
    expect(providerPresentation("brand-new-provider")).toEqual({
      group: "Other",
      description: "",
      color: FALLBACK_PROVIDER_COLOR,
    });
  });

  it("orders groups with Other last", () => {
    expect(GROUP_ORDER).toEqual([
      "Local & Sessions",
      "Providers",
      "Hubs",
      "Other",
    ]);
  });
});
