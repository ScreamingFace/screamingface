# Native index integration for case attribution

Approved goal: remove the selector endpoint by using URL4 native `$index` in #988.

The candidate envelope carries zero-based `case_index` and an explicit `case_count`.
The candidate adapter converts the index to the existing one-based event position.
Model input and Case ID semantics remain unchanged. Native iteration.slice selects the
requested prefix and native index identifies its stable position.

The former selector validates JSON-array shape, selected-row object shape, and sufficient
actual rows before any candidate execution. This must remain true. Proposed design:
validate at the existing cases handler, with the selected count supplied to it, then use
native slicing over the returned array. The owner approved this boundary change.

No new URL4 capability, extra route, model-role attribution or Client UI change.

The cases route becomes an intent processor (`/cases()!'N'`) rather than a bare data
provider. The count intent validates the requested prefix; native slicing performs selection.
This is an explicit Engine protocol change, with no compatibility route or synthetic fields.
