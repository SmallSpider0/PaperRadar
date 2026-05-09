import { ArrowUpRight } from 'lucide-react';

import { Card, CardContent } from './ui';

export function StatCard({ label, value, detail }) {
  return (
    <Card>
      <CardContent>
        <div className="text-sm text-slate-500">{label}</div>
        <div className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">{value}</div>
        {detail ? <div className="mt-3 flex items-center gap-1 text-sm text-slate-500"><ArrowUpRight size={14} /> {detail}</div> : null}
      </CardContent>
    </Card>
  );
}
