import { useEffect, useState } from 'react';

import { AppLayout } from '../components/layout';
import { Badge, Button, Card, CardContent, Input } from '../components/ui';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/paperradar-api';

export default function SubscriptionsPage() {
  const [items, setItems] = useState([]);
  const [form, setForm] = useState({ name: '', query_text: '', threshold: 0.5 });
  const [loading, setLoading] = useState(false);

  async function loadSubscriptions() {
    const res = await fetch(`${API_BASE}/api/subscriptions`);
    const data = await res.json();
    setItems(data || []);
  }

  useEffect(() => {
    loadSubscriptions();
  }, []);

  async function createSubscription() {
    setLoading(true);
    try {
      await fetch(`${API_BASE}/api/subscriptions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      setForm({ name: '', query_text: '', threshold: 0.5 });
      await loadSubscriptions();
    } finally {
      setLoading(false);
    }
  }

  async function deleteSubscription(id) {
    await fetch(`${API_BASE}/api/subscriptions/${id}`, { method: 'DELETE' });
    await loadSubscriptions();
  }

  async function runMatching() {
    await fetch(`${API_BASE}/api/subscriptions/match`, { method: 'POST' });
    await loadSubscriptions();
  }

  return (
    <AppLayout
      title="Subscriptions"
      description="管理主题订阅、手动执行匹配，并查看命中与通知记录。"
      actions={<Button variant="secondary" onClick={runMatching}>Run matching now</Button>}
    >
      <div className="grid gap-6 xl:grid-cols-[1fr_1.3fr]">
        <Card>
          <CardContent className="space-y-4">
            <div>
              <h2 className="m-0 text-lg font-semibold">Create subscription</h2>
              <p className="mt-1 text-sm text-slate-500">用关键词定义一个长期关注主题，后续可命中新增论文。</p>
            </div>
            <Input placeholder="Subscription name" value={form.name} onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))} />
            <Input placeholder="Query text" value={form.query_text} onChange={(e) => setForm((prev) => ({ ...prev, query_text: e.target.value }))} />
            <Input type="number" step="0.1" min="0" max="1" value={form.threshold} onChange={(e) => setForm((prev) => ({ ...prev, threshold: Number(e.target.value) }))} />
            <Button onClick={createSubscription} disabled={loading}>{loading ? 'Creating...' : 'Create'}</Button>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="m-0 text-lg font-semibold">Active subscriptions</h2>
                <p className="mt-1 text-sm text-slate-500">当前已创建的订阅列表。</p>
              </div>
              <Badge tone="primary">{items.length} active</Badge>
            </div>

            <div className="space-y-3">
              {items.length ? items.map((item) => (
                <div key={item.id} className="rounded-xl border border-slate-200 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <div className="font-medium text-slate-900">{item.name}</div>
                      <div className="mt-1 text-sm text-slate-500">{item.query_text}</div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Badge>type: {item.type}</Badge>
                        <Badge tone="warning">threshold: {item.threshold}</Badge>
                      </div>
                    </div>
                    <Button variant="ghost" onClick={() => deleteSubscription(item.id)}>Delete</Button>
                  </div>
                </div>
              )) : (
                <div className="rounded-xl border border-dashed border-slate-200 p-6 text-sm text-slate-500">
                  还没有订阅。先创建一个主题订阅试试。
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </AppLayout>
  );
}
