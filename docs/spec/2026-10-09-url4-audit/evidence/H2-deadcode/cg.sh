#!/bin/bash
# usage: cg.sh PATTERN  -> consumers outside url4 src (excluding node_modules/.venv)
cd /Users/junior/workspace/screamingface
grep -rnE "$1" apps packages/screamingface packages/screamingface-* url4_playground.py packages/url4/tests packages/url4/examples --include=*.py --include=*.ipynb --include=*.toml --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.git 2>/dev/null | cut -c1-170 | head -${2:-10}
