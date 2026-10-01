import { EngineError } from "./engine/errors";
import { tauriInvoke } from "./tauri";

export const DEFAULT_ENGINE_URL = "http://127.0.0.1:9108";

type RuntimeServices = { engine: string } | null;

// The one place Studio decides which Engine it talks to. Inside Tauri the shell reports the
// address from the runtime's readiness record; in a plain browser an env override or the
// runtime's default port is used.
//
// AIDEV-NOTE: a later OME-1308 unit makes the Engine switchable (local / hosted). That setting
// plugs in here, so no call site changes.
export async function getEngineUrl(): Promise<string> {
  const invoke = tauriInvoke();
  if (invoke) {
    let services: RuntimeServices;
    try {
      services = (await invoke("runtime_services")) as RuntimeServices;
    } catch {
      throw new EngineError("unreachable");
    }
    if (!services?.engine) {
      throw new EngineError(
        "unreachable",
        "The local ScreamingFace runtime is not running yet.",
      );
    }
    return services.engine;
  }
  return process.env.NEXT_PUBLIC_SCREAMINGFACE_ENGINE_URL || DEFAULT_ENGINE_URL;
}
