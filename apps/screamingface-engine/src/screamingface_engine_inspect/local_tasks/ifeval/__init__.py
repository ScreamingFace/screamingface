"""IFEval as one local Task package: the loader, the vendored checker, the scorer, the task.

The package import runs before any module in it, so the nltk guard below is in place before
the vendored checker imports nltk.
"""

import os

# WHY: nltk>=3.10 installs a CWD import guard (nltk/inisec.py, CWE-427 mitigation) whose
# under-the-cwd check false-positives on in-project virtualenvs — ANY nltk-initiated
# dependency import resolving beneath the project directory (…/.venv/site-packages/…)
# raises ImportError, breaking the vendored verifier. Every execution context here (CI,
# the read-only Runner Job image) runs from a trusted, non-attacker-writable directory,
# so standard Python import semantics are acceptable. setdefault preserves an explicit
# host opt-in; must run before the first `import nltk` anywhere in the process.
os.environ.setdefault("NLTK_DISABLE_IMPORT_SECURITY", "1")
