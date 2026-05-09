import { useEffect, useState } from 'react';

import { AppLayout } from '../../components/layout';
import { Badge, Button, Card, CardContent, Input } from '../../components/ui';
import { API_BASE } from '../../lib/auth';

export default function AdminUsersPage() {
  const [users, setUsers] = useState([]);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [resetModal, setResetModal] = useState({ open: false, userId: '', username: '' });
  const [resetPasswordValue, setResetPasswordValue] = useState('');
  const [resetConfirmValue, setResetConfirmValue] = useState('');
  const [resetError, setResetError] = useState('');
  const [resetSuccess, setResetSuccess] = useState('');
  const [resetting, setResetting] = useState(false);

  async function loadUsers() {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/admin/users`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setUsers(data.users || []);
    } catch (err) {
      setError(err.message || '加载用户失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  async function createNormalUser(e) {
    e.preventDefault();
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/admin/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, role: 'user' }),
      });
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}));
        throw new Error(payload.detail || `HTTP ${res.status}`);
      }
      setUsername('');
      setPassword('');
      await loadUsers();
    } catch (err) {
      setError(err.message || '创建用户失败');
    }
  }

  async function disableUser(userId) {
    const res = await fetch(`${API_BASE}/api/admin/users/${userId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'disabled' }),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.detail || `HTTP ${res.status}`);
    }
    await loadUsers();
  }

  async function enableUser(userId) {
    const res = await fetch(`${API_BASE}/api/admin/users/${userId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'active' }),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.detail || `HTTP ${res.status}`);
    }
    await loadUsers();
  }

  function openResetPasswordModal(userId, usernameText) {
    setResetModal({ open: true, userId, username: usernameText });
    setResetPasswordValue('');
    setResetConfirmValue('');
    setResetError('');
    setResetSuccess('');
  }

  function closeResetPasswordModal() {
    if (resetting) return;
    setResetModal({ open: false, userId: '', username: '' });
    setResetPasswordValue('');
    setResetConfirmValue('');
    setResetError('');
    setResetSuccess('');
  }

  async function resetPassword(e) {
    e?.preventDefault();
    setResetError('');
    setResetSuccess('');
    if (!resetPasswordValue || resetPasswordValue.length < 8) {
      setResetError('新密码至少 8 位');
      return;
    }
    if (resetPasswordValue !== resetConfirmValue) {
      setResetError('两次输入的新密码不一致');
      return;
    }
    setResetting(true);
    const res = await fetch(`${API_BASE}/api/admin/users/${resetModal.userId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: resetPasswordValue }),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      setResetError(payload.detail || `HTTP ${res.status}`);
      setResetting(false);
      return;
    }
    setResetSuccess('密码重置成功');
    setResetting(false);
    await loadUsers();
  }

  async function removeUser(userId) {
    const confirmed = window.confirm('确认删除该账号？');
    if (!confirmed) return;
    const res = await fetch(`${API_BASE}/api/admin/users/${userId}`, { method: 'DELETE' });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.detail || `HTTP ${res.status}`);
    }
    await loadUsers();
  }

  return (
    <AppLayout title="User management" description="管理员可创建、禁用或删除普通账号。">
      <div className="grid gap-6 xl:grid-cols-[1fr_1.2fr]">
        <Card>
          <CardContent className="space-y-4">
            <h2 className="m-0 text-lg font-semibold">Create user</h2>
            <form onSubmit={createNormalUser} className="space-y-3">
              <Input placeholder="用户名" value={username} onChange={(e) => setUsername(e.target.value)} />
              <Input placeholder="初始密码" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
              {error ? <div className="text-sm text-red-600">{error}</div> : null}
              <Button type="submit">创建普通账号</Button>
            </form>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="m-0 text-lg font-semibold">Users</h2>
              <Button variant="secondary" onClick={loadUsers}>{loading ? '刷新中...' : '刷新'}</Button>
            </div>
            <div className="space-y-2">
              {users.map((user) => (
                <div key={user.id} className="flex items-center justify-between rounded-lg border border-slate-200 p-3">
                  <div>
                    <div className="font-medium text-slate-900">{user.username}</div>
                    <div className="mt-1 flex gap-2">
                      <Badge tone={user.role === 'admin' ? 'primary' : 'default'}>{user.role}</Badge>
                      <Badge tone={user.status === 'active' ? 'success' : 'warning'}>{user.status}</Badge>
                    </div>
                  </div>
                  {user.role !== 'admin' ? (
                    <div className="flex gap-2">
                      {user.status === 'active' ? (
                        <Button variant="secondary" onClick={() => disableUser(user.id)}>禁用</Button>
                      ) : (
                        <Button variant="secondary" onClick={() => enableUser(user.id)}>启用</Button>
                      )}
                      <Button variant="secondary" onClick={() => openResetPasswordModal(user.id, user.username)}>重置密码</Button>
                      <Button variant="secondary" onClick={() => removeUser(user.id)}>删除</Button>
                    </div>
                  ) : null}
                </div>
              ))}
              {!users.length ? <div className="text-sm text-slate-500">暂无用户</div> : null}
            </div>
          </CardContent>
        </Card>
      </div>
      {resetModal.open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
          <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-5 shadow-xl">
            <div className="mb-4">
              <div className="text-lg font-semibold text-slate-900">重置用户密码</div>
              <div className="mt-1 text-sm text-slate-500">目标用户：{resetModal.username}</div>
            </div>
            <form className="space-y-3" onSubmit={resetPassword}>
              <Input
                type="password"
                placeholder="新密码（至少 8 位）"
                value={resetPasswordValue}
                onChange={(e) => setResetPasswordValue(e.target.value)}
              />
              <Input
                type="password"
                placeholder="确认新密码"
                value={resetConfirmValue}
                onChange={(e) => setResetConfirmValue(e.target.value)}
              />
              {resetError ? <div className="text-sm text-red-600">{resetError}</div> : null}
              {resetSuccess ? <div className="text-sm text-emerald-600">{resetSuccess}</div> : null}
              <div className="flex justify-end gap-2 pt-1">
                <Button type="button" variant="secondary" onClick={closeResetPasswordModal} disabled={resetting}>取消</Button>
                <Button type="submit" disabled={resetting}>{resetting ? '提交中...' : '确认重置'}</Button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </AppLayout>
  );
}

