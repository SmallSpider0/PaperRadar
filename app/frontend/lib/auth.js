import { createContext, useContext } from 'react';

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/paperradar-api';

export const AuthContext = createContext({
  loading: true,
  user: null,
  refresh: async () => null,
  setUser: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function canAccessPath(role, path) {
  const normalizedRole = role || 'user';
  if (normalizedRole === 'admin') return true;
  const userAllowed = ['/', '/chat', '/search', '/subscriptions', '/user'];
  return userAllowed.includes(path);
}

