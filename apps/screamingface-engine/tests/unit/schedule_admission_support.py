"""Shared fixture for the schedule-time admission tests (OME-878 follow-up).

A plain module, not a test module: both `test_schedule_time_admission*.py` files import it, and
neither may import the other (the REST one must fail on behaviour, not on an import, before the
fix lands).
"""

# The published FrontierScience leaderboard url4 for claude-opus-5.5, verbatim (the url4 the
# failing replay scheduled). WHY verbatim and not a hand-built miniature: the model is named ONLY
# inside the inert `candidate` text literal that `benchmarks/definition.py::link_candidate`
# embeds — a shape a hand-built url4 would be tempted to simplify away.
PUBLISHED_OPUS_URL4 = r"""(candidate:0.0:'(model_1:0.0:/openrouter/anthropic/claude-opus-5.5?max_tokens=128000&reasoning_effort=high&q=($input)!\'Answer the request accurately and completely. Follow every instruction and formatting constraint in the request.\', _sf_recipe:0.0:\'{"recipe":{"binding":"model_1","kind":"model","name":"claude-opus-5.5","named":false,"role":"model"},"schema":"screamingface.recipe.v1"}\')!\'$model_1\'', (case_evaluations:0.0:(selected_case_evaluations:0.0:/benchmarks/inspect-frontierscience/fb33b1e6a2cf0c12/cases()!'160'*(evaluated:0.0:(preserved_case:0.0:(candidate_invocation:0.0:(candidate_invocation:0.0:/benchmarks/candidate?web_search=false&context_format=case-v1&q=({input: '$item.input', case_id: '$item.id', case_index: '$index', case_count: '160'})!'$candidate')!'$candidate_invocation', protected_grading:0.0:({candidate_invocation: '$candidate_invocation', case_id: '$item.id'})*(grading:0.0:(record:0.0:/benchmarks/inspect-frontierscience/fb33b1e6a2cf0c12/check($candidate_invocation)!'$item.case_id', case_evaluation:0.0:/benchmarks/inspect-frontierscience/fb33b1e6a2cf0c12/case-evaluation({attempt_1: '$record'})!'$item.case_id')!'$case_evaluation')!'$grading', case_execution:0.0:/benchmarks/case-execution({case_id: '$item.id', candidate_invocation: '$candidate_invocation', grading: '$protected_grading'})!'')!'$case_execution')!'$preserved_case')!'$evaluated';iteration.concurrency=1;iteration.slice=0:160)!'$selected_case_evaluations', result:0.0:/benchmarks/inspect-frontierscience/fb33b1e6a2cf0c12/aggregate($case_evaluations)!'aggregate:160')!'$result')!''"""  # noqa: E501
