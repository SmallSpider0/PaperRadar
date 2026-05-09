import Link from 'next/link';
import { Bell, Database, FileText, MessageSquareQuote, SearchCheck, ShieldCheck } from 'lucide-react';

import { AppLayout } from '../components/layout';
import { StatCard } from '../components/stats';
import { Badge, Card, CardContent } from '../components/ui';

const capabilities = [
  {
    title: 'Metadata crawling',
    icon: Database,
    desc: '已完成 IEEE S&P / USENIX Security / CCS / NDSS 元数据抓取、标准化与入库。',
  },
  {
    title: 'Semantic search',
    icon: SearchCheck,
    desc: '支持 metadata 检索，接入 embedding 与关键词 fallback。',
  },
  {
    title: 'On-demand fulltext',
    icon: FileText,
    desc: '遵循 metadata-first / fulltext-on-demand，不默认批量抓全文。',
  },
  {
    title: 'Research chat',
    icon: MessageSquareQuote,
    desc: '基于元数据与摘要的智能检索与多轮对话，可按需结合全文解析结果。',
  },
  {
    title: 'Subscriptions',
    icon: Bell,
    desc: '支持主题订阅、匹配、命中记录与通知链路。',
  },
  {
    title: 'Hosted service',
    icon: ShieldCheck,
    desc: '数据持久化于 PostgreSQL，经 HTTPS 提供服务，便于团队内网使用。',
  },
];

const quickStart = [
  {
    href: '/search',
    title: 'Papers',
    text: '按关键词或语义检索已收录论文；当前不开放抓取解析与阅读页入口。',
  },
  {
    href: '/chat',
    title: 'Chat Search',
    text: '用自然语言提问，查看检索预览、结构化引用与可点击的论文条目。',
  },
  {
    href: '/subscriptions',
    title: 'Subscriptions',
    text: '创建主题订阅、手动运行匹配，并查看命中与通知记录。',
  },
  {
    href: null,
    title: 'Reader',
    text: 'HTML 阅读页当前暂时禁用，恢复后再开放入口。',
  },
];

export default function Home() {
  return (
    <AppLayout
      title="PaperRadar Dashboard"
      description="安全顶会论文跟踪与语义检索：按需全文、主题订阅，以及对话式研究助手。"
    >
      <div className="space-y-6">
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Service status" value="Live" detail="HTTPS 已启用" />
          <StatCard label="Supported venues" value="4" detail="IEEE S&P / USENIX Security / CCS / NDSS" />
          <StatCard label="Retrieval" value="Ready" detail="metadata + embedding + filters" />
          <StatCard label="Research chat" value="Available" detail="检索预览、引用与多轮对话" />
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
          <Card>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="m-0 text-lg font-semibold">What the current system already delivers</h2>
                  <p className="mt-1 text-sm text-slate-500">检索论文并用对话追问要点与引用来源；全文解析与阅读入口当前暂时关闭。</p>
                </div>
                <div className="flex gap-2">
                  <Badge tone="success">metadata-first</Badge>
                  <Badge tone="primary">fulltext-on-demand</Badge>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                {capabilities.map((item) => {
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
              <div>
                <h2 className="m-0 text-lg font-semibold">Quick start</h2>
                <p className="mt-1 text-sm text-slate-500">从下列入口开始使用主要功能。</p>
              </div>
              <div className="space-y-3 text-sm text-slate-600">
                {quickStart.map((item) => (
                  <div key={item.title} className="rounded-xl border border-slate-200 p-4">
                    <div className="font-medium text-slate-900">
                      {item.href ? (
                        <Link href={item.href} className="text-blue-600 hover:underline">
                          {item.title}
                        </Link>
                      ) : (
                        item.title
                      )}
                    </div>
                    <div className="mt-1">{item.text}</div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </section>
      </div>
    </AppLayout>
  );
}
