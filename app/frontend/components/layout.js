import Link from 'next/link';
import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import { Bell, Database, FileSearch, LayoutDashboard, MessageSquareQuote, PanelLeftClose, PanelLeftOpen, Radar, User } from 'lucide-react';

import { cn } from '../lib/utils';
import { API_BASE, canAccessPath, useAuth } from '../lib/auth';
import { Button, Card, CardContent, Input, PageShell } from './ui';

const navItems = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard, roles: ['user', 'admin'] },
  { href: '/chat', label: 'Chat Search', icon: MessageSquareQuote, roles: ['user', 'admin'] },
  { href: '/search', label: 'Papers', icon: FileSearch, roles: ['user', 'admin'] },
  { href: '/subscriptions', label: 'Subscriptions', icon: Bell, roles: ['user', 'admin'] },
  { href: '/user', label: 'User', icon: User, roles: ['user'] },
  { href: '/papers', label: 'Fulltext Tools', icon: Database, roles: ['admin'] },
  { href: '/system', label: 'System', icon: Radar, roles: ['admin'] },
  { href: '/admin/users', label: 'Users', icon: Bell, roles: ['admin'] },
];

export function AppLayout({ title, description, actions, children, sidebarExtra }) {
  const router = useRouter();
  const { user, setUser } = useAuth();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showCollapseBtn, setShowCollapseBtn] = useState(true);
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState('');
  const [changingPassword, setChangingPassword] = useState(false);
  const role = user?.role || 'user';
  const visibleItems = navItems.filter((item) => item.roles.includes(role) && canAccessPath(role, item.href));

  async function logout() {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST' });
    } finally {
      setUser(null);
      router.push('/login');
    }
  }

  function openPasswordModal() {
    setPasswordError('');
    setPasswordSuccess('');
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setShowPasswordModal(true);
  }

  function closePasswordModal() {
    if (changingPassword) return;
    setShowPasswordModal(false);
  }

  async function changeOwnPassword(e) {
    e?.preventDefault();
    setPasswordError('');
    setPasswordSuccess('');
    if (!currentPassword) {
      setPasswordError('请输入当前密码');
      return;
    }
    if (newPassword.length < 8) {
      setPasswordError('新密码至少 8 位');
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError('两次输入的新密码不一致');
      return;
    }
    setChangingPassword(true);
    const res = await fetch(`${API_BASE}/api/auth/password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      setPasswordError(payload.detail || `修改失败: HTTP ${res.status}`);
      setChangingPassword(false);
      return;
    }
    setPasswordSuccess('密码修改成功');
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setChangingPassword(false);
  }

  useEffect(() => {
    if (sidebarCollapsed) {
      setShowCollapseBtn(false);
      return;
    }
    const timer = setTimeout(() => setShowCollapseBtn(true), 180);
    return () => clearTimeout(timer);
  }, [sidebarCollapsed]);

  const sidebar = (
    <div className="sticky top-6 space-y-4">
      <Card>
        <CardContent className="relative py-3">
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              className="group inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white transition hover:bg-blue-700 hover:shadow-sm"
              onClick={() => (sidebarCollapsed ? setSidebarCollapsed(false) : undefined)}
              title={sidebarCollapsed ? '展开侧边栏' : 'PaperRadar'}
            >
              {sidebarCollapsed ? (
                <>
                  <Radar size={18} className="block group-hover:hidden" />
                  <PanelLeftOpen size={18} className="hidden group-hover:block" />
                </>
              ) : (
                <Radar size={18} />
              )}
            </button>
            <div
              className={cn(
                'pointer-events-none absolute left-[5.35rem] top-1/2 -translate-y-1/2 whitespace-nowrap transition-opacity duration-100',
                sidebarCollapsed ? 'opacity-0' : 'opacity-100'
              )}
            >
              <div className="text-2xl font-semibold">PaperRadar</div>
            </div>
            {!sidebarCollapsed && showCollapseBtn ? (
              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
                onClick={() => setSidebarCollapsed(true)}
                title="收起侧边栏"
              >
                <PanelLeftClose size={17} />
              </button>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-2">
          {visibleItems.map((item) => {
            const Icon = item.icon;
            const active = router.pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'relative flex items-center rounded-lg px-3 py-2 text-sm transition',
                  active ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                )}
                title={item.label}
              >
                <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center">
                  <Icon size={16} className="shrink-0" />
                </span>
                <span
                  className={cn(
                    'pointer-events-none absolute left-10 top-1/2 -translate-y-1/2 whitespace-nowrap transition-opacity duration-100',
                    sidebarCollapsed ? 'opacity-0' : 'opacity-100'
                  )}
                >
                  {item.label}
                </span>
              </Link>
            );
          })}
        </CardContent>
      </Card>

      {sidebarExtra && !sidebarCollapsed ? sidebarExtra : null}
      {!sidebarCollapsed && (router.pathname === '/admin/users' || router.pathname === '/user') ? (
        <Card>
          <CardContent className="space-y-4 p-4">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
              <div className="text-base font-semibold text-slate-900">{user?.username || 'unknown'}</div>
              <div className="mt-2 inline-flex items-center rounded-full bg-blue-100 px-2.5 py-1 text-xs font-medium text-blue-700">
                {role === 'admin' ? '管理员' : '普通用户'}
              </div>
            </div>
            <div className="grid gap-2">
              <button
                type="button"
                onClick={openPasswordModal}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
              >
                修改密码
              </button>
              <button
                type="button"
                onClick={logout}
                className="w-full rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-left text-sm font-medium text-red-700 transition hover:border-red-300 hover:bg-red-100"
              >
                退出登录
              </button>
            </div>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );

  const header = (
    <Card>
      <CardContent className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="m-0 text-2xl font-semibold tracking-tight">{title}</h1>
          {description ? <p className="mt-2 text-sm text-slate-500">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-3">{actions}</div> : null}
      </CardContent>
    </Card>
  );

  return (
    <>
      <PageShell sidebar={sidebar} header={header} sidebarCollapsed={sidebarCollapsed}>{children}</PageShell>
      {showPasswordModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/35 p-4">
          <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-5 shadow-xl">
            <div className="mb-4">
              <div className="text-lg font-semibold text-slate-900">修改密码</div>
              <div className="mt-1 text-sm text-slate-500">当前账号：{user?.username || 'unknown'}</div>
            </div>
            <form className="space-y-3" onSubmit={changeOwnPassword}>
              <Input type="password" placeholder="当前密码" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
              <Input type="password" placeholder="新密码（至少 8 位）" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
              <Input type="password" placeholder="确认新密码" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
              {passwordError ? <div className="text-sm text-red-600">{passwordError}</div> : null}
              {passwordSuccess ? <div className="text-sm text-emerald-600">{passwordSuccess}</div> : null}
              <div className="flex justify-end gap-2 pt-1">
                <Button type="button" variant="secondary" onClick={closePasswordModal} disabled={changingPassword}>取消</Button>
                <Button type="submit" disabled={changingPassword}>{changingPassword ? '提交中...' : '确认修改'}</Button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
