# Email draft — LANL researcher onboarding

**From:** Irina Bejan &lt;irina@openmined.org&gt;
**To:** [LANL research team]
**Subject:** ScreamingFace materials — BYOK guide + platform walkthrough for IF-Eval

---

Hi,

Following up on our conversation and the quick demo — I've put together two notebooks that
should give you everything you need to run your own IF-Eval experiments in ScreamingFace
and understand how it works under the hood.

**Your Ens-1 setup maps directly to the library.** The `gemini-3.1-flash` judge +
`gpt-5.4-mini` / `gemini-3.1-flash` members configuration from the tokenomics paper is
natively expressible as `sf.CorrectiveLoop(members=[...], judge=..., max_rounds=3)`. I've
included a code block in the BYOK notebook showing exactly how to write it, alongside the
simpler building blocks it composes from.

**Two notebooks, pick your starting point:**

1. **`ScreamingFace_BYOK_Guide.ipynb`** — recommended starting point. Runs a local engine
   inside the Colab VM using your own API keys (OpenRouter, OpenAI direct, Anthropic
   direct, or Hugging Face). No Google login required, which matters if your institutional
   email doesn't work with Google Workspace auth. The notebook covers:
   - How IF-Eval is implemented: the 541-case vendored verifier, the SHA-256 revision hash
     that pins dataset + verifier + protocol together, and why the grading is free
     (deterministic, no model calls)
   - The caching layer — request-level deduplication and what it means for measuring actual
     tokenomics costs (cache_read_tokens vs input_tokens, and the cost_usd accounting)
   - The three recipe primitives (Solo, Fusion, Pipeline) and a conceptual walkthrough of
     how CorrectiveLoop and SelfCorrective compose from them
   - URL4 — the compiled expression that pins a recipe for exact reproducibility
   - For Gemini models: use OpenRouter (option A in the notebook); GPT and Claude are also
     available directly through their respective APIs

2. **`ScreamingFace_Platform.ipynb`** — shorter, zero-setup path. Uses a hosted engine
   with shared OpenRouter credits. Requires a Google account for Cloudflare Access login;
   if that's a blocker, the BYOK notebook is the alternative.

**One note on model families:** the hosted engine and OpenRouter path give access to the
full OpenRouter catalog. If you need to restrict to specific providers or avoid certain
model families, the BYOK path with direct OpenAI or Anthropic keys is straightforward —
both are shown in the BYOK notebook.

Happy to jump on a call to walk through anything or help set up a specific experimental
configuration. And if there are aspects of the architecture you'd like to dig into further
— the ensemble protocol, the verifier integration, the URL4 compilation — just let me know.

Looking forward to seeing what you build with it.

Best,
Irina

---

_[Attach or link both notebooks]_
