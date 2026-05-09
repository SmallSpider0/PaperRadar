import { useEffect, useState } from 'react';
import { Activity, Database, Globe, ShieldCheck, Workflow } from 'lucide-react';

import { AppLayout } from '../components/layout';
import { StatCard } from '../components/stats';
import { Badge, Card, CardContent } from '../components/ui';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/paperradar-api';

const runtimeCards = [
  {
    title: 'Ingress & search',
    icon: Globe,
    desc: 'IEEE S&P / USENIX Security / CCS / NDSS 元数据抓取、标准化与 metadata search 已完成。',
  },
  {
    title: 'Storage & DB',
    icon: Database,
    desc: 'PostgreSQL 已接入，主数据与检索链路可运行。',
  },
  {
    title: 'Processing',
    icon: Workflow,
    desc: '支持按需全文抓取、PDF 解析、chunk 切分与 embedding。',
  },
  {
    title: 'Policy',
    icon: ShieldCheck,
    desc: '遵循 metadata-first / fulltext-on-demand 的内容边界。',
  },
];

export default function SystemPage() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const health = stats?.health || null;
  const papersByYear = stats?.papers?.by_year || [];
  const apiByEndpoint = stats?.api_usage?.by_endpoint || [];
  const llmByModel = stats?.llm_usage?.by_model || [];
  const retrievalQueue = stats?.retrieval_queue || health?.retrieval_queue || null;

  function formatCount(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number.toLocaleString() : '0';
  }

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError('');
      try {
        const res = await fetch(`${API_BASE}/api/system/stats?window=7d`);
        if (!res.ok) {
          throw new Error(`Request failed: ${res.status}`);
        }
        const data = await res.json();
        setStats(data);
      } catch (err) {
        setStats(null);
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  return (
    <AppLayout title="System status" description="当前服务运行状态、部署链路与产品能力边界。">
      <div className="space-y-6">
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Papers (total)" value={formatCount(stats?.papers?.total_count)} detail="from papers table" />
          <StatCard label="API calls (7d)" value={formatCount(stats?.api_usage?.total_calls)} detail="from api_usage_logs" />
          <StatCard label="Sessions (7d)" value={formatCount(stats?.sessions?.session_count)} detail="from rag_sessions" />
          <StatCard label="Queue pending" value={formatCount(retrievalQueue?.pending_jobs)} detail="retrieval queue depth" />
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
          <Card>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="m-0 text-lg font-semibold">Runtime overview</h2>
                  <p className="mt-1 text-sm text-slate-500">当前已上线能力与运行边界。</p>
                </div>
                <Badge tone={health?.status === 'ok' ? 'success' : 'warning'}>
                  {loading ? 'loading' : (health?.status || 'unavailable')}
                </Badge>
              </div>
              {error ? <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">Stats unavailable: {error}</div> : null}
              <div className="grid gap-4 md:grid-cols-2">
                {runtimeCards.map((item) => {
                  const Icon = item.icon;
                  return (
                    <div key={item.title} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                      <div className="mb-3 flex items-center gap-3">
                        <div className="rounded-lg bg-white p-2 text-blue-600 shadow-sm"><Icon size={18} /></div>
                        <div className="font-medium text-slate-900">{item.title}</div>
                      </div>
                      <div className="text-sm leading-6 text-slate-600">{item.desc}</div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-2 text-slate-900">
                <Activity size={18} />
                <h2 className="m-0 text-lg font-semibold">Live metrics</h2>
              </div>
              <div className="space-y-3 text-sm leading-6 text-slate-600">
                <div className="rounded-xl border border-slate-200 p-4">
                  <div className="font-medium text-slate-900">API health</div>
                  <div className="mt-1">
                    {health ? `${health.app || 'PaperRadar'} / ${health.env || 'prod'} / ${health.status || 'unknown'}` : 'Unavailable'}
                  </div>
                </div>
                <div className="rounded-xl border border-slate-200 p-4">
                  <div className="font-medium text-slate-900">Papers by year (Top 12)</div>
                  <div className="mt-2 space-y-1">
                    {papersByYear.length ? papersByYear.map((item) => (
                      <div key={`year-${item.year}`} className="flex items-center justify-between">
                        <span>{item.year}</span>
                        <span className="font-medium text-slate-900">{formatCount(item.count)}</span>
                      </div>
                    )) : <div className="text-slate-500">No data</div>}
                  </div>
                </div>
                <div className="rounded-xl border border-dashed border-slate-200 p-4">
                  <div className="font-medium text-slate-900">API calls by endpoint (7d)</div>
                  <div className="mt-2 space-y-1">
                    {apiByEndpoint.length ? apiByEndpoint.slice(0, 8).map((item) => (
                      <div key={`endpoint-${item.path}`} className="flex items-center justify-between gap-2">
                        <span className="truncate">{item.path}</span>
                        <span className="font-medium text-slate-900">{formatCount(item.count)}</span>
                      </div>
                    )) : <div className="text-slate-500">No data</div>}
                  </div>
                </div>
                <div className="rounded-xl border border-slate-200 p-4">
                  <div className="font-medium text-slate-900">LLM token usage (7d)</div>
                  <div className="mt-1 text-xs text-slate-500">
                    Prompt {formatCount(stats?.llm_usage?.prompt_tokens)} / Completion {formatCount(stats?.llm_usage?.completion_tokens)}
                  </div>
                  <div className="mt-2 space-y-1">
                    {llmByModel.length ? llmByModel.map((item) => (
                      <div key={`model-${item.model}`} className="flex items-center justify-between gap-2">
                        <span className="truncate">{item.model}</span>
                        <span className="font-medium text-slate-900">{formatCount(item.total_tokens)}</span>
                      </div>
                    )) : <div className="text-slate-500">No data</div>}
                  </div>
                </div>
                <div className="rounded-xl border border-slate-200 p-4">
                  <div className="font-medium text-slate-900">Retrieval queue</div>
                  <div className="mt-1 text-xs text-slate-500">
                    {retrievalQueue?.online ? 'Redis online' : 'Redis unavailable'}
                  </div>
                  <div className="mt-2 space-y-1">
                    <div className="flex items-center justify-between">
                      <span>pending</span>
                      <span className="font-medium text-slate-900">{formatCount(retrievalQueue?.pending_jobs)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>active</span>
                      <span className="font-medium text-slate-900">{formatCount(retrievalQueue?.active_jobs)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>max concurrency</span>
                      <span className="font-medium text-slate-900">{formatCount(retrievalQueue?.max_concurrency)}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>queue capacity</span>
                      <span className="font-medium text-slate-900">{formatCount(retrievalQueue?.queue_capacity)}</span>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </section>
      </div>
    </AppLayout>
  );
}
