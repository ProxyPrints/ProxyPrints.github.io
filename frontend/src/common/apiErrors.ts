/**
 * Shared helpers for handling errors thrown by src/store/api.ts's fetch wrappers, which reject
 * with a `{name, message, status?}` object mirroring the backend's ErrorResponse shape (not
 * every endpoint attaches `status` yet - see api.ts for which do). Every vote-casting catch
 * block in this codebase used to discard the caught error entirely and show a hardcoded
 * generic toast - even for a 429 whose backend message ("Too many tag vote submissions -
 * please slow down") was exactly the useful, specific thing to show. Centralizes two things:
 * surfacing the backend's own message instead of a hardcoded generic one, and detecting a 429
 * rate-limit response distinctly from any other failure.
 */

import { Notification } from "@/common/types";

export interface ShapedAPIError {
  name?: string | null;
  message?: string | null;
  status?: number;
}

function asShapedAPIError(error: unknown): ShapedAPIError | null {
  // api.ts always throws a plain object literal, never a real Error instance - excluding
  // Error instances here specifically is what keeps a genuine network-level failure (a real
  // `TypeError` from a dropped fetch, which does have its own unhelpful `.message`) falling
  // through to the caller's generic copy instead of surfacing "Failed to fetch" verbatim.
  if (typeof error !== "object" || error === null || error instanceof Error) {
    return null;
  }
  return error as ShapedAPIError;
}

/**
 * True only for a genuine 429 from api.ts's shaped rejection - false for a message-less
 * network-level failure (a raw `TypeError` from a dropped connection has no `status`), so
 * callers can safely branch on this without a false positive there.
 */
export function isRateLimited(error: unknown): boolean {
  return asShapedAPIError(error)?.status === 429;
}

/**
 * Builds a toast Notification from a caught API error: surfaces the backend's own name/message
 * when the error is shaped (the common case - a real 4xx/5xx from api.ts), falling back to the
 * caller-supplied generic copy only when the error carries no message at all (e.g. a raw
 * network failure, which has no backend copy to show).
 */
export function errorToNotification(
  error: unknown,
  fallback: { name: string; message: string }
): Notification {
  const shaped = asShapedAPIError(error);
  return {
    name: shaped?.name ?? fallback.name,
    message: shaped?.message ?? fallback.message,
    level: "error",
  };
}
