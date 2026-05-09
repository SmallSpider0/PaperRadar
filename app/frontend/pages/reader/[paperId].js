import Link from 'next/link';
import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';

import { AppLayout } from '../../components/layout';
import { Badge, Card, CardContent } from '../../components/ui';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/paperradar-api';

export default function ReaderPage() {
  const router = useRouter();
  const { paperId } = router.query;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!paperId) return;

    let active = true;
    async function load() {
      setLoading(true);
      setError('');
      try {
        const res = await fetch(`${API_BASE}/api/reader/${paperId}`);
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const payload = await res.json();
        if (active) setData(payload);
      } catch (err) {
        if (active) setError(err.message || '加载失败');
      } finally {
        if (active) setLoading(false);
      }
    }

    load();
    return () => {
      active = false;
    };
  }, [paperId]);

  return (
    <AppLayout title="Reader" description="在浏览器中阅读已解析的论文 HTML 全文。">
      <div className="mb-4 text-sm text-slate-500"><Link href="/search">← Back to papers</Link></div>

      {loading && <Card><CardContent>正在加载阅读页…</CardContent></Card>}
      {error && (
        <Card>
          <CardContent>
            <h2 className="m-0 text-lg font-semibold">阅读页暂不可用</h2>
            <p className="mt-2 text-sm leading-6 text-slate-600">{error}</p>
            <p className="mt-2 text-sm text-slate-500">先在搜索页执行“抓取并解析”，再重新打开这里。</p>
          </CardContent>
        </Card>
      )}

      {data && (
        <div className="grid gap-6 xl:grid-cols-[1.8fr_1fr]">
          <div className="space-y-6">
            <Card>
              <CardContent>
                <div className="flex flex-wrap items-center gap-2">
                  {data.paper?.venue_code ? <Badge tone="primary">{data.paper.venue_code}</Badge> : null}
                  {data.paper?.year ? <Badge>{data.paper.year}</Badge> : null}
                  {data.status?.fulltext_status ? <Badge tone="success">{data.status.fulltext_status}</Badge> : null}
                </div>
                <h1 className="mt-4 text-2xl font-semibold tracking-tight">{data.paper?.title || data.paper_id}</h1>
                {data.paper?.abstract ? <p className="mt-4 text-sm leading-7 text-slate-600">{data.paper.abstract}</p> : null}
                <div className="mt-4 flex flex-wrap gap-4 text-sm text-blue-600">
                  {data.paper?.paper_url ? <a href={data.paper.paper_url} target="_blank" rel="noreferrer">Original paper page</a> : null}
                  {data.status?.source_url ? <a href={data.status.source_url} target="_blank" rel="noreferrer">Fulltext source</a> : null}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <h2 className="m-0 text-lg font-semibold">Reading preview</h2>
                <div className="mt-4 space-y-4">
                  {(data.preview?.paragraphs || []).length ? data.preview.paragraphs.map((paragraph, index) => (
                    <p key={`${index}-${paragraph.slice(0, 20)}`} className="m-0 text-sm leading-8 text-slate-700">{paragraph}</p>
                  )) : <div className="text-sm text-slate-500">暂无预览文本。</div>}
                </div>
              </CardContent>
            </Card>
          </div>

          <div className="space-y-6">
            <Card>
              <CardContent>
                <h2 className="m-0 text-lg font-semibold">Reader status</h2>
                <div className="mt-4 space-y-3 text-sm text-slate-600">
                  <div>paper_id: <span className="font-mono text-slate-900">{data.paper_id}</span></div>
                  <div>chunk_count: <span className="font-medium text-slate-900">{data.chunk_count}</span></div>
                  <div>parsed_path: <span className="font-mono text-xs text-slate-500">{data.status?.parsed_path}</span></div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <h2 className="m-0 text-lg font-semibold">Chunk preview</h2>
                <div className="mt-4 space-y-3">
                  {(data.chunks || []).slice(0, 8).map((chunk) => (
                    <div key={chunk.chunk_index} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                      <div className="mb-2 text-xs font-medium text-slate-500">chunk #{chunk.chunk_index}</div>
                      <div className="text-sm leading-6 text-slate-700">{chunk.text}</div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </AppLayout>
  );
}
