import { useEffect, useRef, useState } from 'react';
import { MoreHorizontal } from 'lucide-react';

import { AppLayout } from '../components/layout';
import { Badge, Button, Card, CardContent, Input } from '../components/ui';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/paperradar-api';

function clampProgress(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(value, 1));
}

function formatEta(seconds) {
  if (typeof seconds !== 'number' || Number.isNaN(seconds) || seconds <= 0) return null;
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  return `${Math.round(seconds)}s`;
}

function formatSessionMeta(session) {
  if (!session) return '未创建';
  const title = session.title || session.query || session.id;
  return `${title} · ${session.status || 'prepared'}`;
}

function formatTokenCount(value) {
  const num = Number(value || 0);
  if (!Number.isFinite(num)) return '0';
  return num.toLocaleString('en-US');
}

function renderCitationLabel(label) {
  return label ? `[${label}]` : '[ref]';
}

function escapeHtml(value) {
  return String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function renderInlineMarkdownToHtml(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  return html;
}

function renderMarkdownToHtml(markdown) {
  const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let paragraphLines = [];
  let listItems = [];
  let listType = null;

  function flushParagraph() {
    if (!paragraphLines.length) return;
    blocks.push(`<p>${renderInlineMarkdownToHtml(paragraphLines.join(' '))}</p>`);
    paragraphLines = [];
  }

  function flushList() {
    if (!listItems.length || !listType) return;
    const tag = listType === 'ol' ? 'ol' : 'ul';
    blocks.push(`<${tag}>${listItems.map((item) => `<li>${renderInlineMarkdownToHtml(item)}</li>`).join('')}</${tag}>`);
    listItems = [];
    listType = null;
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }

    if (line === '---' || line === '***') {
      flushParagraph();
      flushList();
      blocks.push('<hr />');
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = Math.min(6, headingMatch[1].length);
      blocks.push(`<h${level}>${renderInlineMarkdownToHtml(headingMatch[2])}</h${level}>`);
      continue;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listType && listType !== 'ol') flushList();
      listType = 'ol';
      listItems.push(orderedMatch[1]);
      continue;
    }

    const unorderedMatch = line.match(/^[-*]\s+(.*)$/);
    if (unorderedMatch) {
      flushParagraph();
      if (listType && listType !== 'ul') flushList();
      listType = 'ul';
      listItems.push(unorderedMatch[1]);
      continue;
    }

    flushList();
    paragraphLines.push(line);
  }

  flushParagraph();
  flushList();
  return blocks.join('');
}

function MarkdownArticle({ content }) {
  return (
    <div
      className={[
        'mt-3 text-sm leading-7 text-slate-700',
        '[&_h1]:mt-8 [&_h1]:text-3xl [&_h1]:font-semibold [&_h1]:leading-tight [&_h1]:text-slate-950',
        '[&_h2]:mt-7 [&_h2]:text-2xl [&_h2]:font-semibold [&_h2]:leading-tight [&_h2]:text-slate-900',
        '[&_h3]:mt-6 [&_h3]:text-xl [&_h3]:font-semibold [&_h3]:leading-tight [&_h3]:text-slate-900',
        '[&_h4]:mt-5 [&_h4]:text-lg [&_h4]:font-semibold [&_h4]:text-slate-900',
        '[&_p]:mt-3 [&_p]:leading-7',
        '[&_ul]:mt-3 [&_ul]:list-disc [&_ul]:pl-6',
        '[&_ol]:mt-3 [&_ol]:list-decimal [&_ol]:pl-6',
        '[&_li]:mt-1 [&_li]:leading-7',
        '[&_hr]:my-6 [&_hr]:border-slate-200',
        '[&_strong]:font-semibold [&_strong]:text-slate-900',
        '[&_em]:italic',
        '[&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-[0.92em]',
        '[&_a]:text-blue-700 [&_a]:underline [&_a]:underline-offset-2 hover:[&_a]:text-blue-800',
      ].join(' ')}
      dangerouslySetInnerHTML={{ __html: renderMarkdownToHtml(content) }}
    />
  );
}

