---
id: OME-1693
linear_url: https://linear.app/openmined/issue/OME-1693/link-the-candidate-as-a-top-level-source-and-count-cases-by-their-case
status: in_review
type: task
priority: medium
labels: [client-sf, agentic, autonomous]
parent: OME-1692
created: 2026-10-20
closed:
---

# Link the Candidate as a top-level source and count Cases by their case-evaluation code

Client half of `OME-1692`: linking inserts the Candidate as the first top-level source (as a url4 literal), recipe readers use `literal_value`, progress counts `case-evaluation` code calls, and a terminal error's `cause` names the failure.
