#!/usr/bin/env bash
# Re-runs every command cited in REPORT.md and records its exit code.
FM=/Users/junior/workspace/screamingface/.claude/skills/formal-modeling/bin/fm.py
SP=$(cd "$(dirname "$0")" && pwd); cd "$SP"
run() { "$@" > /dev/null 2>&1; echo "exit=$?  $*" | sed "s#$FM#\$FM#; s#$SP/##g"; }
run python3 $FM check model_lifecycle.py --keep-going
run python3 $FM check model_lifecycle.py -D LOST_RESPONSE=0 -D CANCELS=0 --keep-going
run python3 $FM check model_lifecycle.py -D LOST_RESPONSE=0 -D FAULTS=0 --keep-going
run python3 $FM check model_lifecycle.py -D TERM_PATH_RELIABLE=1 -D LOST_RESPONSE=0 --keep-going
run python3 $FM check model_lifecycle.py -D TERM_PATH_RELIABLE=1 -D DEADLINE_SET=0 --keep-going
run python3 $FM check model_lifecycle.py -D MAX_TEL=3 -D FAULTS=3 -D CANCELS=2 --keep-going
run python3 $FM check model_lifecycle.py -D SEQ_COMMIT=1 -D FIX=3 -D TERM_PATH_RELIABLE=1 -D LOST_RESPONSE=1 --keep-going
for fx in 0 1 2 3; do run python3 $FM check model_lifecycle.py -D FIX=$fx -D LOST_RESPONSE=0 --keep-going; done
run python3 $FM check model_lifecycle_fix3_safety.py
run python3 $FM check model_lifecycle_fix3_safety.py -D MAX_TEL=3 -D FAULTS=3 -D CANCELS=2
run python3 $FM check model_lifecycle_fix3_safety.py --challenge
run python3 $FM mutate model_lifecycle_fix3_safety.py
run python3 $FM check model_lifecycle_fix3_live.py
run python3 $FM check model_lifecycle_fix3_live.py -D MAX_TEL=3 -D FAULTS=3 -D CANCELS=2
run python3 $FM check model_lifecycle_fix3_live.py --challenge
run python3 $FM mutate model_lifecycle_fix3_live.py
run python3 $FM check model_lifecycle_fix3_commit.py
run python3 $FM check model_lifecycle_fix3_commit.py --challenge
run python3 $FM mutate model_lifecycle_fix3_commit.py
run python3 $FM compare model_lifecycle.py model_lifecycle_fix3_safety.py model_lifecycle_fix3_live.py model_lifecycle_fix3_commit.py
run python3 $FM check model_jobstatus_inprocess.py --keep-going
run python3 $FM check model_jobstatus_queue.py --keep-going
run python3 $FM check model_jobstatus_queue.py --challenge
run python3 $FM check model_jobstatus_queue_spec2.py
run python3 $FM mutate model_jobstatus_queue_spec2.py
