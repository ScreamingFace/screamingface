/**
 * The cache page is an async Server Component, so — exactly like the accounts page — it is
 * invoked as the async function it is and the returned tree is rendered as ordinary sync React.
 * These tests hold the page's decisions: the live info panel, the upload form and the job list
 * appear together on success, and a gateway refusal replaces the whole working surface.
 */

import { render, screen } from "@testing-library/react";

vi.mock("server-only", () => ({}));

const cacheInfo = vi.fn();
const listCacheJobs = vi.fn();

// Spread the real module so `AdminApiError` keeps ONE identity — `describeFailure` narrows with
// `instanceof`, and a second copy of the class would make every refusal look like a bug.
vi.mock("@/lib/aigateway/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/aigateway/client")>();
  return {
    ...actual,
    cacheInfo: (...args: unknown[]) => cacheInfo(...args),
    listCacheJobs: (...args: unknown[]) => listCacheJobs(...args),
  };
});

// The page imports the server actions only to hand them to the form and the panel as props, so
// stand-in functions are all the page needs to render.
vi.mock("../actions", () => ({
  uploadCacheSnapshotAction: vi.fn(async () => ({ ok: true })),
  listCacheJobsAction: vi.fn(async () => []),
}));

const { AdminApiError } = await import("@/lib/aigateway/client");
const { default: Page } = await import("./page");

function completedJob() {
  return {
    id: "j1",
    state: "complete",
    mode: "merge",
    actor: "admin@openmined.org",
    created_at: "2026-08-24T00:00:00Z",
    finished_at: "2026-08-24T00:00:05Z",
    staged_rows: 1,
    live_before: 0,
    live_after: 1,
    inserted_rows: 1,
    updated_rows: 0,
    manifest_present: true,
    forced: false,
    warnings: [],
    refusal: null,
    error: null,
  };
}

/** Invoke the Server Component and render what it returned. */
async function renderPage() {
  const element = await Page();
  render(element);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("the response cache page", () => {
  it("shows the live info, the upload form and the job list on success", async () => {
    cacheInfo.mockResolvedValue({
      serving: true,
      row_count: 204765,
      revisions: { parameter_contract: "aigw-parameter-contract-2026-08b" },
    });
    listCacheJobs.mockResolvedValue([completedJob()]);

    await renderPage();

    expect(screen.getByText("Response cache")).toBeInTheDocument();
    expect(screen.getAllByText("serving").length).toBeGreaterThan(0);
    expect(screen.getByText("204,765")).toBeInTheDocument();
    expect(screen.getByText("aigw-parameter-contract-2026-08b")).toBeInTheDocument();
    expect(screen.getByText("Upload snapshot")).toBeInTheDocument();
    expect(screen.getByText("Load history")).toBeInTheDocument();
  });

  it("replaces the working surface with the refusal when the gateway refuses", async () => {
    cacheInfo.mockRejectedValue(new AdminApiError("forbidden", 403, "not an admin"));
    listCacheJobs.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByText("Not an administrator")).toBeInTheDocument();
    expect(screen.queryByText("Upload snapshot")).not.toBeInTheDocument();
  });

  it("offers a retry when the failure is retryable", async () => {
    cacheInfo.mockRejectedValue(new AdminApiError("conflict", 409, "busy"));
    listCacheJobs.mockResolvedValue([]);

    await renderPage();

    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
