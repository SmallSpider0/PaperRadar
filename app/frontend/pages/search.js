import { useEffect, useRef, useState } from 'react';

import { AppLayout } from '../components/layout';
import { Badge, Button, Card, CardContent, Input } from '../components/ui';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/paperradar-api';

async function sha256Hex(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function safePaperId(paperUrl) {
  if (!paperUrl) return null;
  const hex = await sha256Hex(paperUrl);
  return `paper_${hex.slice(0, 16)}`;
}

function clampProgress(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(value, 1));
}

function formatEta(seconds) {
  if (typeof seconds !== 'number' || Number.isNaN(seconds) || seconds <= 0) return null;
  if (seconds < 10) return `${seconds.toFixed(1)}s`;
  return `${Math.round(seconds)}s`;
}

export default function SearchPage() {
  const [query, setQuery] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busyMap, setBusyMap] = useState({});
  const [messageMap, setMessageMap] = useState({});
  const [paperIdMap, setPaperIdMap] = useState({});
  const [structuredQuery, setStructuredQuery] = useState(null);
  const [retrievalSummary, setRetrievalSummary] = useState(null);
  const [page, setPage] = useState(1);
  const [pageInput, setPageInput] = useState('1');
  const [totalPages, setTotalPages] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [pageHint, setPageHint] = useState('');
  const [scoreThreshold, setScoreThreshold] = useState(null);
  const [searchProgress, setSearchProgress] = useState(null);
  const [searchError, setSearchError] = useState('');
  const [searchSessionId, setSearchSessionId] = useState(null);
  const pageSize = 10;
  const searchStreamRef = useRef(null);
  const searchTokenRef = useRef(0);

  function buildPageItems(currentPage, maxPages) {
    if (maxPages <= 0) return [];
    const pages = new Set([1, maxPages, currentPage - 1, currentPage, currentPage + 1]);
    const validPages = Array.from(pages).filter((item) => item >= 1 && item <= maxPages).sort((a, b) => a - b);
    const items = [];
    for (let i = 0; i < validPages.length; i += 1) {
      const value = validPages[i];
      if (i > 0 && value - validPages[i - 1] > 1) {
        items.push('ellipsis');
      }
      items.push(value);
    }
    return items;
  }

  function closeSearchStream() {
    if (searchStreamRef.current) {
      searchStreamRef.current.close();
      searchStreamRef.current = null;
    }
  }

  useEffect(() => () => closeSearchStream(), []);

  async function applySearchResponse(data, fallbackPage) {
    const rows = data.results || [];
    setResults(rows);
    setActiveQuery(data.query || '');
    setStructuredQuery(data.structured_query || null);
    setRetrievalSummary(data.retrieval_summary || null);
    setPage(data.page || fallbackPage || 1);
    setPageInput(String(data.page || fallbackPage || 1));
    setTotalPages(data.total_pages || 0);
    setTotalCount(data.total_count || 0);
    setScoreThreshold(typeof data.score_threshold === 'number' ? data.score_threshold : null);
    setSearchSessionId(data.search_session_id || null);
    const entries = await Promise.all(rows.map(async (item) => [item.record.paper_url, await safePaperId(item.record.paper_url)]));
    setPaperIdMap(Object.fromEntries(entries));
  }

  async function waitForSearchJob(jobId, requestToken, fallbackPage) {
    return new Promise((resolve, reject) => {
      const events = new EventSource(`${API_BASE}/api/search/jobs/${jobId}/events`, { withCredentials: true });
      searchStreamRef.current = events;

      events.onmessage = async (event) => {
        if (requestToken !== searchTokenRef.current) {
          closeSearchStream();
          resolve(null);
          return;
        }
        const payload = JSON.parse(event.data);
        setSearchProgress(payload);
        if (payload.status === 'completed') {
          closeSearchStream();
          if (payload.result) {
            await applySearchResponse(payload.result, fallbackPage);
          }
          setSearchError('');
          resolve(payload.result || null);
          return;
        }
        if (payload.status === 'error') {
          closeSearchStream();
          reject(new Error(payload.error || payload.message || '搜索失败'));
        }
      };

      events.onerror = async () => {
        if (requestToken !== searchTokenRef.current) {
          closeSearchStream();
          resolve(null);
          return;
        }
        closeSearchStream();
        try {
          const res = await fetch(`${API_BASE}/api/search/jobs/${jobId}`);
          if (res.ok) {
            const payload = await res.json();
            setSearchProgress(payload);
            if (payload.status === 'completed') {
              if (payload.result) {
                await applySearchResponse(payload.result, fallbackPage);
              }
              setSearchError('');
              resolve(payload.result || null);
              return;
            }
            if (payload.status === 'error') {
              reject(new Error(payload.error || payload.message || '搜索失败'));
              return;
            }
          }
        } catch (error) {
          reject(error);
          return;
        }
        reject(new Error('搜索进度连接中断'));
      };
    });
  }

  async function startSearch(e, targetPage = 1) {
    e?.preventDefault();
    const nextPage = Math.max(Number(targetPage) || 1, 1);
    const requestToken = searchTokenRef.current + 1;
    searchTokenRef.current = requestToken;
    closeSearchStream();
    setLoading(true);
    setSearchError('');
    setPageHint('');
    setSearchSessionId(null);
    setSearchProgress({
      status: 'queued',
      stage: 'queued',
      message: '正在创建搜索任务',
      progress: 0.02,
      page: nextPage,
      limit: pageSize,
      query,
    });
    try {
      const res = await fetch(`${API_BASE}/api/search/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, limit: pageSize, page: nextPage }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `搜索失败: HTTP ${res.status}`);
      }
      setSearchSessionId(data.job_id || null);
      setSearchProgress(data);
      await waitForSearchJob(data.job_id, requestToken, nextPage);
      if (requestToken === searchTokenRef.current) {
        setSearchProgress((prev) => (prev ? { ...prev, progress: 1, eta_seconds: 0 } : prev));
      }
    } catch (error) {
      if (requestToken === searchTokenRef.current) {
        setSearchError(error.message || '搜索失败');
      }
    } finally {
      if (requestToken === searchTokenRef.current) {
        setLoading(false);
      }
    }
  }

  async function runSearch(e, targetPage = page) {
    await startSearch(e, targetPage);
  }

  async function loadPage(targetPage) {
    const nextPage = Math.max(Number(targetPage) || 1, 1);
    if (!searchSessionId || query.trim() !== activeQuery.trim()) {
      await startSearch(undefined, nextPage);
      return;
    }
    const requestToken = searchTokenRef.current + 1;
    searchTokenRef.current = requestToken;
    closeSearchStream();
    setLoading(true);
    setSearchError('');
    setSearchProgress(null);
    try {
      const res = await fetch(`${API_BASE}/api/search/sessions/${searchSessionId}?page=${nextPage}&limit=${pageSize}`);
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        if (requestToken === searchTokenRef.current) {
          await applySearchResponse(data, nextPage);
        }
        return;
      }
      if (res.status === 404) {
        if (requestToken === searchTokenRef.current) {
          setSearchSessionId(null);
          setPageHint('结果已过期，正在重新搜索…');
        }
        await startSearch(undefined, nextPage);
        return;
      }
      throw new Error(data.detail || `翻页失败: HTTP ${res.status}`);
    } catch (error) {
      if (requestToken === searchTokenRef.current) {
        setSearchError(error.message || '翻页失败');
      }
    } finally {
      if (requestToken === searchTokenRef.current) {
        setLoading(false);
      }
    }
  }

  useEffect(() => {
    runSearch(undefined, 1);
  }, []);

  useEffect(() => {
    if (!pageHint) return undefined;
    const timer = setTimeout(() => setPageHint(''), 2200);
    return () => clearTimeout(timer);
  }, [pageHint]);

  async function handleFetchAndParse(item) {
    const paperUrl = item?.record?.paper_url;
    const paperId = paperIdMap[paperUrl] || (await safePaperId(paperUrl));
    if (!paperId) return;
    setMessageMap((prev) => ({ ...prev, [paperId]: '该功能暂时禁用。' }));
  }

  function jumpToPage() {
    const target = Math.max(Number(pageInput) || 1, 1);
    const maxPage = Math.max(totalPages || 1, 1);
    const clampedPage = Math.min(target, maxPage);
    if (target > maxPage) {
      setPageHint(`已自动跳到最后一页（第 ${maxPage} 页）`);
    } else {
      setPageHint('');
    }
    loadPage(clampedPage);
  }

  const progressValue = clampProgress(searchProgress?.progress);
  const progressPercent = Math.round(progressValue * 100);
  const progressLabel = searchProgress?.search_message || searchProgress?.message || (loading ? '搜索中' : '');
  const etaLabel = formatEta(searchProgress?.eta_seconds);
  const progressMetaSecondary = searchProgress?.status === 'queued' && typeof searchProgress?.queue_ahead === 'number'
    ? `前方 ${searchProgress.queue_ahead} 个任务`
    : searchProgress?.variant_total
      ? `并行检索 ${searchProgress.completed_variants || 0}/${searchProgress.variant_total}${searchProgress?.active_variants?.length ? ` · 运行中 ${searchProgress.active_variants.length} 个` : ''}`
      : searchProgress?.total_chunks
        ? `分片 ${searchProgress.completed_chunks || 0}/${searchProgress.total_chunks}`
        : searchProgress?.candidate_count
          ? `${searchProgress.candidate_count} 条候选`
          : '';
  const progressMeta = progressMetaSecondary
    || (searchProgress?.stage === 'parse_query' || searchProgress?.stage === 'parse_query_done' ? '解析查询' : '')
    || (searchProgress?.stage === 'records_ready' ? '元数据已载入' : '')
    || (searchProgress?.stage === 'merge' ? '合并结果' : '');
  const showIndeterminateBar = loading && searchProgress?.status === 'running' && progressPercent < 12;

  return (
    <AppLayout title="Papers" description="搜索已收录论文；“抓取并解析”和“进入阅读页”当前暂时禁用。">
      <Card>
        <CardContent className="space-y-3">
          <form onSubmit={(e) => startSearch(e, 1)} className="flex flex-col gap-3 lg:flex-row lg:items-center">
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search security papers, topics, methods..." />
            <Button type="submit">{loading ? 'Searching…' : 'Search'}</Button>
          </form>
          {(loading || searchError) && searchProgress ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                <span className="truncate">{progressLabel}</span>
                <span className="shrink-0">{progressPercent}%{etaLabel ? ` · 约剩 ${etaLabel}` : ''}</span>
              </div>
              <div className="relative h-1.5 overflow-hidden rounded-full bg-slate-200">
                <div
                  className={`h-full rounded-full bg-blue-600 transition-all duration-300 ${showIndeterminateBar ? 'animate-pulse' : ''}`}
                  style={{ width: `${Math.max(progressPercent, showIndeterminateBar ? 8 : 0)}%` }}
                />
              </div>
              <div className="flex items-center justify-between gap-3 text-xs text-slate-400">
                <span>{progressMeta || (loading ? '连接进度流…' : '')}</span>
                <span>{searchProgress?.elapsed_seconds ? `已用 ${searchProgress.elapsed_seconds.toFixed?.(1) || searchProgress.elapsed_seconds}s` : ''}</span>
              </div>
            </div>
          ) : null}
          {searchError ? <div className="text-sm text-red-600">{searchError}</div> : null}
        </CardContent>
      </Card>

      {structuredQuery ? (
        <Card className="mt-6">
          <CardContent className="space-y-4">
            <div className="text-sm font-medium text-slate-900">Structured Query</div>
            <div className="flex flex-wrap gap-2">
              <Badge tone="primary">intent {structuredQuery.intent}</Badge>
              <Badge>top_k {structuredQuery.top_k}</Badge>
              <Badge tone={structuredQuery.needs_fulltext ? 'warning' : 'success'}>
                {structuredQuery.needs_fulltext ? 'needs fulltext' : 'abstract-first'}
              </Badge>
            </div>
            <div className="grid gap-4 lg:grid-cols-[1.35fr_1fr]">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
                <div><span className="font-medium text-slate-900">topic：</span>{structuredQuery.topic || '—'}</div>
                <div className="mt-2"><span className="font-medium text-slate-900">must：</span>{structuredQuery.must_terms?.join(' | ') || '—'}</div>
                <div className="mt-2"><span className="font-medium text-slate-900">should：</span>{structuredQuery.should_terms?.join(' | ') || '—'}</div>
                <div className="mt-2"><span className="font-medium text-slate-900">negative：</span>{structuredQuery.negative_terms?.join(' | ') || '—'}</div>
              </div>
              {retrievalSummary ? (
                <div className="rounded-xl border border-slate-200 p-4 text-sm text-slate-600">
                  <div className="font-medium text-slate-900">Retrieval Summary</div>
                  <div className="mt-2">模式：{retrievalSummary.intent_label}</div>
                  <div className="mt-1">结果数：{retrievalSummary.result_count}</div>
                  <div className="mt-1">query variants：{(retrievalSummary.query_variants || []).join(' | ') || '—'}</div>
                </div>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <div className="mt-6 grid gap-4">
        {results.map((item) => {
          const paperUrl = item.record.paper_url;
          const paperId = paperIdMap[paperUrl];
          return (
            <Card key={paperUrl}>
              <CardContent>
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div className="min-w-0 flex-1">
                    <a href={paperUrl} target="_blank" rel="noreferrer" className="text-lg font-semibold leading-7 text-slate-900 hover:text-blue-600">
                      {item.record.title}
                    </a>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge tone="primary">score {Number(item.score).toFixed(4)}</Badge>
                      <Badge>{item.record.venue_code}</Badge>
                      <Badge>{item.record.year}</Badge>
                      <Badge tone="warning">{item.record.content_policy || 'unknown policy'}</Badge>
                    </div>
                    {item.record.abstract ? <p className="mt-4 text-sm leading-7 text-slate-600">{item.record.abstract}</p> : null}
                    {item.match_reasons?.length ? (
                      <div className="mt-4 flex flex-wrap gap-2">
                        {item.match_reasons.map((reason) => <Badge key={reason} tone="success">{reason}</Badge>)}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-3 xl:w-56 xl:flex-col">
                    <Button disabled title="该功能暂时禁用">
                      抓取并解析（暂时禁用）
                    </Button>
                    <Button variant="secondary" disabled title="该功能暂时禁用">
                      进入阅读页（暂时禁用）
                    </Button>
                  </div>
                </div>
                {messageMap[paperId] ? <div className="mt-4 text-sm text-emerald-600">{messageMap[paperId]}</div> : null}
              </CardContent>
            </Card>
          );
        })}

        {!loading && !results.length ? (
          <Card>
            <CardContent>
              <div className="text-sm text-slate-500">
                {query.trim()
                  ? `当前没有结果。可能是匹配度阈值（${scoreThreshold ?? 'N/A'}）过滤了低相关论文，建议放宽关键词或尝试英文术语。`
                  : '还没有结果。先执行一次搜索，查看已入库的会议论文。'}
              </div>
            </CardContent>
          </Card>
        ) : null}
      </div>

      <Card className="mt-6">
        <CardContent className="flex items-center justify-between gap-4 overflow-x-auto whitespace-nowrap">
          <div className="text-sm text-slate-600">
            共 {totalCount} 条，{totalPages || 1} 页
          </div>
          <div className="flex items-center gap-2 text-sm">
            <button
              type="button"
              className="rounded-md px-2 py-1 text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300"
              onClick={() => loadPage(page - 1)}
              disabled={loading || page <= 1}
            >
              上一页
            </button>
            {buildPageItems(page, Math.max(totalPages, 1)).map((item, index) => (
              item === 'ellipsis' ? (
                <span key={`ellipsis-${index}`} className="px-1 text-slate-400">...</span>
              ) : (
                <button
                  key={`page-${item}`}
                  type="button"
                  className={`min-w-8 rounded-md px-2 py-1 ${item === page ? 'bg-blue-600 text-white' : 'text-blue-600 hover:bg-blue-50'}`}
                  onClick={() => loadPage(item)}
                  disabled={loading}
                >
                  {item}
                </button>
              )
            ))}
            <button
              type="button"
              className="rounded-md px-2 py-1 text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:text-slate-300"
              onClick={() => loadPage(page + 1)}
              disabled={loading || page >= totalPages}
            >
              下一页
            </button>
            <Input value={pageInput} onChange={(e) => setPageInput(e.target.value)} placeholder="页码" />
            <Button onClick={jumpToPage} disabled={loading}>跳转</Button>
            {pageHint ? <span className="text-xs text-amber-600">{pageHint}</span> : null}
          </div>
        </CardContent>
      </Card>
    </AppLayout>
  );
}
