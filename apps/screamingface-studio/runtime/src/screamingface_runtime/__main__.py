"""Frozen-executable and ``python -m screamingface_runtime`` entry point."""

import multiprocessing

from screamingface_runtime.cli import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
