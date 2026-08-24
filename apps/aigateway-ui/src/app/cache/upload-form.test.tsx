/**
 * The upload form's half of the OME-953 contract: merge is the default and hides the loss
 * acknowledgement, REPLACE is the only mode that reveals it, a gateway refusal lands on the
 * right control (file vs form), and a successful upload shows the "poll the job" notice.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { UploadForm } from "./upload-form";
import type { ActionState, FormState } from "../actions";

function renderForm(
  action = vi.fn(
    async (_state: FormState, _formData: FormData): Promise<ActionState> => ({ ok: true }),
  ),
) {
  render(<UploadForm action={action} />);
  return action;
}

function formElement(): HTMLFormElement {
  const form = screen.getByText("Upload snapshot").closest("form");
  if (!form) throw new Error("upload form not found");
  return form as HTMLFormElement;
}

describe("the cache upload form", () => {
  it("defaults to merge and hides the loss acknowledgement", () => {
    renderForm();

    const select = screen.getByLabelText(/load mode/i) as HTMLSelectElement;
    expect(select.value).toBe("merge");
    expect(
      screen.queryByLabelText(/rows newer than the snapshot will be destroyed/i),
    ).not.toBeInTheDocument();
  });

  it("reveals the loss acknowledgement only while replace is chosen", () => {
    renderForm();

    const select = screen.getByLabelText(/load mode/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "replace" } });
    expect(
      screen.getByLabelText(/rows newer than the snapshot will be destroyed/i),
    ).toBeInTheDocument();

    fireEvent.change(select, { target: { value: "merge" } });
    expect(
      screen.queryByLabelText(/rows newer than the snapshot will be destroyed/i),
    ).not.toBeInTheDocument();
  });

  it("submits the chosen mode and flags to the action", async () => {
    const action = renderForm();

    const select = screen.getByLabelText(/load mode/i) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "replace" } });
    fireEvent.click(screen.getByLabelText(/rows newer than the snapshot will be destroyed/i));
    fireEvent.click(screen.getByLabelText(/load despite a revision mismatch/i));

    fireEvent.submit(formElement());

    await waitFor(() => expect(action).toHaveBeenCalled());
    const formData = action.mock.calls[0][1] as FormData;
    expect(formData.get("mode")).toBe("replace");
    expect(formData.get("acknowledge_loss")).toBe("on");
    expect(formData.get("force")).toBe("on");
  });

  it("shows the success notice once the action accepts the upload", async () => {
    renderForm();

    fireEvent.submit(formElement());

    expect(await screen.findByText(/upload accepted/i)).toBeInTheDocument();
  });

  it("lands a form-level refusal on the form, not the file control", async () => {
    renderForm(
      vi.fn(async (): Promise<ActionState> => ({
        ok: false,
        error: "Choose a load mode: merge or replace.",
        field: "mode",
      })),
    );

    fireEvent.submit(formElement());

    expect(await screen.findByRole("alert")).toHaveTextContent(/choose a load mode/i);
    expect(screen.getByLabelText(/snapshot archive/i)).not.toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("lands a file-level refusal on the snapshot control", async () => {
    renderForm(
      vi.fn(async (): Promise<ActionState> => ({
        ok: false,
        error: "Attach the snapshot archive (.sql.gz).",
        field: "snapshot",
      })),
    );

    fireEvent.submit(formElement());

    expect(await screen.findByRole("alert")).toHaveTextContent(/attach the snapshot archive/i);
    expect(screen.getByLabelText(/snapshot archive/i)).toHaveAttribute("aria-invalid", "true");
  });
});
