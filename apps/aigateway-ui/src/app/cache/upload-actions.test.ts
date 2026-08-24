/**
 * What these tests hold is the upload action's half of the OME-953 contract: the console's own
 * checks run BEFORE the gateway is called (mode, presence, size), a gateway refusal maps to the
 * shared failure shape naming the file control, and a successful upload purges the console.
 * The gateway's own refusals (checksum, revisions, replace guard) are its contract — pinned in
 * aigateway — and arrive here only as an `AdminApiError`, exactly like every other action.
 */

vi.mock("server-only", () => ({}));

const revalidatePath = vi.fn();
vi.mock("next/cache", () => ({ revalidatePath: (...args: unknown[]) => revalidatePath(...args) }));

const uploadCacheSnapshot = vi.fn();
vi.mock("@/lib/aigateway/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/aigateway/client")>();
  return {
    ...actual,
    uploadCacheSnapshot: (...args: unknown[]) => uploadCacheSnapshot(...args),
  };
});

const { AdminApiError } = await import("@/lib/aigateway/client");
const { uploadCacheSnapshotAction } = await import("../actions");

function file(name: string, size: number, type = "application/gzip"): File {
  return new File([new Uint8Array(size)], name, { type });
}

function form(fields: Record<string, string>, files: Record<string, File>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) data.append(key, value);
  for (const [key, value] of Object.entries(files)) data.append(key, value);
  return data;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("uploadCacheSnapshotAction", () => {
  it("accepts an upload and purges the console", async () => {
    uploadCacheSnapshot.mockResolvedValue({ id: "j1", state: "validating" });

    const state = await uploadCacheSnapshotAction(
      null,
      form(
        { mode: "merge", force: "on", acknowledge_loss: "on" },
        { snapshot: file("snap.sql.gz", 1024) },
      ),
    );

    expect(uploadCacheSnapshot).toHaveBeenCalledWith({
      mode: "merge",
      force: true,
      acknowledgeLoss: true,
      snapshot: expect.any(File),
      manifest: null,
    });
    expect(revalidatePath).toHaveBeenCalledWith("/", "layout");
    expect(state).toEqual({ ok: true });
  });

  it("passes the manifest through when attached", async () => {
    uploadCacheSnapshot.mockResolvedValue({ id: "j2", state: "validating" });

    await uploadCacheSnapshotAction(
      null,
      form(
        { mode: "replace" },
        { snapshot: file("snap.sql.gz", 10), manifest: file("snap.manifest.json", 10, "application/json") },
      ),
    );

    expect(uploadCacheSnapshot.mock.calls[0][0].manifest).toBeInstanceOf(File);
    // acknowledge_loss unchecked on the wire: the operator did not confirm a loss.
    expect(uploadCacheSnapshot.mock.calls[0][0].acknowledgeLoss).toBe(false);
  });

  it("refuses an unknown mode before touching the gateway", async () => {
    const state = await uploadCacheSnapshotAction(
      null,
      form({ mode: "append" }, { snapshot: file("s.gz", 10) }),
    );
    expect(state).toEqual({ ok: false, error: "Choose a load mode: merge or replace.", field: "mode" });
    expect(uploadCacheSnapshot).not.toHaveBeenCalled();
  });

  it("refuses a missing or empty archive before touching the gateway", async () => {
    const missing = await uploadCacheSnapshotAction(null, form({ mode: "merge" }, {}));
    expect(missing).toEqual({
      ok: false,
      error: "Attach the snapshot archive (.sql.gz).",
      field: "snapshot",
    });

    const empty = await uploadCacheSnapshotAction(
      null,
      form({ mode: "merge" }, { snapshot: file("s.gz", 0) }),
    );
    expect(empty.ok).toBe(false);
    expect(uploadCacheSnapshot).not.toHaveBeenCalled();
  });

  it("refuses a file far beyond any snapshot size before the upload", async () => {
    const state = await uploadCacheSnapshotAction(
      null,
      form({ mode: "merge" }, { snapshot: file("backup.sql.gz", 600 * 1024 * 1024) }),
    );
    expect(state.ok).toBe(false);
    if (!state.ok) expect(state.field).toBe("snapshot");
    expect(uploadCacheSnapshot).not.toHaveBeenCalled();
  });

  it("maps a gateway refusal to the failure shape naming the file control", async () => {
    uploadCacheSnapshot.mockRejectedValue(
      new AdminApiError("conflict", 409, "one snapshot load runs at a time"),
    );

    const state = await uploadCacheSnapshotAction(
      null,
      form({ mode: "merge" }, { snapshot: file("s.gz", 10) }),
    );

    // `conflict` maps to the console's fixed copy (a lost race is always "try again", and the
    // gateway's sentence would imply this specific race was the only possibility).
    expect(state).toEqual({
      ok: false,
      error: "A concurrent write won. Nothing was lost — try again.",
      field: "snapshot",
      kind: "conflict",
    });
  });
});

export {};