function MessageCitations({ citations = [] }) {
  if (!citations.length) return null;
  return (
    <div className="mt-3 grid gap-2">
      {citations.map((item) => {
        const href = item.paper_url || item.pdf_url || null;
        return (
          <div key={item.id || item.paper_id || item.title} className="rounded-xl border border-slate-200 bg-white/80 p-3 text-xs text-slate-700">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="primary">{renderCitationLabel(item.label)}</Badge>
              {item.role ? <Badge>{item.role}</Badge> : null}
              {item.venue_code ? <Badge>{item.venue_code}</Badge> : null}
              {item.year ? <Badge>{item.year}</Badge> : null}
            </div>
            <div className="mt-2 font-medium text-slate-900">
              {href ? <a href={href} target="_blank" rel="noreferrer" className="hover:text-blue-700 hover:underline">{item.title}</a> : item.title}
            </div>
            {item.relevance_note || item.snippet ? (
              <div className="mt-2 leading-6 text-slate-600">{item.relevance_note || item.snippet}</div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function PaperList({ title, papers = [], emptyText }) {
  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="text-sm font-medium text-slate-900">{title}</div>
        {papers.length ? (
          <div className="grid gap-3">
            {papers.map((item) => (
              <div key={item.paper_id || item.title} className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                <div className="flex flex-wrap gap-2">
                  {item.venue_code ? <Badge>{item.venue_code}</Badge> : null}
                  {item.year ? <Badge>{item.year}</Badge> : null}
                  {item.decision ? <Badge tone={item.decision === 'exclude' ? 'warning' : 'success'}>{item.decision}</Badge> : null}
                </div>
                <div className="mt-2 font-medium text-slate-900">
                  {item.paper_url ? <a href={item.paper_url} target="_blank" rel="noreferrer" className="hover:text-blue-700 hover:underline">{item.title}</a> : item.title}
                </div>
                {item.decision_reason ? <div className="mt-2 text-xs text-slate-600">{item.decision_reason}</div> : null}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-slate-500">{emptyText}</div>
        )}
      </CardContent>
    </Card>
  );
}

function PreviewPaperCards({ results = [] }) {
  if (!results.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 p-6 text-sm text-slate-500">
        暂无候选论文。
      </div>
    );
  }
  return (
    <div className="grid gap-4">
      {results.map((item) => (
        <Card key={item.paper_url || item.paper_id || item.title}>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              <Badge tone="primary">score {Number(item.score || 0).toFixed(4)}</Badge>
              {item.venue_code ? <Badge>{item.venue_code}</Badge> : null}
              {item.year ? <Badge>{item.year}</Badge> : null}
            </div>
            <div className="mt-3 text-lg font-semibold text-slate-900">
              {item.paper_url ? <a href={item.paper_url} target="_blank" rel="noreferrer" className="hover:text-blue-700 hover:underline">{item.title}</a> : item.title}
            </div>
            {item.abstract ? <p className="mt-3 text-sm leading-7 text-slate-600">{item.abstract}</p> : null}
            {item.relevance?.why_matched?.length ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {item.relevance.why_matched.map((reason) => <Badge key={reason} tone="success">{reason}</Badge>)}
              </div>
            ) : item.match_reasons?.length ? (
              <div className="mt-4 flex flex-wrap gap-2">
                {item.match_reasons.map((reason) => <Badge key={reason} tone="success">{reason}</Badge>)}
              </div>
            ) : null}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function ChatPage() {
  const [query, setQuery] = useState('');
  const [loadingPrepare, setLoadingPrepare] = useState(false);
  const [loadingGenerate, setLoadingGenerate] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState('');
  const [reviewSessionId, setReviewSessionId] = useState('');
  const [reviewDetail, setReviewDetail] = useState(null);
  const [sessions, setSessions] = useState([]);
  const [error, setError] = useState('');
  const [managingSession, setManagingSession] = useState(null);
  const [jobProgress, setJobProgress] = useState(null);
  const reviewStreamRef = useRef(null);
  const reviewTokenRef = useRef(0);

  function closeReviewStream() {
    if (reviewStreamRef.current) {
      reviewStreamRef.current.close();
      reviewStreamRef.current = null;
    }
  }

  function applyReviewDetail(detail, { keepQuery = true } = {}) {
    const nextSessionId = detail?.session?.id || '';
    setReviewSessionId(nextSessionId);
    setReviewDetail(detail || null);
    if (!keepQuery) {
      setQuery(detail?.session?.query || '');
    }
  }

  async function loadSessions(activeSessionId = '') {
    setLoadingSessions(true);
    try {
      const res = await fetch(`${API_BASE}/api/review/sessions?limit=20`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSessions(data.sessions || []);
      if (!reviewSessionId && activeSessionId) {
        setReviewSessionId(activeSessionId);
      }
    } catch (err) {
      setError((prev) => prev || err.message || '加载综述会话失败');
    } finally {
      setLoadingSessions(false);
    }
  }

  async function loadSessionDetail(targetSessionId) {
    if (!targetSessionId) return;
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/review/sessions/${targetSessionId}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      applyReviewDetail(data, { keepQuery: false });
      setJobProgress(null);
    } catch (err) {
      setError(err.message || '加载综述会话失败');
    }
  }

  useEffect(() => {
    loadSessions();
  }, []);

  useEffect(() => () => closeReviewStream(), []);

  async function waitForJob(jobPath, jobId, requestToken, onCompleted) {
    return new Promise((resolve, reject) => {
      const events = new EventSource(`${API_BASE}${jobPath}/${jobId}/events`, { withCredentials: true });
      reviewStreamRef.current = events;

      events.onmessage = async (event) => {
        if (requestToken !== reviewTokenRef.current) {
          closeReviewStream();
          resolve(null);
          return;
        }
        const payload = JSON.parse(event.data);
        setJobProgress(payload);
        if (payload.status === 'completed') {
          closeReviewStream();
          await onCompleted(payload.result || null);
          setError('');
          resolve(payload.result || null);
          return;
        }
        if (payload.status === 'error') {
          closeReviewStream();
          reject(new Error(payload.error || payload.message || '请求失败'));
        }
      };

      events.onerror = async () => {
        if (requestToken !== reviewTokenRef.current) {
          closeReviewStream();
          resolve(null);
          return;
        }
        closeReviewStream();
        try {
          const res = await fetch(`${API_BASE}${jobPath}/${jobId}`);
          const payload = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(payload.detail || `HTTP ${res.status}`);
          }
          setJobProgress(payload);
          if (payload.status === 'completed') {
            await onCompleted(payload.result || null);
            resolve(payload.result || null);
            return;
          }
          if (payload.status === 'error') {
            reject(new Error(payload.error || payload.message || '请求失败'));
            return;
          }
        } catch (err) {
          reject(err);
          return;
        }
        reject(new Error('任务进度连接中断'));
      };
    });
  }

  async function runPrepare(e) {
    e?.preventDefault();
    if (!query.trim()) return;
    setError('');
    const requestToken = reviewTokenRef.current + 1;
    reviewTokenRef.current = requestToken;
    closeReviewStream();
    setLoadingPrepare(true);
    setJobProgress({
      status: 'queued',
      stage: 'queued',
      message: '综述候选准备已入队',
      progress: 0.02,
      query,
    });
    try {
      const res = await fetch(`${API_BASE}/api/review/prepare/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, preview_limit: 20, candidate_limit: 60 }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setJobProgress(data);
      await waitForJob('/api/review/prepare/jobs', data.job_id, requestToken, async (result) => {
        applyReviewDetail(result);
        await loadSessions(result?.session?.id || '');
      });
    } catch (err) {
      setError(err.message || '请求失败');
    } finally {
      if (requestToken === reviewTokenRef.current) {
        setLoadingPrepare(false);
      }
    }
  }

  async function runGenerate(e) {
    e?.preventDefault();
    if (!reviewSessionId) return;
    const requestToken = reviewTokenRef.current + 1;
    reviewTokenRef.current = requestToken;
    closeReviewStream();
    setLoadingGenerate(true);
    setError('');
    setJobProgress({
      status: 'queued',
      stage: 'queued',
      message: '中文综述任务已入队',
      progress: 0.02,
      review_session_id: reviewSessionId,
    });
    try {
      const res = await fetch(`${API_BASE}/api/review/generate/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ review_session_id: reviewSessionId, confirmed: true }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      setJobProgress(data);
      await waitForJob('/api/review/generate/jobs', data.job_id, requestToken, async (result) => {
        applyReviewDetail(result);
        await loadSessions(result?.session?.id || '');
      });
    } catch (err) {
      setError(err.message || '请求失败');
    } finally {
      if (requestToken === reviewTokenRef.current) {
        setLoadingGenerate(false);
      }
    }
  }

  async function deleteSession(targetSessionId) {
    if (!targetSessionId || deletingSessionId) return;
    const confirmed = window.confirm('确认永久删除这个综述会话吗？删除后不可恢复。');
    if (!confirmed) return;

    setDeletingSessionId(targetSessionId);
    setError('');
    try {
      const res = await fetch(`${API_BASE}/api/review/sessions/${targetSessionId}`, {
        method: 'DELETE',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }

      const remaining = sessions.filter((item) => item.id !== targetSessionId);
      setSessions(remaining);

      if (reviewSessionId === targetSessionId) {
        if (remaining.length) {
          await loadSessionDetail(remaining[0].id);
        } else {
          resetReview();
        }
      }
      setManagingSession(null);
    } catch (err) {
      setError(err.message || '删除综述会话失败');
    } finally {
      setDeletingSessionId('');
    }
  }

  function resetReview() {
    closeReviewStream();
    setReviewSessionId('');
    setReviewDetail(null);
    setJobProgress(null);
    setError('');
    setQuery('');
  }

  const activeSession = sessions.find((item) => item.id === reviewSessionId) || reviewDetail?.session || null;
  const prepared = reviewDetail?.prepared || null;
  const review = reviewDetail?.review || null;
  const answerSummary = review?.answer_summary || {};
  const totalTokenUsage = answerSummary.token_usage || {};
  const filterTokenUsage = answerSummary.filter_token_usage || {};
  const synthesisTokenUsage = answerSummary.synthesis_token_usage || {};
  const canGenerate = Boolean(reviewSessionId && prepared && !review && !loadingPrepare && !loadingGenerate);
  const progressValue = clampProgress(jobProgress?.progress);
  const progressPercent = Math.round(progressValue * 100);
  const etaLabel = formatEta(jobProgress?.eta_seconds);
  const queueLabel = jobProgress?.status === 'queued' && typeof jobProgress?.queue_ahead === 'number'
    ? `前方 ${jobProgress.queue_ahead} 个任务`
    : '';
  const parallelLabel = jobProgress?.variant_total
    ? `并行检索 ${jobProgress.completed_variants || 0}/${jobProgress.variant_total}${jobProgress?.active_variants?.length ? ` · 运行中 ${jobProgress.active_variants.length} 个` : ''}`
    : '';
  const chunkLabel = jobProgress?.total_chunks
    ? `分片 ${jobProgress.completed_chunks || 0}/${jobProgress.total_chunks}`
    : '';
  const candidateLabel = jobProgress?.candidate_count ? `${jobProgress.candidate_count} 条候选` : '';
  const progressMeta = queueLabel || parallelLabel || chunkLabel || candidateLabel;
  const sidebarExtra = (
    <Card>
      <CardContent className="space-y-3">
        <div className="text-sm font-semibold text-slate-900">Review Sessions</div>
        <div className="flex gap-2">
          <Button type="button" className="flex-1" onClick={resetReview}>新建综述</Button>
          <Button type="button" variant="secondary" onClick={() => loadSessions()}>
            {loadingSessions ? '刷新中…' : '刷新'}
          </Button>
        </div>
        <div className="max-h-[52vh] space-y-2 overflow-y-auto pr-1">
          {managingSession ? (
            <div className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
              <div className="truncate font-medium text-slate-900">{managingSession.title || managingSession.query || managingSession.id}</div>
              <div className="mt-3 grid gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  className="justify-start px-2 py-2 text-sm text-red-600 hover:bg-red-50 hover:text-red-700"
                  onClick={() => deleteSession(managingSession.id)}
                  disabled={deletingSessionId === managingSession.id}
                >
                  {deletingSessionId === managingSession.id ? '删除中…' : '删除会话'}
                </Button>
                <Button type="button" variant="secondary" className="justify-start px-2 py-2 text-sm" onClick={() => setManagingSession(null)}>
                  返回会话列表
                </Button>
              </div>
            </div>
          ) : sessions.length ? sessions.map((session) => {
            const isActive = session.id === reviewSessionId;
            return (
              <div
                key={session.id}
                className={`rounded-xl border px-2 py-1.5 text-left text-sm transition ${isActive ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
              >
                <div className="flex items-center gap-1">
                  <button type="button" onClick={() => loadSessionDetail(session.id)} className="min-w-0 flex-1 text-left">
                    <div className="truncate font-medium text-slate-900">{session.title || session.query || session.id}</div>
                    <div className="mt-0.5 text-xs text-slate-500">{session.status} · {session.included_count || 0} included</div>
                  </button>
                  <button
                    type="button"
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
                    onClick={() => setManagingSession(session)}
                    title="会话操作"
                  >
                    <MoreHorizontal size={15} />
                  </button>
                </div>
              </div>
            );
          }) : (
            <div className="rounded-xl border border-dashed border-slate-200 p-4 text-sm text-slate-500">暂无历史综述</div>
          )}
        </div>
      </CardContent>
    </Card>
  );

  return (
    <AppLayout
      title="Chat Search"
      description="先确认候选论文，再生成尽可能完整的中文文献综述。"
      sidebarExtra={sidebarExtra}
    >
      <div className="h-[calc(100vh-220px)] min-h-[640px] overflow-hidden rounded-2xl border border-slate-200 bg-white">
        <div className="flex h-full min-h-0">
          <section className="flex min-w-0 flex-1 flex-col">
            <div className="border-b border-slate-200 px-4 py-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span>review_session_id: {reviewSessionId || '未创建'}</span>
                <span>status: {reviewDetail?.session?.status || 'idle'}</span>
                <span>active: {formatSessionMeta(activeSession)}</span>
              </div>
              {(loadingPrepare || loadingGenerate) && jobProgress ? (
                <div className="mt-3 space-y-2">
                  <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                    <span className="truncate">{jobProgress.search_message || jobProgress.message || '处理中'}</span>
                    <span className="shrink-0">{progressPercent}%{etaLabel ? ` · 约剩 ${etaLabel}` : ''}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
                    <div className="h-full rounded-full bg-blue-600 transition-all duration-300" style={{ width: `${Math.max(progressPercent, 6)}%` }} />
                  </div>
                  <div className="flex items-center justify-between gap-3 text-xs text-slate-400">
                    <span>{progressMeta || '等待进度更新…'}</span>
                    <span>{jobProgress?.elapsed_seconds ? `已用 ${Number(jobProgress.elapsed_seconds).toFixed(1)}s` : ''}</span>
                  </div>
                </div>
              ) : null}
              {error ? <div className="mt-2 text-sm text-red-600">{error}</div> : null}
            </div>

            <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
              {review ? (
                <Card>
                  <CardContent className="space-y-4">
                    <div className="flex flex-wrap gap-2">
                      <Badge tone="primary">completed</Badge>
                      <Badge>{answerSummary.included_count || 0} included</Badge>
                      <Badge>{answerSummary.excluded_count || 0} excluded</Badge>
                      <Badge tone="success">{answerSummary.language || 'zh-CN'}</Badge>
                      <Badge>tokens {formatTokenCount(totalTokenUsage.total_tokens)}</Badge>
                    </div>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                        <div className="text-xs text-slate-500">总 Token</div>
                        <div className="mt-1 font-semibold text-slate-900">{formatTokenCount(totalTokenUsage.total_tokens)}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          prompt {formatTokenCount(totalTokenUsage.prompt_tokens)} · completion {formatTokenCount(totalTokenUsage.completion_tokens)}
                        </div>
                      </div>
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                        <div className="text-xs text-slate-500">筛选 Token</div>
                        <div className="mt-1 font-semibold text-slate-900">{formatTokenCount(filterTokenUsage.total_tokens)}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          prompt {formatTokenCount(filterTokenUsage.prompt_tokens)} · completion {formatTokenCount(filterTokenUsage.completion_tokens)}
                        </div>
                      </div>
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                        <div className="text-xs text-slate-500">综述 Token</div>
                        <div className="mt-1 font-semibold text-slate-900">{formatTokenCount(synthesisTokenUsage.total_tokens)}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          prompt {formatTokenCount(synthesisTokenUsage.prompt_tokens)} · completion {formatTokenCount(synthesisTokenUsage.completion_tokens)}
                        </div>
                      </div>
                      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700">
                        <div className="text-xs text-slate-500">筛选批次</div>
                        <div className="mt-1 font-semibold text-slate-900">
                          {answerSummary.filter_total_batches || 0} 批 / 并行 {answerSummary.filter_parallel_batches || 0}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          重试 {answerSummary.filter_retry_batches || 0} · fallback {answerSummary.filter_fallback_batches || 0}
                        </div>
                      </div>
                    </div>
                    {answerSummary.limitations?.length ? (
                      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                        <div className="font-medium">本次综述限制</div>
                        <div className="mt-2 space-y-1">
                          {answerSummary.limitations.map((item) => (
                            <div key={item}>- {item}</div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <div>
                      <div className="text-sm font-medium text-slate-900">中文综述</div>
                      <MarkdownArticle content={review.review_markdown} />
                    </div>
                    {review.citations?.length ? (
                      <div>
                        <div className="text-sm font-medium text-slate-900">重点引用</div>
                        <MessageCitations citations={review.citations} />
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              ) : null}

              {prepared ? (
                <div className="grid gap-4 xl:grid-cols-[0.95fr_1.45fr]">
                  <div>
                    <Card>
                      <CardContent className="space-y-4">
                        <div>
                          <div className="text-sm font-medium text-slate-900">待确认主题</div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            <Badge tone="primary">prepared</Badge>
                            <Badge>{prepared.candidate_papers?.length || 0} candidates</Badge>
                            <Badge tone="warning">confirmation required</Badge>
                          </div>
                        </div>

                        <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                          <div><span className="font-medium text-slate-900">topic：</span>{prepared.structured_query?.topic || '—'}</div>
                          <div className="mt-2"><span className="font-medium text-slate-900">venues：</span>{prepared.structured_query?.filters?.venues?.join(', ') || '—'}</div>
                          <div className="mt-2"><span className="font-medium text-slate-900">years：</span>{prepared.structured_query?.filters?.years?.join(', ') || '—'}</div>
                          <div className="mt-2"><span className="font-medium text-slate-900">query variants：</span>{prepared.retrieval_summary?.query_variants?.join(' | ') || '—'}</div>
                        </div>

                        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-slate-700">
                          <div className="font-medium text-slate-900">开始前确认</div>
                          <div className="mt-2 leading-6">{prepared.confirmation_prompt}</div>
                          <div className="mt-3 flex gap-2">
                            <Button type="button" onClick={runGenerate} disabled={!canGenerate}>
                              {loadingGenerate ? '综述生成中…' : '确认并开始综述'}
                            </Button>
                            <Button type="button" variant="secondary" onClick={() => setQuery(prepared.query || '')}>
                              返回修改主题
                            </Button>
                          </div>
                        </div>

                        <div className="rounded-xl border border-slate-200 p-4 text-sm text-slate-600">
                          <div className="font-medium text-slate-900">Retrieval Summary</div>
                          <div className="mt-2">模式：{prepared.retrieval_summary?.intent_label || 'direct_search'}</div>
                          <div className="mt-1">候选数：{prepared.candidate_papers?.length || 0}</div>
                          <div className="mt-1">展示数：{prepared.preview_results?.length || 0}</div>
                        </div>
                      </CardContent>
                    </Card>
                  </div>

                  <PreviewPaperCards results={prepared.preview_results || []} />
                </div>
              ) : null}

              {review ? (
                <div className="grid gap-4 xl:grid-cols-2">
                  <PaperList title="纳入论文" papers={review.included_papers || []} emptyText="暂无纳入论文" />
                  <PaperList title="排除论文" papers={review.excluded_papers || []} emptyText="暂无排除论文" />
                </div>
              ) : null}

              {!prepared && !review ? (
                <div className="flex h-full min-h-[240px] items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 px-6 text-center text-sm text-slate-500">
                  输入一个研究主题，系统会先准备候选论文并要求你确认，确认后才开始生成中文综述。
                </div>
              ) : null}
            </div>

            <form onSubmit={runPrepare} className="border-t border-slate-200 bg-white p-4">
              <div className="rounded-2xl border border-slate-300 px-3 py-3 shadow-sm">
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="输入你想综述的研究主题，例如：近两年 prompt injection defense"
                />
                <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
                  <Button type="submit" disabled={loadingPrepare || loadingGenerate}>
                    {loadingPrepare ? '检索中…' : '开始检索'}
                  </Button>
                  <Button type="button" variant="secondary" onClick={runGenerate} disabled={!canGenerate}>
                    {loadingGenerate ? '综述中…' : '确认并开始综述'}
                  </Button>
                </div>
              </div>
            </form>
          </section>
        </div>
      </div>
    </AppLayout>
  );
}
