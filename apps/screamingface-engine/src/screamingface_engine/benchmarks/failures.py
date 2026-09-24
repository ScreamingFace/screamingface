"""Engine-owned failure types retained by URL4's existing collected error kind."""

from url4.core.errors import ResolutionError


class CandidateExecutionError(ResolutionError):
    """A URL4 failure escaping the execution of a benchmark's candidate recipe.

    INVARIANT: URL4 serializes this class name as error.kind. Keep the name stable;
    benchmark aggregation uses it as boundary evidence, independently of error codes.
    """
