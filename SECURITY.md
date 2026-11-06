# Security policy

ScreamingFace runs model calls on people's own API keys, shares a cache across its community, and publishes leaderboard results that only mean something if they can't be faked. We take reports about any of that seriously, and we're grateful to everyone who takes the time to find and report a problem.

## Reporting a vulnerability

**Please don't report security problems in public issues, pull requests, Slack, or social media.**

Report privately through GitHub instead: **[Report a vulnerability](https://github.com/ScreamingFace/screamingface/security/advisories/new)**. Only the maintainers can see your report, and we can work on the fix with you there.

If you don't have a GitHub account, email **security@screamingface.ai**.

### What to include

- The affected component and its version: your `screamingface` client version (`python -c "import screamingface as sf; print(sf.__version__)"`), a container image tag, or a commit.
- Whether you found it on a hosted service we run, or on a local or self-hosted engine.
- Steps to reproduce it, or a proof of concept.
- What an attacker could do with it, and who would be affected.

Use throwaway provider API keys while you test. Never send us real keys, tokens, or anyone else's data. If your report has to include something sensitive, tell us and we'll arrange a safer way to share it.

## Scope

### In scope

This repository and everything built from it: the `screamingface` and `url4` Python packages, the container images and Helm charts we publish, and the hosted services we operate under `screamingface.ai`.

We especially want to hear about:

- **Provider keys and accounts.** Exposure of the provider API keys the AI gateway holds, or any way to use another person's keys, account, or subsidized compute, including impersonating another user to the hosted engine or the AI gateway.
- **Data leaking between users.** Prompts, model outputs, or account details that one user can reach from another, through the shared cache, logs, error reports, or the hosted engine.
- **Cache poisoning.** Making a replay of someone else's url4 string return responses you chose. ScreamingFace results depend on replays being faithful.
- **Leaderboard integrity.** Getting a result onto the leaderboard, or changing one, without it passing verification. Reading benchmark answer keys, rubrics, or judge prompts that are meant to stay inside the engine. Writing candidate answers that manipulate an LLM judge into giving a higher score.
- **Untrusted url4 strings.** Code execution, file access, or unexpected network calls triggered by parsing or replaying a url4 string someone else wrote, or by running the Python that `Url4.to_python()` generates from one.
- **Build and release pipeline.** Ways to tamper with our PyPI releases, published images, or GitHub Actions workflows, or to escape a pull-request preview environment.

### Out of scope

- Jailbreaks, harmful outputs, or poor answers from third-party models. Please report those to the model's provider.
- Vulnerabilities in provider APIs or other third-party services. Report those to the vendor, and tell us too if ScreamingFace makes them worse.
- Denial-of-service attacks, and load or stress testing against hosted services.
- Problems that need an attacker who already controls the victim's machine or engine.
- Insecure configuration of a self-hosted deployment, unless our defaults or docs led to it.
- Automated scanner output without a demonstrated impact.
- Bugs with no security impact, such as a benchmark scoring a correct answer as wrong. Please [open a regular issue](https://github.com/ScreamingFace/screamingface/issues/new/choose) for those.

## Supported versions

ScreamingFace is early, so we fix security problems in the latest release only. Please check that a problem still exists in the latest release before you report it.

| Component | Receives security fixes |
| --- | --- |
| `screamingface` on PyPI | Latest release |
| `url4` on PyPI | Latest release |
| Container images and Helm charts | Latest release of each |
| Hosted services under `screamingface.ai` | The version currently running |

## What happens after you report

1. We'll acknowledge your report within 3 business days.
2. Within 10 business days, we'll tell you whether we've confirmed the problem and how severe we think it is. If we decide it isn't a vulnerability, we'll explain why.
3. We'll keep you updated while we work on a fix, and agree on a disclosure date with you. We aim to release a fix within 90 days of your report, and sooner for serious problems.
4. Once the fix is out, we'll publish a GitHub security advisory, request a CVE where one applies, and credit you unless you'd rather stay anonymous.

Please keep the details private until the fix is released or 90 days have passed, whichever comes first.

## Testing guidelines

- Test against your own engine where you can. `screamingface up` starts one on your machine.
- Use only your own accounts and keys. Don't access, change, or delete other people's data.
- If you come across someone else's data, stop, don't keep a copy, and tell us.
- Don't run load tests against hosted services, and don't use more shared or subsidized compute than a proof of concept needs.
- Don't try social engineering or phishing against the team or the community.

## Safe harbor

We won’t pursue or support legal action against anyone who researches and reports a vulnerability in good faith and in line with this policy. We may still disclose reports where required by law or in response to a lawful request from law enforcement. If a third party takes action against you for activity that complied with this policy, we’ll make it known that you were acting in good faith. If you’re not sure whether something you want to try is allowed, ask us first at security@screamingface.ai.

## Recognition

ScreamingFace doesn't run a paid bug bounty. With your permission, we'll credit you in the security advisory and the release notes for the fix.

## Everything else

For questions and bugs that aren't security problems, [open an issue](https://github.com/ScreamingFace/screamingface/issues/new/choose) or ask in the community [Slack](https://openmined.org/slack/).
