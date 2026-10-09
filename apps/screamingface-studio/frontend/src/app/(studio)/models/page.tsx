"use client";

import {
  Boxes,
  Cpu,
  Globe,
  Key,
  Plug,
  RefreshCw,
  Search,
  Star,
  Terminal,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import type { SavedModel } from "@/lib/ensemble-store";
import { isEngineError } from "@/lib/engine/errors";
import {
  useModelStore,
  useProviders,
  type ProviderView,
} from "@/lib/model-store";
import {
  GROUP_ORDER,
  providerPresentation,
} from "@/lib/provider-presentation";
import { fusionOf, recipeToUrl4 } from "@/lib/recipe";
import { cn } from "@/lib/utils";

const STARRED_VIEW = "__starred__";

// A fusion of the selected models, in the form the builder's `?recipe=` import reads.
function buildRecipe(models: SavedModel[]) {
  return recipeToUrl4(fusionOf(models));
}

function errorDetail(error: unknown) {
  return isEngineError(error) ? error.detail : "Something went wrong.";
}

function ProviderDot({ providerId }: { providerId: string }) {
  return (
    <span
      className="size-2 shrink-0 rounded-full"
      style={{ background: providerPresentation(providerId).color }}
    />
  );
}

function StarButton({
  starred,
  label,
  disabled,
  onClick,
}: {
  starred: boolean;
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant="ghost"
      size="icon"
      className={cn(
        "size-8 shrink-0",
        starred
          ? "text-amber-500 hover:text-amber-500"
          : "text-muted-foreground hover:text-foreground",
      )}
      aria-label={label}
      aria-pressed={starred}
      title={disabled ? label : undefined}
      disabled={disabled}
      onClick={onClick}
    >
      <Star className={cn("size-4", starred && "fill-current")} />
    </Button>
  );
}

function ProviderIcon({
  provider,
  className,
}: {
  provider: ProviderView;
  className?: string;
}) {
  const Icon = provider.keyless
    ? Cpu
    : provider.authMethods.includes("oauth")
      ? Terminal
      : Globe;

  return (
    <span
      className={cn(
        "grid size-8 shrink-0 place-items-center rounded-lg",
        className,
      )}
      style={{
        background: `color-mix(in srgb, ${provider.color} 10%, transparent)`,
      }}
    >
      <Icon className="size-4" style={{ color: provider.color }} />
    </span>
  );
}

function StarredRailRow({
  active,
  count,
  onSelect,
}: {
  active: boolean;
  count: number;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left transition-colors focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        active
          ? "border-primary/50 bg-primary/5 shadow-sm ring-1 ring-primary/15"
          : "border-transparent hover:bg-secondary/40",
      )}
      onClick={onSelect}
    >
      <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-amber-500/10">
        <Star className="size-4 fill-current text-amber-500" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">Starred</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {count} {count === 1 ? "model" : "models"} in your library
        </span>
      </span>
    </button>
  );
}

function providerStatusText(provider: ProviderView) {
  if (provider.keyless) return `Local · ${provider.models.length} models`;
  switch (provider.status) {
    case "connected":
      return `${provider.models.length} models`;
    case "pending":
      return "Signing in…";
    case "needs_reauth":
      return "Needs sign-in";
    case "error":
      return "Connection error";
    default:
      return "Not connected";
  }
}

function ProviderRow({
  provider,
  active,
  onSelect,
}: {
  provider: ProviderView;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left transition-colors focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        active
          ? "border-primary/50 bg-primary/5 shadow-sm ring-1 ring-primary/15"
          : "border-transparent hover:bg-secondary/40",
      )}
      onClick={onSelect}
    >
      <ProviderIcon provider={provider} className="size-7" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium">
          {provider.name}
        </span>
        <span className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
          {provider.connected && (
            <span className="size-1.5 rounded-full bg-accent" />
          )}
          <span className={cn(provider.connected && "text-accent")}>
            {providerStatusText(provider)}
          </span>
        </span>
      </span>
    </button>
  );
}

