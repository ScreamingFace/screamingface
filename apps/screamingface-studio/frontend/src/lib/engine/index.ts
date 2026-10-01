import { getEngineUrl } from "../runtime";
import { createEngineClient, type EngineClient } from "./client";

// The Engine Studio talks to right now. Resolved per call, so a runtime that restarts on a
// new address (or, later, a user-switched Engine) is picked up without a reload.
export async function getEngineClient(): Promise<EngineClient> {
  return createEngineClient(await getEngineUrl());
}
