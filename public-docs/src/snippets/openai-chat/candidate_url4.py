from url4 import Expression, Source, Text, build


def candidate_url4(evaluation_url4: str) -> str:
    """Return the Candidate URL4 inside an evaluation URL4."""
    root = build(evaluation_url4)
    if isinstance(root, Expression):
        for source in root.sources:
            is_candidate = isinstance(source, Source) and source.name == "candidate"
            if is_candidate and isinstance(source.value, Text):
                return source.value.value
    raise ValueError("this text is not an evaluation URL4")
