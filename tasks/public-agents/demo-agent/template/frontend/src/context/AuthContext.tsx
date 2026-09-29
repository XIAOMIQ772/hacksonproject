import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { fetchCurrentUser, loginUser, logoutUser, registerUser } from '../api/auth';

const TOKEN_KEY = 'arc_demo_token';

type AuthUser = {
  id: number;
  username: string;
  email: string;
};

type AuthContextValue = {
  user: AuthUser | null;
  authLoading: boolean;
  login: (payload: { account: string; password: string }) => Promise<{ user: AuthUser }>;
  logout: () => Promise<{ message: string }>;
  refreshUser: () => Promise<AuthUser | null>;
  register: (payload: { username: string; email: string; password: string; confirmPassword: string }) => Promise<{ user: AuthUser }>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

function getToken() {
  return window.localStorage.getItem(TOKEN_KEY);
}

function saveToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authLoading, setAuthLoading] = useState(true);

  async function refreshUser() {
    const token = getToken();

    if (!token) {
      setUser(null);
      setAuthLoading(false);
      return null;
    }

    try {
      const response = await fetchCurrentUser();
      setUser(response.data.user);
      return response.data.user;
    } catch (error) {
      clearToken();
      setUser(null);
      throw error;
    } finally {
      setAuthLoading(false);
    }
  }

  useEffect(() => {
    refreshUser().catch(() => {});
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      authLoading,
      async register(payload) {
        const response = await registerUser(payload);
        saveToken(response.data.token);
        setUser(response.data.user);
        return response.data;
      },
      async login(payload) {
        const response = await loginUser(payload);
        saveToken(response.data.token);
        setUser(response.data.user);
        return response.data;
      },
      async logout() {
        try {
          const response = await logoutUser();
          return response.data;
        } finally {
          clearToken();
          setUser(null);
        }
      },
      refreshUser,
    }),
    [authLoading, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error('useAuth must be used within AuthProvider.');
  }

  return context;
}
