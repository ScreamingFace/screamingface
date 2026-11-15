# OME-1851 implementation plan

1. Add independent VM tests simulating page reloads sharing session storage; confirm failures.
2. Restore the checkbox on initialization and save from checkbox changes, catching storage exceptions locally.
3. Run the scoreboard gates and inspect desktop/mobile previews in light and dark themes.
4. Remove the include-unscored button and update its previous tests to use the checkbox, per the owner's explicit follow-up. Verify search is retained and the preference survives reload.
5. Record evidence and prepare the focused PR.

Owner follow-up: remove the separate search-clear button and its handler. Update the
existing clear regression to exercise an empty input event; verify the native × in Chrome.
