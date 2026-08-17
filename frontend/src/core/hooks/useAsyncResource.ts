import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> = {
  data: T | null;
  error: string;
  loading: boolean;
};

export function useAsyncResource<T>(loader: () => Promise<T>, dependencies: readonly unknown[]) {
  const [state, setState] = useState<AsyncState<T>>({ data: null, error: "", loading: true });
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => {
    setState({ data: null, error: "", loading: true });
    setNonce((value) => value + 1);
  }, []);

  useEffect(() => {
    let active = true;
    loader().then(
      (data) => active && setState({ data, error: "", loading: false }),
      (error: unknown) =>
        active &&
        setState({
          data: null,
          error: error instanceof Error ? error.message : "Request failed",
          loading: false,
        }),
    );
    return () => {
      active = false;
    };
    // The caller deliberately controls request identity through primitive dependencies.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, nonce]);

  return { ...state, reload };
}
