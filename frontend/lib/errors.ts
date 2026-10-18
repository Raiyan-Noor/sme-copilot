import { ApiError } from "@/lib/api";

/** A short, owner-readable error line. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = typeof error.detail === "string" ? error.detail : JSON.stringify(error.detail);
    return `${detail} (${error.status})`;
  }
  return error instanceof Error ? error.message : String(error);
}
