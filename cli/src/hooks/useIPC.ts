/**
 * React hook for IPC communication
 */

import {useState, useEffect} from 'react';
import {ipcClient} from '../lib/ipc-client.js';
import type {IPCResponse} from '../lib/types.js';

interface UseIPCOptions<T> {
  command: string;
  params?: Record<string, unknown>;
  autoExecute?: boolean;
}

interface UseIPCResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  execute: () => Promise<void>;
}

export function useIPC<T>({
  command,
  params = {},
  autoExecute = true,
}: UseIPCOptions<T>): UseIPCResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const execute = async () => {
    setLoading(true);
    setError(null);

    try {
      if (!ipcClient.isConnected()) {
        await ipcClient.connect();
      }

      const response: IPCResponse<T> = await ipcClient.send<T>(command, params);

      if (response.success && response.data) {
        setData(response.data);
      } else {
        throw new Error(response.error || 'Unknown error');
      }
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (autoExecute) {
      void execute();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoExecute]);

  return {data, loading, error, execute};
}
