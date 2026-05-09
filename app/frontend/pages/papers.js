import { useState } from 'react';

import { AppLayout } from '../components/layout';
import { Badge, Button, Card, CardContent, Input } from '../components/ui';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/paperradar-api';

export default function PapersPage() {
  const [paperUrl, setPaperUrl] = useState('https://www.usenix.org/conference/usenixsecurity25/presentation/agarwal-shubham');
  const [status, setStatus] = useState(null);

  async function fetchFulltext() {
    const res = await fetch(`${API_BASE}/api/fulltext/fetch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_url: paperUrl }),
    });
    const data = await res.json();
    setStatus(data);
  }

  async function parseFulltext() {
    if (!status?.paper_id) return;
    const res = await fetch(`${API_BASE}/api/fulltext/parse/${status.paper_id}`, {
      method: 'POST',
    });
    const data = await res.json();
    setStatus(data);
  }

  return (
    <AppLayout title="Fulltext tools" description="针对单篇论文执行全文抓取、解析和阅读跳转，适合调试和人工触发链路。">
      <div className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
        <Card>
          <CardContent className="space-y-4">
            <div>
              <h2 className="m-0 text-lg font-semibold">Run fulltext pipeline</h2>
              <p className="mt-1 text-sm text-slate-500">全文抓取、解析与阅读跳转当前暂时禁用，这里仅保留状态展示。</p>
            </div>
            <Input value={paperUrl} onChange={(e) => setPaperUrl(e.target.value)} disabled />
            <div className="flex flex-wrap gap-3">
              <Button disabled>Fetch fulltext（暂时禁用）</Button>
              <Button variant="secondary" disabled>Parse fulltext（暂时禁用）</Button>
              <Button variant="ghost" disabled>Open reader（暂时禁用）</Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-3">
            <h2 className="m-0 text-lg font-semibold">Pipeline policy</h2>
            <div className="flex flex-wrap gap-2">
              <Badge tone="primary">metadata-first</Badge>
              <Badge tone="warning">on-demand only</Badge>
            </div>
            <ul className="m-0 space-y-2 pl-5 text-sm leading-6 text-slate-600">
              <li>普通搜索不会偷偷下载 PDF。</li>
              <li>只有显式触发才会抓全文。</li>
              <li>当前前端已临时关闭抓取、解析与 HTML 阅读页入口。</li>
            </ul>
          </CardContent>
        </Card>
      </div>

      {status ? (
        <Card className="mt-6">
          <CardContent>
            <h2 className="m-0 text-lg font-semibold">Latest status</h2>
            <pre className="mt-4 overflow-auto rounded-xl bg-slate-950 p-4 text-sm text-slate-100">{JSON.stringify(status, null, 2)}</pre>
          </CardContent>
        </Card>
      ) : null}
    </AppLayout>
  );
}
