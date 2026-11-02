"use client";

import {
  Boxes,
  ChevronRight,
  GitFork,
  Plug,
  Plus,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useEnsembleStore } from "@/lib/ensemble-store";
import { useModelStore, useProviders } from "@/lib/model-store";
import { providerPresentation } from "@/lib/provider-presentation";
import { collectSolos, describeRecipeKind, parseRecipe } from "@/lib/recipe";

const LEGACY_STRATEGY_LABEL = {
  majority_vote: "Majority Vote",
  weighted_avg: "Weighted Average",
  best_of_n: "Best-of-N",
  merge: "Merge",
} as const;

export default function EnsemblesPage() {
  const router = useRouter();
  const [importing, setImporting] = useState(false);
  const [importValue, setImportValue] = useState("");
  const [importError, setImportError] = useState("");
  const providers = useProviders();
  const catalogLoad = useModelStore((state) => state.load);
  const catalog = useModelStore((state) => state.models);
  const refreshCatalog = useModelStore((state) => state.refresh);
  const hasProviderConnected = providers.some(
    (provider) => provider.connected && provider.models.length > 0,
  );

  useEffect(() => {
    if (catalogLoad === "idle") void refreshCatalog();
  }, [catalogLoad, refreshCatalog]);
  const ensembles = useEnsembleStore((state) => state.ensembles);

  function importRecipe() {
    const parsed = parseRecipe(importValue);
    if (!parsed.ok) {
      setImportError(parsed.error);
      return;
    }

    if (catalogLoad !== "ready") {
      setImportError(
        "The model catalog hasn't loaded. Is the local ScreamingFace runtime running?",
      );
      return;
    }
    const knownModelIds = new Set(catalog.map((model) => model.id));
    const models = collectSolos(parsed.root)
      .map((solo) => solo.model?.id)
      .filter((id): id is string => Boolean(id));
    const unknown = [...new Set(models.filter((model) => !knownModelIds.has(model)))];

    if (models.length === 0) {
      setImportError("No models found in that url4.");
      return;
    }
    if (unknown.length > 0) {
      setImportError(`Unknown models: ${unknown.join(", ")}`);
      return;
    }

    setImporting(false);
    setImportValue("");
    setImportError("");
    router.push(`/ensembles/new/?recipe=${encodeURIComponent(importValue.trim())}`);
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      <header className="flex shrink-0 items-center justify-between gap-4 border-b px-5 py-5 sm:px-8">
        <div
          data-tauri-drag-region
          className="min-w-0 flex-1"
        >
          <h1 className="text-base font-semibold">Fusions</h1>
          <p className="mt-1 text-xs text-muted-foreground">
            Your recipes. Open one to compose, run evals, and analyze results.
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="rounded-lg"
            onClick={() => {
              setImporting((current) => !current);
              setImportError("");
            }}
          >
            <GitFork className="size-3.5" />
            Import url4
          </Button>
          <Button size="sm" className="rounded-lg shadow-sm" asChild>
            <Link href="/ensembles/new/" prefetch={false}>
              <Plus className="size-4" />
              New Fusion
            </Link>
          </Button>
        </div>
      </header>

      {importing && (
        <section className="shrink-0 border-b bg-muted/20 px-5 py-4 sm:px-8">
          <div className="w-full">
            <div className="mb-2 flex items-start justify-between gap-4">
              <p className="text-xs text-muted-foreground">
                Paste a url4 recipe to create a fusion from it
              </p>
              <Button
                variant="ghost"
                size="icon"
                className="-my-2 size-8"
                aria-label="Close import"
                onClick={() => {
                  setImporting(false);
                  setImportError("");
                }}
              >
                <X className="size-3.5" />
              </Button>
            </div>

            <div className="flex max-w-2xl items-center gap-2">
              <Input
                autoFocus
                value={importValue}
                onChange={(event) => {
                  setImportValue(event.target.value);
                  setImportError("");
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") importRecipe();
                }}
                placeholder="Paste a recipe copied with Share url4"
                className="h-9 rounded-lg font-mono text-xs"
              />
              <Button size="sm" onClick={importRecipe}>
                Create
              </Button>
            </div>

            {importError && (
              <p className="mt-1.5 text-xs text-destructive">
                {importError}
              </p>
            )}
          </div>
        </section>
      )}

      <main className="min-h-0 flex-1 overflow-y-auto px-5 py-8 sm:px-8">
        {ensembles.length === 0 ? (
          <section className="flex justify-center py-16">
            <div className="flex w-full max-w-md flex-col items-center gap-5 rounded-xl border bg-card p-8 text-center">
              <Boxes className="size-7 text-muted-foreground/30" />
              <div className="space-y-2">
                <h2 className="text-sm font-semibold">No fusions yet</h2>
                <p className="text-xs text-muted-foreground">
                  A fusion runs several models on the same question and
                  combines their answers into one.
                </p>
              </div>
              <Button size="sm" className="rounded-lg shadow-sm" asChild>
                <Link href="/ensembles/new/" prefetch={false}>
                  <Plus className="size-4" />
                  New Fusion
                </Link>
              </Button>
              {!hasProviderConnected && (
                <Link
                  href="/models/"
                  prefetch={false}
                  className="inline-flex items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
                >
                  <Plug className="size-3.5" />
                  First, connect a model on the Models page &rarr;
                </Link>
              )}
            </div>
          </section>
        ) : (
          <section className="grid max-w-4xl gap-4 md:grid-cols-2">
            {ensembles.map((ensemble) => (
              <Link
                key={ensemble.id}
                href={`/ensembles/new/?id=${encodeURIComponent(ensemble.id)}`}
                prefetch={false}
                className="group flex flex-col gap-4 rounded-xl border bg-card p-5 text-left transition-colors hover:border-foreground/20"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="truncate font-mono text-sm font-medium">
                      {ensemble.name}
                    </h2>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {ensemble.slots.length} models ·{" "}
                      {ensemble.root
                        ? describeRecipeKind(ensemble.root)
                        : LEGACY_STRATEGY_LABEL[ensemble.strategy]}
                    </p>
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </div>
                <div className="flex min-h-4 items-center gap-1.5">
                  {ensemble.slots.length > 0 ? (
                    ensemble.slots.slice(0, 6).map((slot, index) => (
                      <span
                        key={slot.id ?? `${slot.model.id}-${index}`}
                        className="size-2 rounded-full"
                        style={{
                          background: providerPresentation(
                            slot.model.providerId,
                          ).color,
                        }}
                      />
                    ))
                  ) : (
                    <span className="text-xs text-muted-foreground/50">
                      empty recipe
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between border-t border-border/40 pt-3 text-xs text-muted-foreground">
                  <span>
                    {ensemble.runs} run{ensemble.runs === 1 ? "" : "s"}
                  </span>
                  <span>
                    Saved{" "}
                    {new Date(ensemble.updatedAt).toLocaleDateString("en", {
                      month: "short",
                      day: "numeric",
                    })}
                  </span>
                </div>
              </Link>
            ))}
          </section>
        )}
      </main>
    </div>
  );
}
