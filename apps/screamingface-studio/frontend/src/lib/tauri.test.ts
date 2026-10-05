import { openExternal, tauriInvoke } from "./tauri";

type TauriWindow = Window & { __TAURI__?: unknown };

afterEach(() => {
  delete (window as TauriWindow).__TAURI__;
  vi.restoreAllMocks();
});

describe("tauriInvoke", () => {
  it("is null outside Tauri", () => {
    expect(tauriInvoke()).toBeNull();
  });

  it("returns the global invoke inside Tauri", () => {
    const invoke = vi.fn();
    (window as TauriWindow).__TAURI__ = { core: { invoke } };
    expect(tauriInvoke()).toBe(invoke);
  });
});

describe("openExternal", () => {
  it("opens the URL through the opener plugin inside Tauri", async () => {
    const invoke = vi.fn(async () => undefined);
    (window as TauriWindow).__TAURI__ = { core: { invoke } };

    await openExternal("https://auth.example/a");
    expect(invoke).toHaveBeenCalledWith("plugin:opener|open_url", {
      url: "https://auth.example/a",
    });
  });

  it("opens a new browser tab outside Tauri", async () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);

    await openExternal("https://auth.example/b");
    expect(open).toHaveBeenCalledWith(
      "https://auth.example/b",
      "_blank",
      "noopener,noreferrer",
    );
  });
});
