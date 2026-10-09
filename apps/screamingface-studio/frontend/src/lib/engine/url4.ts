// url4 text helpers Studio needs to address the Engine exactly as the SDK does.

// A url4 Text literal. Mirrors `url4/core/render.py` `_quote`: backslashes first, then quotes,
// so an escaped quote's own backslash is not escaped twice.
export function quoteText(text: string): string {
  return `'${text.replaceAll("\\", "\\\\").replaceAll("'", "\\'")}'`;
}

// Bind one canonical Candidate into one Benchmark expression (spec D4), byte-identical to the
// SDK's `link_candidate` (`screamingface/_evaluation/linking.py`) for canonical inputs: the
// Benchmark is the Engine's own rendered url4, and the Candidate is `recipeToUrl4`'s output.
export function linkCandidate(candidateUrl4: string, benchmarkUrl4: string): string {
  return `(candidate:0.0:${quoteText(candidateUrl4)}, ${benchmarkUrl4})!''`;
}
