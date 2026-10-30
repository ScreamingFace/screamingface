# Benchmark picker Escape behavior — OME-1762

The open benchmark picker closes when Escape is pressed on its trigger, search
input or any result link, including results rebuilt after filtering. Closing
hides the panel, sets aria-expanded=false, and restores focus to the trigger.

Tab continues moving focus normally. Enter continues following result links.
Outside clicks and focus leaving the control still dismiss it. Other keys do not
close it or have their default behavior canceled. Search contents and filtering
are unchanged; OME-1761 is a separate PR.
