"use client";

import { useMemo } from "react";
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

import type { SavedModel } from "@/lib/ensemble-store";
import { getEngineClient } from "@/lib/engine";
import { EngineError, isEngineError } from "@/lib/engine/errors";
import { runOAuth } from "@/lib/engine/oauth";
import type {
  AuthMethod,
  Connection,
  ConnectionStatus,
  EngineModel,
} from "@/lib/engine/types";
import {
  GROUP_ORDER,
  providerPresentation,
  type ProviderGroup,
} from "@/lib/provider-presentation";
import { openExternal } from "@/lib/tauri";

export const MODEL_STORE_KEY = "screamingface-models";

// One provider as the Models page and the composer picker show it: the Engine's connection row
// (or a keyless model owner) joined with its models and Studio's presentation.
export type ProviderView = {
  id: string;
  name: string;
  group: ProviderGroup;
  description: string;
  color: string;
  authMethods: AuthMethod[];
  status: ConnectionStatus;
  accountLabel: string | null;
  connected: boolean;
  // A model owner with no connection row: its models need no credential (Ollama, for example).
  keyless: boolean;
  models: SavedModel[];
};

export type LoadState = "idle" | "loading" | "ready" | "error";

// Mirrors the Python Client's fallback label for a provider with no display name.
function titleCase(id: string) {
  return id
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function toSavedModel(model: EngineModel, providerName?: string): SavedModel {
  // WHY name = id: recipe.ts builds url4 paths from `name`, and the Engine addresses a model by
  // its full `provider/model` id.
  return {
    id: model.id,
    name: model.id,
    providerId: model.owned_by,
    providerName: providerName ?? model.owned_by,
  };
}

export function buildProviders(
  connections: Connection[],
  models: EngineModel[],
): ProviderView[] {
  const byOwner = new Map<string, EngineModel[]>();
  for (const model of models) {
    byOwner.set(model.owned_by, [...(byOwner.get(model.owned_by) ?? []), model]);
  }

  const view = (
    id: string,
    name: string,
    fields: Pick<ProviderView, "authMethods" | "status" | "accountLabel" | "keyless">,
  ): ProviderView => ({
    id,
    name,
    ...providerPresentation(id),
    ...fields,
    connected: fields.status === "connected",
    models: (byOwner.get(id) ?? [])
      .map((model) => toSavedModel(model, name))
      .sort((a, b) => a.id.localeCompare(b.id)),
  });

  const known = new Set(connections.map((row) => row.provider));
  const providers = [
    ...connections.map((row) =>
      view(row.provider, row.display_name, {
        authMethods: row.auth_methods,
        status: row.status,
        accountLabel: row.account_label ?? null,
        keyless: false,
      }),
    ),
    ...[...byOwner.keys()]
      .filter((owner) => !known.has(owner))
      .map((owner) =>
        view(owner, titleCase(owner), {
          authMethods: [],
          status: "connected",
          accountLabel: null,
          keyless: true,
        }),
      ),
  ];

  return providers.sort(
    (a, b) =>
      GROUP_ORDER.indexOf(a.group) - GROUP_ORDER.indexOf(b.group) ||
      a.name.localeCompare(b.name),
  );
}

type SignInOptions = {
  signal?: AbortSignal;
  open?: (url: string) => Promise<void> | void;
};

type ModelState = {
  connections: Connection[];
  models: EngineModel[];
  load: LoadState;
  error: EngineError | null;
  library: SavedModel[];
  refresh: () => Promise<void>;
  connectApiKey: (provider: string, apiKey: string) => Promise<void>;
  signIn: (provider: string, options?: SignInOptions) => Promise<Connection>;
  disconnect: (provider: string) => Promise<void>;
  toggleLibraryModel: (model: SavedModel) => void;
  addLibraryModels: (models: SavedModel[]) => void;
};

function asEngineError(error: unknown) {
  return isEngineError(error) ? error : new EngineError("unknown");
}

// WHY a sequence number: two refreshes can overlap (mount + a finished connect); only the newest
// one may write, or an older, slower response would roll the page back.
let refreshSequence = 0;

export const useModelStore = create<ModelState>()(
  persist(
    (set, get) => ({
      // Server state: fetched from the Engine, kept in memory, never persisted.
      connections: [],
      models: [],
      load: "idle",
      error: null,
      // The user's starred models: a per-user convenience with no backend yet.
      library: [],

      refresh: async () => {
        const sequence = ++refreshSequence;
        if (get().load !== "ready") set({ load: "loading" });
        try {
          const client = await getEngineClient();
          const [connections, models] = await Promise.all([
            client.listConnections(),
            client.listModels(),
          ]);
          if (sequence !== refreshSequence) return;
          set({ connections, models, load: "ready", error: null });
        } catch (error) {
          if (sequence !== refreshSequence) return;
          set({ load: "error", error: asEngineError(error) });
        }
      },

      connectApiKey: async (provider, apiKey) => {
        const client = await getEngineClient();
        await client.connectApiKey(provider, apiKey);
        await get().refresh();
      },

      signIn: async (provider, { signal, open = openExternal } = {}) => {
        const client = await getEngineClient();
        try {
          return await runOAuth(client, provider, { open, signal });
        } finally {
          await get().refresh();
        }
      },

      disconnect: async (provider) => {
        const client = await getEngineClient();
        await client.disconnect(provider);
        await get().refresh();
      },

      toggleLibraryModel: (model) =>
        set((state) => ({
          library: state.library.some((item) => item.id === model.id)
            ? state.library.filter((item) => item.id !== model.id)
            : [...state.library, model],
        })),

      addLibraryModels: (models) =>
        set((state) => {
          const ids = new Set(state.library.map((model) => model.id));
          const added: SavedModel[] = [];
          for (const model of models) {
            if (ids.has(model.id)) continue;
            ids.add(model.id);
            added.push(model);
          }
          return { library: [...state.library, ...added] };
        }),
    }),
    {
      name: MODEL_STORE_KEY,
      storage: createJSONStorage(() => localStorage),
      // v1 held the mock's providers and a library keyed by fake ids (`ol-1`) that no Engine
      // model matches, so nothing of it carries over.
      version: 2,
      migrate: () => ({ library: [] }),
      partialize: (state) => ({ library: state.library }),
    },
  ),
);

export function useProviders(): ProviderView[] {
  const connections = useModelStore((state) => state.connections);
  const models = useModelStore((state) => state.models);
  return useMemo(() => buildProviders(connections, models), [connections, models]);
}
