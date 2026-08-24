---
id: OME-971
linear_url: https://linear.app/openmined/issue/OME-971/onboard-the-gdpval-text-subset-as-a-rubric-graded-benchmark
status: in_progress
type: feature
priority: medium
labels: [url4-cloud, agentic, autonomous]
created: 2026-08-24
closed:
---

# Onboard the GDPval text subset as a rubric-graded benchmark

Register the prose-only slice of the GDPval gold set (102 tasks after excluding 7 with
unusable references) as an Engine-owned benchmark graded per rubric item on the
`healthbench-worst30` pattern. No code execution, no sandbox, no artifact handling —
those are later phases. Blocked at scale by the 1 MiB candidate-result truncation defect.