function ProviderConnect({ provider }: { provider: ProviderView }) {
  const connectApiKey = useModelStore((state) => state.connectApiKey);
  const signIn = useModelStore((state) => state.signIn);
  const disconnect = useModelStore((state) => state.disconnect);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState<"key" | "oauth" | "disconnect" | null>(null);
  const [message, setMessage] = useState("");
  const signInController = useRef<AbortController | null>(null);

  const supportsOAuth = provider.authMethods.includes("oauth");
  const supportsKey = provider.authMethods.includes("api_key");
  // The Engine refuses a new sign-in (and an API key over an OAuth row) while a saved row exists,
  // so a credential that stopped working is removed before connecting again.
  const stale = provider.status === "needs_reauth" || provider.status === "error";
  const clearStale = async () => {
    if (stale) await disconnect(provider.id);
  };

  if (provider.keyless) {
    return (
      <div className="flex max-w-md flex-col gap-3 rounded-xl border bg-card p-4">
        <p className="text-xs text-muted-foreground">
          These models run through your local ScreamingFace runtime. No API key
          is needed.
        </p>
      </div>
    );
  }

  async function run(kind: "key" | "oauth" | "disconnect", action: () => Promise<unknown>) {
    setBusy(kind);
    setMessage("");
    try {
      await action();
    } catch (error) {
      setMessage(errorDetail(error));
    } finally {
      setBusy(null);
    }
  }

  function submitKey(event: FormEvent) {
    event.preventDefault();
    const key = apiKey.trim();
    if (!key) return;
    void run("key", async () => {
      try {
        await clearStale();
        await connectApiKey(provider.id, key);
      } finally {
        // The key goes to the Engine and nowhere else: never kept in the form after the call.
        setApiKey("");
      }
    });
  }

  function startSignIn() {
    const controller = new AbortController();
    signInController.current = controller;
    void run("oauth", async () => {
      await clearStale();
      const result = await signIn(provider.id, { signal: controller.signal });
      if (result.status === "error") {
        setMessage(`${provider.name} sign-in did not complete.`);
      }
    });
  }

  if (provider.connected) {
    return (
      <div className="flex max-w-md flex-wrap items-center justify-between gap-3 rounded-xl border bg-card p-4">
        <p className="flex items-center gap-1.5 text-xs text-accent">
          <span className="size-1.5 rounded-full bg-accent" />
          Connected{provider.accountLabel ? ` as ${provider.accountLabel}` : ""}
        </p>
        <Button
          size="sm"
          variant="outline"
          className="rounded-lg"
          disabled={busy !== null}
          onClick={() => run("disconnect", () => disconnect(provider.id))}
        >
          {busy === "disconnect" ? "Disconnecting…" : "Disconnect"}
        </Button>
        {message && (
          <p role="alert" className="w-full text-xs text-destructive">
            {message}
          </p>
        )}
      </div>
    );
  }

  const waitingElsewhere = provider.status === "pending" && busy !== "oauth";

  return (
    <div className="flex max-w-md flex-col gap-3 rounded-xl border bg-card p-4">
      {stale && (
        <p className="text-xs text-muted-foreground">
          The saved {provider.name} credential stopped working. Connect again to
          keep using its models.
        </p>
      )}

      {waitingElsewhere ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-muted-foreground">
            A {provider.name} sign-in is waiting to finish in your browser.
          </p>
          <Button
            size="sm"
            variant="outline"
            className="rounded-lg"
            disabled={busy !== null}
            onClick={() => run("disconnect", () => disconnect(provider.id))}
          >
            Cancel sign-in
          </Button>
        </div>
      ) : (
        supportsOAuth && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              className="rounded-lg"
              disabled={busy !== null}
              onClick={startSignIn}
            >
              {busy === "oauth" ? (
                <>
                  <span className="size-3 animate-spin rounded-full border-2 border-primary-foreground/30 border-t-primary-foreground" />
                  Waiting for sign-in…
                </>
              ) : (
                <>
                  <Terminal className="size-3.5" />
                  Sign in with {provider.name}
                </>
              )}
            </Button>
            {busy === "oauth" && (
              <Button
                size="sm"
                variant="ghost"
                className="rounded-lg"
                onClick={() => signInController.current?.abort()}
              >
                Cancel
              </Button>
            )}
          </div>
        )
      )}

      {supportsKey && (
        <form className="flex flex-col gap-3" onSubmit={submitKey}>
          {supportsOAuth && (
            <p className="text-xs text-muted-foreground">or use an API key</p>
          )}
          <div>
            <label
              htmlFor={`${provider.id}-api-key`}
              className="mb-1.5 block text-xs text-muted-foreground"
            >
              API Key
            </label>
            <div className="relative">
              <Key className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                id={`${provider.id}-api-key`}
                type="password"
                autoComplete="off"
                placeholder="sk-…"
                value={apiKey}
                className="h-9 pl-9 text-xs"
                onChange={(event) => setApiKey(event.target.value)}
              />
            </div>
          </div>
          <Button
            type="submit"
            size="sm"
            variant={supportsOAuth ? "outline" : "default"}
            className="self-start rounded-lg"
            disabled={busy !== null || apiKey.trim() === ""}
          >
            {busy === "key" ? "Connecting…" : "Connect"}
          </Button>
        </form>
      )}

      <label className="flex items-center gap-2 text-xs text-muted-foreground">
        <Switch checked={false} disabled aria-label="Use OpenMined key (subsidized)" />
        Use OpenMined key (subsidized)
        <span className="rounded-md border px-1.5 py-0.5 text-[10px] uppercase tracking-wider">
          Coming soon
        </span>
      </label>

      {message && (
        <p role="alert" className="text-xs text-destructive">
          {message}
        </p>
      )}
    </div>
  );
}

