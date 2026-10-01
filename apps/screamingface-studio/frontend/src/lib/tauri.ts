// Access to the Tauri shell through the `withGlobalTauri` global, the same way the rest of
// Studio reaches it (`native-theme-sync.tsx`, `updates/page.tsx`). Everything here also works in
// a plain browser (`next dev`), where the global is absent.

type Invoke = (command: string, args?: Record<string, unknown>) => Promise<unknown>;

type TauriGlobal = { core?: { invoke?: Invoke } };

export function tauriInvoke(): Invoke | null {
  if (typeof window === "undefined") return null;
  const tauri = (window as Window & { __TAURI__?: TauriGlobal }).__TAURI__;
  const invoke = tauri?.core?.invoke;
  return typeof invoke === "function" ? invoke : null;
}

// Opens a URL in the system browser (an OAuth sign-in page, for example).
export async function openExternal(url: string): Promise<void> {
  const invoke = tauriInvoke();
  if (invoke) {
    await invoke("plugin:opener|open_url", { url });
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}
