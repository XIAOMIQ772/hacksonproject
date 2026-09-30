import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { get } from './api';

export type Session = { user: { username: string; email: string } | null; orgs: { login: string; displayName: string }[] };
type Ctx = Session & { loaded: boolean; refresh: () => Promise<void> };

const SessionContext = createContext<Ctx>({ user: null, orgs: [], loaded: false, refresh: async () => {} });

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [s, setS] = useState<Session>({ user: null, orgs: [] });
  const [loaded, setLoaded] = useState(false);
  const refresh = useCallback(async () => {
    try {
      setS(await get<Session>('/session'));
    } catch {
      setS({ user: null, orgs: [] });
    }
    setLoaded(true);
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  return <SessionContext.Provider value={{ ...s, loaded, refresh }}>{children}</SessionContext.Provider>;
}

export const useSession = () => useContext(SessionContext);
