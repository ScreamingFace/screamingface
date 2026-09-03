/**
 * The job list's half of the OME-953 contract: the empty state, the per-state badge tone, the
 * merge/replace counter sentences, the refusal/override/warning/error detail column, and the
 * polling rule — a timer runs only while some job is non-terminal.
 */

import { act, render, screen } from "@testing-library/react";

import { JobsPanel } from "./jobs-panel";
import type { AdminCacheJob } from "@/lib/aigateway/client";

function job(overrides: Partial<AdminCacheJob> = {}): AdminCacheJob {
  return {
    id: "j1",
    state: "complete",
    mode: "merge",
    actor: "admin@openmined.org",
    created_at: "2026-08-24T00:00:00Z",
    finished_at: "2026-08-24T00:00:05Z",
    staged_rows: 10,
    live_before: 5,
    live_after: 10,
    inserted_rows: 5,
    updated_rows: 5,
    manifest_present: true,
    forced: false,
    warnings: [],
    refusal: null,
    error: null,
    ...overrides,
  };
}

describe("the cache jobs panel", () => {
  it("shows the empty state when there are no loads", () => {
    render(<JobsPanel initialJobs={[]} refresh={vi.fn()} />);

    expect(screen.getByText(/no loads yet/i)).toBeInTheDocument();
  });

  it("renders a merge job with its counter sentence", () => {
    render(<JobsPanel initialJobs={[job()]} refresh={vi.fn()} />);

    expect(screen.getByText("merge")).toBeInTheDocument();
    expect(screen.getByText("10 staged · 5 inserted · 5 replaced")).toBeInTheDocument();
    expect(screen.getByText("complete")).toBeInTheDocument();
  });

  it("renders a replace job with the before → after sentence", () => {
    render(
      <JobsPanel
        initialJobs={[job({ mode: "replace", inserted_rows: null, updated_rows: null })]}
        refresh={vi.fn()}
      />,
    );

    expect(screen.getByText("10 staged · 5 → 10 rows")).toBeInTheDocument();
  });

  it("renders refusal, override, warnings and error in the detail column", () => {
    render(
      <JobsPanel
        initialJobs={[
          job({
            state: "refused",
            refusal: "revision mismatch",
            forced: true,
            warnings: ["revisions_unverified"],
            error: null,
          }),
        ]}
        refresh={vi.fn()}
      />,
    );

    expect(screen.getByText("revision mismatch")).toBeInTheDocument();
    expect(screen.getByText("revision override")).toBeInTheDocument();
    expect(screen.getByText("revisions_unverified")).toBeInTheDocument();
  });

  it("shows the error sentence for a failed job", () => {
    render(
      <JobsPanel initialJobs={[job({ state: "failed", error: "COPY failed" })]} refresh={vi.fn()} />,
    );

    expect(screen.getByText("COPY failed")).toBeInTheDocument();
  });

  it("polls only while a job is non-terminal", () => {
    vi.useFakeTimers();
    const refresh = vi.fn(async () => [job({ state: "validating" })]);
    render(<JobsPanel initialJobs={[job({ state: "validating" })]} refresh={refresh} />);

    act(() => vi.advanceTimersByTime(2000));
    expect(refresh).toHaveBeenCalledTimes(1);

    act(() => vi.advanceTimersByTime(2000));
    expect(refresh).toHaveBeenCalledTimes(2);

    vi.useRealTimers();
  });

  it("does not poll when every job is terminal", () => {
    vi.useFakeTimers();
    const refresh = vi.fn(async () => []);
    render(<JobsPanel initialJobs={[job()]} refresh={refresh} />);

    act(() => vi.advanceTimersByTime(6000));
    expect(refresh).not.toHaveBeenCalled();

    vi.useRealTimers();
  });
});
