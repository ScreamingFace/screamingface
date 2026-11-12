# Check external result sources

An availability check never changes a score, its rank, comparison evidence, or edit history. If the source cannot be reached, the row keeps its **Source ↗** button and shows **Source unchecked**, followed by the last successful availability date. If there has never been a successful check, it says so. A later successful check removes the notice.

This checks whether the page responds, not whether it still contains the cited score. A timeout, HTTP 403/429, or failed TLS connection does not prove a page was deleted. All unsuccessful checks use the neutral unchecked state.

## Run a check

Use the deployed Scoreboard image and its existing database configuration. Apply migration `0024_external_source_health` before starting the new application or this command; the existing Helm migration hook handles the schema. This change follows the edit-history migration from #1731.

```sh
python -m scoreboard.check_sources --benchmark-id inspect-sad_facts_llms
```

Run it after importing results, and repeat when checking source availability. It checks each distinct non-empty source URL on that board once, including currently unranked results. It prints counts only. An unknown board is an error; an empty board is a successful no-op. An unavailable source is a recorded outcome, not a command failure. Database failures still fail the command.

**There is no automatic schedule in this change.** Deployment owners can invoke this command periodically for the selected boards. Until a first check runs, existing rows have no availability claim or notice. Recurring scheduling and live execution require a deployment step; merely deploying the UI does not check any URLs.

## What is stored

The read API adds `source_health`, either null or an object with:

- `available`: whether the latest attempt received a successful HTTP response.
- `checked_at`: the UTC start time of that attempt.
- `last_available_at`: the most recent successful attempt's start time, or null.

These dates describe URL availability. They are separate from `observed_at`, the date someone read the source's score. The portal displays the last available calendar date in UTC.

Identical URLs share the same state, stored separately from score observations. A changed source URL looks up its own state; it never inherits the previous URL's failure. Overlapping checks retain the latest attempt and most recent success even when they finish out of order. The current implementation uses exact URL identity, including fragments.

## Network boundaries

Only public HTTP(S) destinations on ports 80/443 are contacted. DNS answers are checked before connecting, and the connection is pinned to a checked IP while retaining the original HTTP Host and TLS hostname. If a connection fails, the checker tries the remaining validated addresses within the same deadline, retaining the original HTTP Host and TLS identity. HTTP error responses and read failures do not trigger retries. Redirects receive the same validation. Credentials in URLs, private/local addresses, environment proxies, and other schemes/ports are refused. Azure’s [platform service address](https://learn.microsoft.com/en-us/azure/virtual-network/what-is-ip-address-168-63-129-16) is also explicitly refused, including its IPv4-mapped IPv6 form.

Each URL has a 15-second overall deadline and at most five redirects, with a five-second per-request timeout. System DNS runs in a short-lived isolated Python process, which is killed and reaped on timeout or cancellation; it cannot leave a blocking resolver thread delaying command shutdown. Numeric IPs need no resolver process. GET responses are streamed and closed after headers; page and redirect bodies are not downloaded. No HTTP requests run during leaderboard page reads. Response bodies, redirect locations, and exception details are not stored or exposed.

## Acceptance check after deployment

1. Import a qualifying result, then check its reachable public source. Confirm the normal Source button and a successful API status.
2. In a disposable dev fixture, check a public URL returning 404. Confirm the result and rank remain, with an unchecked notice and no fabricated last-success date.
3. Use a controlled public source that first returns 200, then fails, then recovers. Confirm the last-success date survives failure and advances on recovery; the notice clears.
4. Change the fixture's source URL and check that it does not inherit the old source state. Confirm no source check creates a score-history version.

Local preview failures are simulated. They do not describe the availability of the actual published SAD source.
