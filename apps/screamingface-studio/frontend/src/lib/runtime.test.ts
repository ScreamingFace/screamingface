import { EngineError } from "./engine/errors";
import { DEFAULT_ENGINE_URL, getEngineUrl } from "./runtime";

type TauriWindow = Window & { __TAURI__?: unknown };

function installTauri(invoke: (command: string) => Promise<unknown>) {
  (window as TauriWindow).__TAURI__ = { core: { invoke } };
}

afterEach(() => {
  delete (window as TauriWindow).__TAURI__;
  vi.unstubAllEnvs();
});

describe("getEngineUrl", () => {
  it("asks the Tauri shell for the runtime's Engine address", async () => {
    const invoke = vi.fn(async () => ({ engine: "http://127.0.0.1:19108" }));
    installTauri(invoke);

    await expect(getEngineUrl()).resolves.toBe("http://127.0.0.1:19108");
    expect(invoke).toHaveBeenCalledWith("runtime_services");
  });

  it("reports a runtime that is not ready as unreachable", async () => {
    installTauri(async () => null);

    const error = await getEngineUrl().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(EngineError);
    expect(error).toMatchObject({ kind: "unreachable" });
  });

  it("reports a failed shell call as unreachable", async () => {
    installTauri(async () => {
      throw new Error("command not found");
    });

    await expect(getEngineUrl()).rejects.toMatchObject({ kind: "unreachable" });
  });

  it("uses the env override outside Tauri", async () => {
    vi.stubEnv("NEXT_PUBLIC_SCREAMINGFACE_ENGINE_URL", "http://engine.test:1");
    await expect(getEngineUrl()).resolves.toBe("http://engine.test:1");
  });

  it("falls back to the runtime's default port outside Tauri", async () => {
    vi.stubEnv("NEXT_PUBLIC_SCREAMINGFACE_ENGINE_URL", "");
    await expect(getEngineUrl()).resolves.toBe(DEFAULT_ENGINE_URL);
    expect(DEFAULT_ENGINE_URL).toBe("http://127.0.0.1:9108");
  });
});
