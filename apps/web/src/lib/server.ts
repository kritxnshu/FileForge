import "server-only";
import { fetchCapabilities, serverApiBase, type Capabilities } from "./api";

/** Capabilities for server rendering. Returns null when the API is unreachable (the client retries). */
export async function serverCaps(): Promise<Capabilities | null> {
  try {
    return await fetchCapabilities(serverApiBase());
  } catch {
    return null;
  }
}
