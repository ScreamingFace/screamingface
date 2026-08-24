"use client";

/**
 * The job list, with polling.
 *
 * WHY a client component at all: a load takes seconds-to-minutes, and the honest UI is the one
 * that shows the job moving through its states without the operator pressing refresh. Polling
 * runs only while a job is non-terminal — a quiet console costs nothing.
 *
 * WHY through a server action (`refresh` prop) rather than fetching the gateway directly: the
 * same rule as every other read — the gateway's address and the identity header never cross to
 * the browser.
 */

import { useEffect, useState } from "react";

import { Badge, EmptyState, Table, TBody, TD, TH, THead, TR } from "@/components/ui";

import type { AdminCacheJob } from "@/lib/aigateway/client";

const POLL_MILLIS = 2000;
const TERMINAL = new Set(["complete", "failed", "refused"]);

function toneFor(state: AdminCacheJob["state"]): "good" | "bad" | "neutral" {
  if (state === "complete") return "good";
  if (state === "failed" || state === "refused") return "bad";
  return "neutral";
}

function describeCounters(job: AdminCacheJob): string {
  if (job.state === "refused" || job.state === "failed") return "—";
  if (job.mode === "merge" && job.inserted_rows !== null && job.updated_rows !== null) {
    return `${job.staged_rows} staged · ${job.inserted_rows} inserted · ${job.updated_rows} replaced`;
  }
  if (job.staged_rows !== null && job.live_before !== null && job.live_after !== null) {
    return `${job.staged_rows} staged · ${job.live_before} → ${job.live_after} rows`;
  }
  return "—";
}

export type JobsPanelProps = {
  initialJobs: AdminCacheJob[];
  refresh: () => Promise<AdminCacheJob[]>;
};

export function JobsPanel({ initialJobs, refresh }: JobsPanelProps) {
  const [jobs, setJobs] = useState(initialJobs);

  const active = jobs.some((job) => !TERMINAL.has(job.state));

  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => {
      refresh()
        .then(setJobs)
        .catch(() => {
          /* A missed poll is a stale list, not a broken page; the next tick retries. */
        });
    }, POLL_MILLIS);
    return () => clearInterval(timer);
  }, [active, refresh]);

  if (jobs.length === 0) {
    return (
      <EmptyState
        title="No loads yet"
        message="Upload a snapshot above; the job it starts will be listed here."
      />
    );
  }

  return (
    <div className="ui-table-scroll">
      <Table>
        <THead>
          <TR>
            <TH scope="col">Started</TH>
            <TH scope="col">Actor</TH>
            <TH scope="col">Mode</TH>
            <TH scope="col">State</TH>
            <TH scope="col">Rows</TH>
            <TH scope="col">Detail</TH>
          </TR>
        </THead>
        <TBody>
          {jobs.map((job) => (
            <TR key={job.id}>
              <TD>{new Date(job.created_at).toLocaleString()}</TD>
              <TD>{job.actor}</TD>
              <TD>{job.mode}</TD>
              <TD>
                <Badge tone={toneFor(job.state)}>{job.state}</Badge>
              </TD>
              <TD>{describeCounters(job)}</TD>
              <TD>
                {job.refusal ? <span className="cache-refusal">{job.refusal}</span> : null}
                {job.forced ? <span className="cache-warning">revision override</span> : null}
                {(job.warnings ?? []).map((warning) => (
                  <span key={warning} className="cache-warning">
                    {warning}
                  </span>
                ))}
                {job.error ? <span className="cache-refusal">{job.error}</span> : null}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
