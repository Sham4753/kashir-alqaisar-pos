import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { clearConnection, loadConnection, saveConnection } from "@/lib/kashir-storage";
import type { Connection } from "@/lib/kashir-types";

type WaiterContextValue = {
  connection: Connection | null;
  ready: boolean;
  setConnection: (value: Connection) => Promise<void>;
  signOut: () => Promise<void>;
};

const WaiterContext = createContext<WaiterContextValue | null>(null);

export function WaiterProvider({ children }: { children: React.ReactNode }) {
  const [connection, setConnectionState] = useState<Connection | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    loadConnection().then((value) => { setConnectionState(value); setReady(true); });
  }, []);

  const setConnection = useCallback(async (value: Connection) => {
    await saveConnection(value);
    setConnectionState(value);
  }, []);

  const signOut = useCallback(async () => {
    await clearConnection();
    setConnectionState(null);
  }, []);

  const value = useMemo(() => ({ connection, ready, setConnection, signOut }), [connection, ready, setConnection, signOut]);
  return <WaiterContext.Provider value={value}>{children}</WaiterContext.Provider>;
}

export function useWaiter() {
  const value = useContext(WaiterContext);
  if (!value) throw new Error("useWaiter must be used inside WaiterProvider");
  return value;
}
