import '../styles/globals.css';
import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/router';

import { API_BASE, AuthContext, canAccessPath } from '../lib/auth';

const PUBLIC_PATHS = new Set(['/login']);

export default function App({ Component, pageProps }) {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [user, setUser] = useState(null);

  async function refresh() {
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`);
      if (!res.ok) {
        setUser(null);
        return null;
      }
      const data = await res.json();
      setUser(data);
      return data;
    } catch {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (loading) return;
    const pathname = router.pathname || '/';
    if (PUBLIC_PATHS.has(pathname)) {
      if (user) {
        router.replace('/');
      }
      return;
    }
    if (!user) {
      const next = encodeURIComponent(pathname);
      router.replace(`/login?next=${next}`);
      return;
    }
    if (!canAccessPath(user.role, pathname)) {
      router.replace('/');
    }
  }, [loading, user, router]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const nativeFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await nativeFetch(...args);
      if (response.status === 401 && !PUBLIC_PATHS.has(router.pathname || '/')) {
        setUser(null);
      }
      if (response.status === 403 && !PUBLIC_PATHS.has(router.pathname || '/')) {
        router.replace('/');
      }
      return response;
    };
    return () => {
      window.fetch = nativeFetch;
    };
  }, [router.pathname]);

  const authContextValue = useMemo(
    () => ({
      loading,
      user,
      refresh,
      setUser,
    }),
    [loading, user]
  );

  if (loading && !PUBLIC_PATHS.has(router.pathname || '/')) {
    return <div className="flex min-h-screen items-center justify-center text-slate-500">Loading session...</div>;
  }

  return (
    <AuthContext.Provider value={authContextValue}>
      <Component {...pageProps} />
    </AuthContext.Provider>
  );
}
