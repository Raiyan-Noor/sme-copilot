"use client";

import { useCallback, useEffect, useState } from "react";

export type ApiState<T> = {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
};

/**
 * Fetch on mount and whenever `key` changes. Pass `key = null` to skip (e.g. no business selected yet).
 * State is tagged with the key it belongs to, so a stale response never shows under a new key.
 */
export function useApi<T>(key: string | null, load: () => Promise<T>): ApiState<T> {
  const [state, setState] = useState<{ key: string; data?: T; error?: unknown } | null>(null);
  const [nonce, setNonce] = useState(0);
  const tag = key === null ? null : `${key}#${nonce}`;

  useEffect(() => {
    if (tag === null) return;
    let live = true;
    load().then(
      (data) => live && setState({ key: tag, data }),
      (error) => live && setState({ key: tag, error }),
    );
    return () => {
      live = false;
    };
    // `load` is a fresh closure every render; `tag` captures everything it depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tag]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const current = state && state.key === tag ? state : undefined;
  return { data: current?.data, error: current?.error, loading: tag !== null && !current, reload };
}
