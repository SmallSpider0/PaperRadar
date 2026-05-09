import { useState } from 'react';
import { useRouter } from 'next/router';

import { API_BASE, useAuth } from '../lib/auth';
import { Button, Card, CardContent, Input } from '../components/ui';

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function onSubmit(e) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(payload.detail || `HTTP ${res.status}`);
      }
      await refresh();
      const next = typeof router.query.next === 'string' ? router.query.next : '/';
      router.replace(next || '/');
    } catch (err) {
      setError(err.message || '登录失败');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <Card className="w-full max-w-md">
        <CardContent className="space-y-4">
          <div>
            <h1 className="m-0 text-2xl font-semibold text-slate-900">PaperRadar Login</h1>
            <p className="mt-2 text-sm text-slate-500">请使用管理员或普通账号登录。</p>
          </div>
          <form onSubmit={onSubmit} className="space-y-3">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="用户名" />
            <Input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="密码" type="password" />
            {error ? <div className="text-sm text-red-600">{error}</div> : null}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? '登录中...' : '登录'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

