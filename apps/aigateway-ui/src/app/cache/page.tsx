/**
 * The "Response cache" section: live cache state, the snapshot upload, and the job history.
 *
 * A Server Component for the same reason the accounts page is: `cacheInfo` and `listCacheJobs`
 * run here carrying the mesh-verified identity header, and the browser never learns the
 * gateway's address. Writes go through `uploadCacheSnapshotAction`, handed to the form as a prop.
 */

import { Badge, Button, Notice } from "@/components/ui";
import { cacheInfo, listCacheJobs } from "@/lib/aigateway/client";
import type { AdminCacheInfo, AdminCacheJob } from "@/lib/aigateway/client";
import type { AdminGateFailure } from "@/lib/auth";
import { describeFailure } from "@/lib/auth";

import { listCacheJobsAction, uploadCacheSnapshotAction } from "../actions";
import { JobsPanel } from "./jobs-panel";
import { UploadForm } from "./upload-form";

export default async function Page() {
  let info: AdminCacheInfo | null = null;
  let jobs: AdminCacheJob[] = [];
  let failure: AdminGateFailure | null = null;

  try {
    info = await cacheInfo();
    jobs = await listCacheJobs();
  } catch (error) {
    // `describeFailure` RETHROWS anything that is not an AdminApiError, so a genuine bug still
    // reaches the error boundary instead of being flattened into a tidy sentence.
    failure = describeFailure(error);
  }

  return (
    <main className="page">
      <p className="eyebrow">OpenMined · ScreamingFace</p>
      <h1 className="page-title">Response cache</h1>
      <p className="lede">
        The gateway serves identical requests from one global cache. A snapshot — the archive
        <code className="cache-code">snapshot-cache</code> writes — can be loaded here, either
        merging into the live table or replacing its contents.
      </p>

      {failure ? (
        <Notice tone="error" title={failure.title} className="cache-failure">
          {failure.message}
          {failure.retryable ? (
            <form method="get" action="/cache" className="cache-retry">
              <Button type="submit" variant="ghost">
                Try again
              </Button>
            </form>
          ) : null}
        </Notice>
      ) : info ? (
        <>
          <div className="cache-info">
            <div>
              <span className="cache-info-label">serving</span>
              <Badge tone={info.serving ? "good" : "bad"}>
                {info.serving ? "serving" : "bypassed"}
              </Badge>
            </div>
            <div>
              <span className="cache-info-label">cached responses</span>
              <span className="cache-info-value">{info.row_count.toLocaleString()}</span>
            </div>
            <div>
              <span className="cache-info-label">key revisions</span>
              <span className="cache-info-value cache-info-revisions">
                {Object.entries(info.revisions).map(([name, revision]) => (
                  <span key={name}>
                    <span className="cache-info-key">{name}</span> {revision}
                  </span>
                ))}
              </span>
            </div>
          </div>

          <UploadForm action={uploadCacheSnapshotAction} />

          <h2 className="cache-jobs-title">Load history</h2>
          <JobsPanel initialJobs={jobs} refresh={listCacheJobsAction} />
        </>
      ) : null}
    </main>
  );
}
