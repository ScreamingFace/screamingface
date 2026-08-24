"use client";

/**
 * The snapshot upload form. A Client Component for `useActionState` and for the one piece of
 * state the gateway cannot hold for us: whether the operator has chosen REPLACE, which is the
 * only mode that can destroy data and therefore the only one that must show the loss
 * acknowledgement.
 *
 * INVARIANT: the action arrives as a PROP (same rule as every form here — this file's module
 * graph must not reach the server-only client library).
 */

import { useActionState, useState } from "react";

import { Button, Field, Input, Notice, Select } from "@/components/ui";

import type { ActionState, FormState } from "../actions";

export type UploadFormProps = {
  action: (state: FormState, formData: FormData) => Promise<ActionState>;
};

export function UploadForm({ action }: UploadFormProps) {
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [state, submit, pending] = useActionState<FormState, FormData>(action, null);

  const failed = state !== null && !state.ok;
  const formError = failed && state.field !== "snapshot" ? state.error : undefined;
  const fileError = failed && state.field === "snapshot" ? state.error : undefined;

  return (
    <form action={submit} className="cache-upload">
      {state?.ok ? (
        <Notice tone="success" className="cache-upload-notice">
          Upload accepted. The load job appears below — poll it there.
        </Notice>
      ) : null}
      {formError ? (
        <Notice tone="error" title="The gateway refused that upload" className="cache-upload-notice">
          {formError}
        </Notice>
      ) : null}

      <div className="cache-upload-row">
        <Field
          label="Load mode"
          hint="Merge replaces matching keys and keeps everything else. Replace swaps the whole table's contents."
        >
          <Select
            name="mode"
            value={mode}
            onChange={(event) => setMode(event.target.value as "merge" | "replace")}
          >
            <option value="merge">merge (create-or-replace)</option>
            <option value="replace">replace (wholesale)</option>
          </Select>
        </Field>

        <Field
          label="Snapshot archive"
          hint="The .sql.gz that snapshot-cache wrote. A manifest beside it lets the gateway verify it."
          error={fileError}
        >
          <Input name="snapshot" type="file" required accept=".gz,.sql,application/gzip" />
        </Field>

        <Field label="Manifest (optional)" hint="The .manifest.json emitted beside the archive.">
          <Input name="manifest" type="file" accept=".json,application/json" />
        </Field>
      </div>

      {mode === "replace" ? (
        <Field
          label="I understand rows newer than the snapshot will be destroyed"
          hint="Required for replace when the live table holds more rows than the snapshot carries."
        >
          <input
            className="cache-check"
            type="checkbox"
            name="acknowledge_loss"
            value="on"
          />
        </Field>
      ) : null}

      <Field
        label="Load despite a revision mismatch"
        hint="Only for a snapshot the revision guard refuses. The override is recorded on the job."
      >
        <input className="cache-check" type="checkbox" name="force" value="on" />
      </Field>

      <div className="cache-upload-actions">
        <Button type="submit" disabled={pending}>
          {pending ? "Uploading…" : "Upload snapshot"}
        </Button>
      </div>
    </form>
  );
}