function RuntimeUnavailable({
  detail,
  onRetry,
}: {
  detail: string;
  onRetry: () => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-muted-foreground">
      <Plug className="size-7 opacity-20" />
      <p className="text-sm">The local ScreamingFace runtime isn&apos;t reachable.</p>
      <p className="max-w-sm text-xs opacity-70">{detail}</p>
      <Button size="sm" variant="outline" className="rounded-lg" onClick={onRetry}>
        <RefreshCw className="size-3.5" />
        Retry
      </Button>
    </div>
  );
}

export default function ModelsPage() {
  const providers = useProviders();
  const load = useModelStore((state) => state.load);
  const error = useModelStore((state) => state.error);
  const refresh = useModelStore((state) => state.refresh);
  const library = useModelStore((state) => state.library);
  const toggleLibraryModel = useModelStore(
    (state) => state.toggleLibraryModel,
  );
  // `undefined` = nothing chosen yet: show the first connected provider once the list loads.
  const [selection, setSelection] = useState<string | null | undefined>();
  const [search, setSearch] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const selectedId =
    selection === undefined
      ? (providers.find((provider) => provider.connected && !provider.keyless)
          ?.id ?? null)
      : selection;
  const starredView = selectedId === STARRED_VIEW;
  const active =
    providers.find((provider) => provider.id === selectedId) ?? null;
  const filteredModels = useMemo(
    () =>
      active?.models.filter((model) =>
        model.name.toLowerCase().includes(search.toLowerCase()),
      ) ?? [],
    [active, search],
  );

  const starredById = useMemo(
    () => new Set(library.map((model) => model.id)),
    [library],
  );
  // A model is usable only while its provider is connected (or keyless): the catalog also lists
  // models of providers that aren't.
  const availableIds = useMemo(
    () =>
      new Set(
        providers
          .filter((provider) => provider.connected)
          .flatMap((provider) => provider.models.map((model) => model.id)),
      ),
    [providers],
  );
  const isAvailable = (model: SavedModel) =>
    load !== "ready" || availableIds.has(model.id);

  const unstar = (model: SavedModel) => {
    toggleLibraryModel(model);
    setChecked((current) => {
      if (!current.has(model.id)) return current;
      const next = new Set(current);
      next.delete(model.id);
      return next;
    });
  };

  const toggleChecked = (id: string) => {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const selectedModels = useMemo(
    () =>
      library.filter(
        (model) =>
          checked.has(model.id) && (load !== "ready" || availableIds.has(model.id)),
      ),
    [library, checked, load, availableIds],
  );
  const composeRecipe = buildRecipe(selectedModels);
  const canCompose = selectedModels.length > 0;

  const unreachable = load === "error" && providers.length === 0;
  const loading = (load === "idle" || load === "loading") && providers.length === 0;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      <header className="flex shrink-0 items-start justify-between gap-3 border-b px-5 py-5 sm:px-8">
        <div>
          <h1 className="text-base font-semibold">Models</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Connect providers once, then star models to build a reusable
            library for your fusions.
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="size-8 shrink-0 text-muted-foreground"
          aria-label="Refresh providers and models"
          disabled={load === "loading"}
          onClick={() => void refresh()}
        >
          <RefreshCw className={cn("size-4", load === "loading" && "animate-spin")} />
        </Button>
      </header>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside className="flex w-64 shrink-0 flex-col gap-5 overflow-y-auto border-r px-4 py-6">
          <section className="flex flex-col gap-1">
            <StarredRailRow
              active={starredView}
              count={library.length}
              onSelect={() => setSelection(STARRED_VIEW)}
            />
          </section>
          {load === "error" && providers.length > 0 && (
            <p role="status" className="px-1 text-xs text-destructive">
              Couldn&apos;t refresh: {error?.detail}
            </p>
          )}
          {loading && (
            <div aria-label="Loading providers" className="flex flex-col gap-2">
              {[0, 1, 2, 3].map((index) => (
                <div
                  key={index}
                  className="h-11 animate-pulse rounded-lg bg-secondary/40"
                />
              ))}
            </div>
          )}
          {GROUP_ORDER.map((group) => {
            const members = providers.filter(
              (provider) => provider.group === group,
            );
            if (members.length === 0) return null;
            return (
              <section key={group} className="flex flex-col gap-1">
                <h2 className="px-1 pb-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  {group}
                </h2>
                {members.map((provider) => (
                  <ProviderRow
                    key={provider.id}
                    provider={provider}
                    active={provider.id === selectedId}
                    onSelect={() =>
                      setSelection(
                        provider.id === selectedId ? null : provider.id,
                      )
                    }
                  />
                ))}
              </section>
            );
          })}
        </aside>

        <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
          <div className="min-h-0 flex-1 px-6 py-6">
            {starredView ? (
              <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-amber-500/10">
                      <Star className="size-4 fill-current text-amber-500" />
                    </span>
                    <div>
                      <h2 className="text-sm font-medium">Starred Models</h2>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        Check the models you want, then compose a fusion.
                      </p>
                    </div>
                  </div>
                  {library.length > 0 && (
                    <Button
                      className="rounded-lg"
                      size="sm"
                      disabled={!canCompose}
                      asChild={canCompose}
                    >
                      {canCompose ? (
                        <Link
                          href={`/ensembles/new/?recipe=${encodeURIComponent(composeRecipe)}`}
                          prefetch={false}
                        >
                          <Boxes className="size-3.5" />
                          Compose a Fusion
                        </Link>
                      ) : (
                        <>
                          <Boxes className="size-3.5" />
                          Compose a Fusion
                        </>
                      )}
                    </Button>
                  )}
                </div>

                {library.length === 0 ? (
                  <div className="flex flex-col items-center justify-center gap-3 py-16 text-muted-foreground">
                    <Star className="size-7 opacity-20" />
                    <p className="text-sm opacity-50">
                      Star models from a provider to add them here.
                    </p>
                  </div>
                ) : (
                  <div className="grid gap-3 xl:grid-cols-2">
                    {library.map((model) => {
                      const available = isAvailable(model);
                      const isChecked = available && checked.has(model.id);
                      return (
                        <div
                          key={model.id}
                          className={cn(
                            "flex w-full items-center gap-3 rounded-xl border bg-card px-4 py-3.5 transition-colors",
                            isChecked
                              ? "border-primary/50 bg-primary/5"
                              : "hover:border-foreground/20",
                            !available && "opacity-60",
                          )}
                        >
                          <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              disabled={!available}
                              onChange={() => toggleChecked(model.id)}
                              className="size-4 shrink-0 rounded border-input accent-primary"
                              aria-label={`Select ${model.name} for composing`}
                            />
                            <ProviderDot providerId={model.providerId} />
                            <span className="truncate text-sm">
                              {model.name}{" "}
                              <span className="font-mono text-xs text-muted-foreground">
                                [{model.providerName}]
                              </span>
                            </span>
                            {!available && (
                              <span className="shrink-0 rounded-md border px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                                Unavailable
                              </span>
                            )}
                          </label>
                          <StarButton
                            starred
                            label={`Unstar ${model.name}`}
                            onClick={() => unstar(model)}
                          />
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : unreachable ? (
              <RuntimeUnavailable
                detail={error?.detail ?? ""}
                onRetry={() => void refresh()}
              />
            ) : !active ? (
              <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
                <Plug className="size-7 opacity-20" />
                <p className="text-sm opacity-50">
                  {loading ? "Loading providers…" : "Select a provider on the left."}
                </p>
              </div>
            ) : (
              <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <ProviderIcon provider={active} />
                    <div>
                      <h2 className="text-sm font-medium">{active.name}</h2>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {active.description ||
                          `${active.models.length} models on this Engine`}
                      </p>
                    </div>
                  </div>
                  {active.models.length > 0 && (
                    <div className="relative w-44">
                      <Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        value={search}
                        placeholder="Search…"
                        aria-label={`Search ${active.name} models`}
                        className="h-9 pl-9 text-xs"
                        onChange={(event) => setSearch(event.target.value)}
                      />
                    </div>
                  )}
                </div>

                <ProviderConnect key={active.id} provider={active} />

                {active.models.length === 0 ? (
                  <p className="py-8 text-center text-xs text-muted-foreground/60">
                    This Engine lists no models for {active.name} yet.
                  </p>
                ) : (
                  <>
                    <p className="text-xs text-muted-foreground">
                      {active.connected
                        ? `${library.filter((model) => model.providerId === active.id).length} in your library`
                        : `Preview. Connect ${active.name} to star these models.`}
                    </p>
                    {filteredModels.length === 0 ? (
                      <p className="py-8 text-center text-xs text-muted-foreground/60">
                        No models match these filters.
                      </p>
                    ) : (
                      <div className="grid gap-3 xl:grid-cols-2">
                        {filteredModels.map((model) => {
                          const starred = starredById.has(model.id);
                          return (
                            <div
                              key={model.id}
                              className={cn(
                                "flex w-full items-center justify-between gap-3 rounded-xl border bg-card px-4 py-3.5 transition-colors",
                                starred
                                  ? "border-primary/50 bg-primary/5"
                                  : "hover:border-foreground/20",
                              )}
                            >
                              <span className="flex min-w-0 items-center gap-3">
                                <ProviderDot providerId={model.providerId} />
                                <span className="truncate text-sm">
                                  {model.name}
                                </span>
                              </span>
                              <StarButton
                                starred={starred}
                                disabled={!active.connected && !starred}
                                label={
                                  starred
                                    ? `Unstar ${model.name}`
                                    : active.connected
                                      ? `Star ${model.name}`
                                      : `Connect ${active.name} to star ${model.name}`
                                }
                                onClick={() => toggleLibraryModel(model)}
                              />
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </main>
      </div>

      <footer className="flex shrink-0 items-center justify-end border-t px-6 py-4 sm:px-8">
        <Button asChild className="rounded-xl">
          <Link href="/ensembles/new/" prefetch={false}>
            <Boxes className="size-4" />
            Start building a fusion
          </Link>
        </Button>
      </footer>
    </div>
  );
}
