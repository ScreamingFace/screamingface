# Rich notebook repr for `sf.credits()` — OME-1935

## Behavior

A `CreditStatus` displayed in a notebook renders a static card. It is the same card the
connection panel shows, so the two never disagree:

- **BYOK:** account balance first and largest; key allowance beside it; the note "Key
  allowance is a spending cap, not additional credit."
- **Hosted:** one "Hosted allowance". The platform account balance is never shown.
- **Per amount:** the USD value, "No key limit" for `unlimited`, the stale note with the
  last known value for `stale`, and "Checked YYYY-MM-DD HH:MM UTC" when `as_of` is set.
- **Unavailable amounts** say why, in short factual words: `not_connected` → "Not
  connected", `credential_rejected` → "Key rejected", `lookup_failed` → "Lookup failed",
  `unsupported` → "Not supported", `invalid_response` → "Unreadable response".
  `hosted_unavailable` → "Not available on hosted" (the Engine reports it with no job
  identity, or for a hosted key with no per-key limit).
  `management_key_required` and `account_unverified` keep their current notes.
  On the account box only, `credential_rejected` reads "Management key rejected" when the key
  allowance was not itself rejected: the account amount then comes from the management key,
  so "Key rejected" there would read as the execution key failing (OME-1968). When the
  execution key is rejected, the Gateway rejects both amounts and both boxes read "Key
  rejected" (review of PR #1942).
- **Failed request:** when the credit request itself fails, every amount, hosted included,
  is `lookup_failed`, so a hosted panel says "Lookup failed" (OME-1968).
- **Shared with the panel:** the labels live in the one renderer the connection panel
  and the card both use, so the panel gains them too and the two always agree.
- **Nothing known** (every amount unavailable and no hosted marker, e.g. the SDK's
  failed-lookup result): one neutral "Credits unavailable" box with the reason, instead
  of two empty BYOK boxes. The card cannot know whether the caller is hosted, so it does
  not guess. Any known amount keeps the normal layout: account "Lookup failed" next to a
  $12.40 key allowance stays two boxes. The neutral box shows the account's note when it
  is one the user can act on ("Add a management key…", "Account association could not
  be verified."), otherwise the key's reason.

The card is a snapshot. It does not refresh; calling `sf.credits()` again does. It carries
no snapshot hint; the "Checked … UTC" stamp dates it. The plain `repr()` and the dataclass
fields are unchanged.

## Rendering constraints

- The card root carries the shared `sf-ui` theme class, so the `--sf-*` tokens from
  `_ui/style.py` apply outside the connection panel, in light and dark.
- The root carries both no-maths classes (`NO_MATH`, OME-1226). Amounts contain `$`,
  which MathJax would otherwise typeset.
- No new dependency. `credit.py` imports the renderer from `_ui` inside `_repr_html_`,
  like `ModelDetails` does.

## Out of scope

A live, auto-refreshing card; management-key controls; any change to the connection
panel beyond the shared reason labels; any change to the credit wire contract.
