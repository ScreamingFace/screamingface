# Implementation plan — OME-1557 review fixes

1. Add failing URL4 nested-reference and SDK composition/export/replay regressions.
2. Preserve outer reference frames in nested AST Expression lowering.
3. Detect executable fusion policy before deciding to skip canonical validation.
4. Add Engine request-content regressions through the existing FrontierScience fixture.
5. Run focused regressions, original scratch probes, and all three stack gate runners.
6. Record outcomes, commit, and push to `codex/ome-1557-fusion-quorum`.
