# Benchmark picker Escape implementation — OME-1762

1. Add DOM regressions using the real renderer and bubbling events; demonstrate
   Escape from a result fails on main.
2. Move the input keydown listener to the containing panel so descendant events
   reach the existing handler. Preserve the trigger's listener.
3. Register the test file in local and CI gates.
4. Check native keyboard navigation in Chromium; run the scoreboard gates.
5. Review the diff, record results and open a linked PR.
