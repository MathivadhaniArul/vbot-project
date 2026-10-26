'use client';

/**
 * VIT Assistant — Admin Console
 * ------------------------------------------------------------------
 * Single-page operator console for the RAG backend exposed by
 * main.py / admin_ingest.py / admin_scrape.py / admin_vectordb.py.
 *
 * Configure the backend origin via NEXT_PUBLIC_API_BASE_URL
 * (leave unset if this app is served behind a reverse proxy that
 * forwards /api/* to the FastAPI service on the same origin).
 *
 * Drop this file at app/admin/page.tsx in a Next.js (App Router)
 * project with Tailwind CSS configured.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

// ============================================================================
// CONFIG
// ============================================================================

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? '';
const DISPLAY_TZ = 'Asia/Kolkata';
console.log('API_BASE is:', JSON.stringify(API_BASE));
// ============================================================================
// FETCH HELPERS
// ============================================================================

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function fetchJson<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...(init?.headers || {}),
    },
  });
  const ct = res.headers.get('content-type') || '';
  const body = ct.includes('application/json') ? await res.json().catch(() => null) : await res.text();
  if (!res.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as any).detail : res.statusText;
    throw new ApiError(typeof detail === 'string' ? detail : JSON.stringify(detail), res.status);
  }
  return body as T;
}

const getJson = <T = any,>(path: string) => fetchJson<T>(path, { method: 'GET' });
const postJson = <T = any,>(path: string, payload?: any) =>
  fetchJson<T>(path, { method: 'POST', body: payload !== undefined ? JSON.stringify(payload) : undefined });
const postForm = <T = any,>(path: string, form: FormData) => fetchJson<T>(path, { method: 'POST', body: form });

// ============================================================================
// FORMAT HELPERS
// ============================================================================

function fmtDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: DISPLAY_TZ,
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  }).format(d);
}

function fmtNum(n?: number | null): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  return new Intl.NumberFormat('en-IN').format(n);
}

function fmtMs(n?: number | null): string {
  if (n === null || n === undefined) return '—';
  return n >= 1000 ? `${(n / 1000).toFixed(2)}s` : `${Math.round(n)}ms`;
}

function fmtPct(n?: number | null): string {
  if (n === null || n === undefined) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ');
}

// ============================================================================
// ICONS (hand-rolled, no external icon dependency)
// ============================================================================

function Icon({ path, className }: { path: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d={path} />
    </svg>
  );
}
const IconPaths = {
  grid: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z',
  users: 'M17 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  gauge: 'M12 14 15 9M4 14a8 8 0 1 1 16 0M4 14h16',
  flask: 'M9 3h6M10 3v5.5L5.5 17a2 2 0 0 0 1.8 3h9.4a2 2 0 0 0 1.8-3L14 8.5V3',
  upload: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  database: 'M4 6c0-1.66 3.58-3 8-3s8 1.34 8 3-3.58 3-8 3-8-1.34-8-3ZM4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6',
  refresh: 'M21 12a9 9 0 1 1-3-6.7M21 3v6h-6',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.35-4.35',
  trash: 'M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6',
  check: 'M20 6 9 17l-5-5',
  alert: 'M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  link: 'M9 17H7a5 5 0 0 1 0-10h2M15 7h2a5 5 0 0 1 0 10h-2M8 12h8',
  play: 'M6 4.5v15l13-7.5-13-7.5Z',
  chevron: 'm9 6 6 6-6 6',
};

// ============================================================================
// PRIMITIVES
// ============================================================================

function Panel({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cx('panel', className)}>{children}</div>;
}

function PanelHead({ title, sub, right }: { title: string; sub?: string; right?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 mb-4">
      <div>
        <h3 className="font-display text-[15px] tracking-wide text-ink">{title}</h3>
        {sub ? <p className="mt-0.5 text-[12.5px] text-muted font-mono">{sub}</p> : null}
      </div>
      {right}
    </div>
  );
}

function Stat({ label, value, tone = 'default', hint }: { label: string; value: React.ReactNode; tone?: 'default' | 'good' | 'warn' | 'bad'; hint?: string }) {
  const toneClass = { default: 'text-ink', good: 'text-signal', warn: 'text-amber', bad: 'text-coral' }[tone];
  return (
    <div className="stat">
      <div className="text-[11px] uppercase tracking-[0.12em] text-muted font-mono">{label}</div>
      <div className={cx('font-mono text-[26px] leading-tight mt-1', toneClass)}>{value}</div>
      {hint ? <div className="text-[11.5px] text-muted mt-1">{hint}</div> : null}
    </div>
  );
}

function Badge({ children, tone = 'default' }: { children: React.ReactNode; tone?: 'default' | 'good' | 'warn' | 'bad' }) {
  const toneClass = {
    default: 'bg-white/5 text-ink2 border-line',
    good: 'bg-signal/10 text-signal border-signal/30',
    warn: 'bg-amber/10 text-amber border-amber/30',
    bad: 'bg-coral/10 text-coral border-coral/30',
  }[tone];
  return <span className={cx('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-mono', toneClass)}>{children}</span>;
}

function Button({
  children,
  onClick,
  variant = 'default',
  disabled,
  type = 'button',
  className,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: 'default' | 'primary' | 'danger' | 'ghost';
  disabled?: boolean;
  type?: 'button' | 'submit';
  className?: string;
}) {
  const variants: Record<string, string> = {
    default: 'bg-surface2 border-line text-ink hover:bg-white/[0.06]',
    primary: 'bg-signal/15 border-signal/40 text-signal hover:bg-signal/25',
    danger: 'bg-coral/15 border-coral/40 text-coral hover:bg-coral/25',
    ghost: 'bg-transparent border-transparent text-muted hover:text-ink hover:bg-white/[0.04]',
  };
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={cx(
        'inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12.5px] font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed',
        variants[variant],
        className
      )}
    >
      {children}
    </button>
  );
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        'w-full rounded-md border border-line bg-surface2 px-3 py-2 text-[13px] text-ink placeholder:text-muted/70 outline-none focus:border-signal/50 focus:ring-1 focus:ring-signal/30 font-mono',
        props.className
      )}
    />
  );
}

function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cx(
        'w-full rounded-md border border-line bg-surface2 px-3 py-2 text-[13px] text-ink placeholder:text-muted/70 outline-none focus:border-signal/50 focus:ring-1 focus:ring-signal/30 font-mono',
        props.className
      )}
    />
  );
}

function Field({ label, children, htmlFor }: { label: string; children: React.ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block">
      <div className="mb-1 text-[11px] uppercase tracking-[0.1em] text-muted font-mono">{label}</div>
      {children}
    </label>
  );
}

function LoadingRows({ n = 3 }: { n?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="h-8 w-full animate-pulse rounded bg-white/[0.04]" />
      ))}
    </div>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="rounded-md border border-dashed border-line py-8 text-center text-[12.5px] text-muted font-mono">{label}</div>;
}

function ErrorNote({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-coral/30 bg-coral/10 px-3 py-2 text-[12.5px] text-coral">
      <Icon path={IconPaths.alert} className="mt-0.5 h-4 w-4 shrink-0" />
      <span className="font-mono">{message}</span>
    </div>
  );
}

function Table({ head, rows, empty = 'No rows.' }: { head: string[]; rows: React.ReactNode[][]; empty?: string }) {
  if (!rows.length) return <EmptyState label={empty} />;
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="w-full min-w-[560px] border-collapse text-[12.5px]">
        <thead>
          <tr className="bg-white/[0.03]">
            {head.map((h) => (
              <th key={h} className="border-b border-line px-3 py-2 text-left font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-line/60 last:border-0 hover:bg-white/[0.02]">
              {r.map((c, j) => (
                <td key={j} className="px-3 py-2 align-top text-ink2 font-mono">
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Horizontal bar used for stage latency / router distribution
function BarRow({ label, value, max, formatted, tone = 'signal' }: { label: string; value: number; max: number; formatted: string; tone?: 'signal' | 'amber' | 'coral' }) {
  const pct = max > 0 ? Math.min(100, (value / max) * 100) : 0;
  const toneClass = { signal: 'bg-signal/60', amber: 'bg-amber/60', coral: 'bg-coral/60' }[tone];
  return (
    <div className="grid grid-cols-[120px_1fr_70px] items-center gap-3 py-1.5">
      <div className="truncate text-[12px] text-ink2 font-mono">{label}</div>
      <div className="h-2 rounded-full bg-white/[0.05] overflow-hidden">
        <div className={cx('h-full rounded-full', toneClass)} style={{ width: `${pct}%` }} />
      </div>
      <div className="text-right text-[12px] text-muted font-mono">{formatted}</div>
    </div>
  );
}

// Signature element — a live "pulse strip" summarizing pipeline health as a
// heartbeat-style waveform. Purely decorative/informational, driven by the
// error + timeout rate from the last pipeline summary fetch.
function PulseStrip({ errorRate, timeoutRate, requests }: { errorRate: number | null; timeoutRate: number | null; requests: number | null }) {
  const severity = Math.min(1, ((errorRate ?? 0) + (timeoutRate ?? 0)) * 4);
  const tone = severity > 0.5 ? 'coral' : severity > 0.15 ? 'amber' : 'signal';
  const toneHex = { coral: '#F87171', amber: '#FBBF24', signal: '#5EEAD4' }[tone];
  // deterministic pseudo-waveform, amplitude scales with severity
  const points = useMemo(() => {
    const n = 64;
    const amp = 4 + severity * 14;
    return Array.from({ length: n }).map((_, i) => {
      const spike = i % 8 === 4 ? amp * 1.8 : amp * Math.sin(i * 0.9) * 0.4;
      return 20 + spike;
    });
  }, [severity]);
  const path = points.map((y, i) => `${i === 0 ? 'M' : 'L'} ${i * (560 / (points.length - 1))} ${y}`).join(' ');

  return (
    <div className="relative overflow-hidden rounded-lg border border-line bg-surface2/60 px-4 py-3">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className={cx('absolute inline-flex h-full w-full animate-ping rounded-full opacity-60')} style={{ backgroundColor: toneHex }} />
            <span className="relative inline-flex h-2 w-2 rounded-full" style={{ backgroundColor: toneHex }} />
          </span>
          <span className="text-[11px] uppercase tracking-[0.12em] text-muted font-mono">pipeline pulse — last 24h</span>
        </div>
        <div className="flex items-center gap-3 text-[11.5px] font-mono text-muted">
          <span>
            req <span className="text-ink2">{fmtNum(requests)}</span>
          </span>
          <span>
            err <span className={tone === 'coral' ? 'text-coral' : 'text-ink2'}>{fmtPct(errorRate)}</span>
          </span>
          <span>
            timeout <span className={tone === 'amber' || tone === 'coral' ? 'text-amber' : 'text-ink2'}>{fmtPct(timeoutRate)}</span>
          </span>
        </div>
      </div>
      <svg viewBox="0 0 560 40" className="w-full h-10" preserveAspectRatio="none">
        <path d={path} fill="none" stroke={toneHex} strokeWidth={1.4} strokeLinejoin="round" strokeLinecap="round" opacity={0.85} />
      </svg>
    </div>
  );
}

// ============================================================================
// NAV
// ============================================================================

type TabKey = 'overview' | 'chats' | 'pipeline' | 'evaluations' | 'ingest' | 'vectordb';

const NAV: { key: TabKey; label: string; icon: string }[] = [
  { key: 'overview', label: 'Overview', icon: IconPaths.grid },
  { key: 'chats', label: 'Chats & Users', icon: IconPaths.users },
  { key: 'pipeline', label: 'Pipeline', icon: IconPaths.gauge },
  { key: 'evaluations', label: 'Evaluations', icon: IconPaths.flask },
  { key: 'ingest', label: 'Ingest', icon: IconPaths.upload },
  { key: 'vectordb', label: 'Vector DB', icon: IconPaths.database },
];

// ============================================================================
// ROOT PAGE
// ============================================================================

export default function AdminPage() {
  const [tab, setTab] = useState<TabKey>('overview');

  return (
    <div className="admin-root min-h-screen bg-base text-ink">
      <style jsx global>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
        .admin-root {
          --base: #0a0c10;
          --surface: #12151b;
          --surface2: #171b22;
          --line: #262b34;
          --ink: #e8ebf0;
          --ink2: #b7bfcb;
          --muted: #7c8695;
          --signal: #5eead4;
          --amber: #fbbf24;
          --coral: #f87171;
          background: radial-gradient(1200px 600px at 85% -10%, rgba(94, 234, 212, 0.05), transparent), var(--base);
          font-family: 'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif;
        }
        .admin-root .font-display {
          font-family: 'Space Grotesk', ui-sans-serif, system-ui, sans-serif;
        }
        .admin-root .font-mono {
          font-family: 'IBM Plex Mono', ui-monospace, monospace;
        }
        .admin-root .bg-base { background-color: var(--base); }
        .admin-root .bg-surface { background-color: var(--surface); }
        .admin-root .bg-surface2 { background-color: var(--surface2); }
        .admin-root .border-line { border-color: var(--line); }
        .admin-root .text-ink { color: var(--ink); }
        .admin-root .text-ink2 { color: var(--ink2); }
        .admin-root .text-muted { color: var(--muted); }
        .admin-root .text-signal { color: var(--signal); }
        .admin-root .text-amber { color: var(--amber); }
        .admin-root .text-coral { color: var(--coral); }
        .admin-root .bg-signal\\/10 { background-color: rgba(94,234,212,0.10); }
        .admin-root .bg-signal\\/15 { background-color: rgba(94,234,212,0.15); }
        .admin-root .bg-signal\\/25 { background-color: rgba(94,234,212,0.25); }
        .admin-root .bg-signal\\/60 { background-color: rgba(94,234,212,0.6); }
        .admin-root .bg-amber\\/10 { background-color: rgba(251,191,36,0.10); }
        .admin-root .bg-amber\\/60 { background-color: rgba(251,191,36,0.6); }
        .admin-root .bg-coral\\/10 { background-color: rgba(248,113,113,0.10); }
        .admin-root .bg-coral\\/15 { background-color: rgba(248,113,113,0.15); }
        .admin-root .bg-coral\\/25 { background-color: rgba(248,113,113,0.25); }
        .admin-root .bg-coral\\/60 { background-color: rgba(248,113,113,0.6); }
        .admin-root .border-signal\\/30 { border-color: rgba(94,234,212,0.3); }
        .admin-root .border-signal\\/40 { border-color: rgba(94,234,212,0.4); }
        .admin-root .border-signal\\/50 { border-color: rgba(94,234,212,0.5); }
        .admin-root .border-amber\\/30 { border-color: rgba(251,191,36,0.3); }
        .admin-root .border-coral\\/30 { border-color: rgba(248,113,113,0.3); }
        .admin-root .border-coral\\/40 { border-color: rgba(248,113,113,0.4); }
        .admin-root .ring-signal\\/30 { --tw-ring-color: rgba(94,234,212,0.3); }
        .admin-root .panel {
          background: linear-gradient(180deg, var(--surface), var(--surface2));
          border: 1px solid var(--line);
          border-radius: 12px;
          padding: 18px;
        }
        .admin-root .stat {
          border: 1px solid var(--line);
          background: var(--surface2);
          border-radius: 10px;
          padding: 14px 16px;
        }
        .admin-root ::selection { background: rgba(94,234,212,0.25); }
      `}</style>

      <div className="mx-auto flex max-w-[1400px] gap-6 px-5 py-6">
        {/* Sidebar */}
        <aside className="sticky top-6 hidden h-[calc(100vh-3rem)] w-56 shrink-0 flex-col justify-between md:flex">
          <div>
            <div className="mb-6 px-1">
              <div className="font-display text-[17px] font-semibold tracking-tight text-ink">VIT Assistant</div>
              <div className="font-mono text-[11px] text-muted">admin console</div>
            </div>
            <nav className="space-y-1">
              {NAV.map((n) => (
                <button
                  key={n.key}
                  onClick={() => setTab(n.key)}
                  className={cx(
                    'flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-[13px] transition-colors',
                    tab === n.key ? 'bg-signal/10 text-signal border border-signal/30' : 'text-ink2 hover:bg-white/[0.04] border border-transparent'
                  )}
                >
                  <Icon path={n.icon} className="h-4 w-4 shrink-0" />
                  {n.label}
                </button>
              ))}
            </nav>
          </div>
          <div className="px-1 pb-2 text-[11px] font-mono text-muted">
            <div>backend: {API_BASE || 'same-origin'}</div>
            <div>tz: {DISPLAY_TZ}</div>
          </div>
        </aside>

        {/* Mobile tab bar */}
        <div className="fixed inset-x-0 top-0 z-20 flex gap-1 overflow-x-auto border-b border-line bg-base/95 px-3 py-2 backdrop-blur md:hidden">
          {NAV.map((n) => (
            <button
              key={n.key}
              onClick={() => setTab(n.key)}
              className={cx(
                'shrink-0 rounded-md px-3 py-1.5 text-[12px] font-mono',
                tab === n.key ? 'bg-signal/15 text-signal' : 'text-muted'
              )}
            >
              {n.label}
            </button>
          ))}
        </div>

        {/* Main */}
        <main className="min-w-0 flex-1 pt-10 md:pt-0">
          {tab === 'overview' && <OverviewView onNavigate={setTab} />}
          {tab === 'chats' && <ChatsView />}
          {tab === 'pipeline' && <PipelineView />}
          {tab === 'evaluations' && <EvaluationsView />}
          {tab === 'ingest' && <IngestView />}
          {tab === 'vectordb' && <VectorDbView />}
        </main>
      </div>
    </div>
  );
}

// ============================================================================
// OVERVIEW
// ============================================================================

function OverviewView({ onNavigate }: { onNavigate: (t: TabKey) => void }) {
  const [stats, setStats] = useState<any>(null);
  const [pipeline, setPipeline] = useState<any>(null);
  const [vdb, setVdb] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const [s, p, v] = await Promise.allSettled([
        getJson('/api/admin/stats'),
        getJson('/api/admin/pipeline/summary?hours=24'),
        getJson('/api/admin/vectordb/stats'),
      ]);
      if (s.status === 'fulfilled') setStats(s.value);
      if (p.status === 'fulfilled') setPipeline(p.value);
      if (v.status === 'fulfilled') setVdb(v.value);
      const firstErr = [s, p, v].find((r) => r.status === 'rejected') as PromiseRejectedResult | undefined;
      if (firstErr) setErr(String(firstErr.reason?.message || firstErr.reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-[22px] font-semibold text-ink">Overview</h1>
          <p className="text-[13px] text-muted mt-0.5">System health at a glance.</p>
        </div>
        <Button onClick={load} variant="ghost">
          <Icon path={IconPaths.refresh} className="h-3.5 w-3.5" /> Refresh
        </Button>
      </header>

      <PulseStrip
        errorRate={pipeline?.totals?.error_rate ?? null}
        timeoutRate={pipeline?.totals?.timeout_rate ?? null}
        requests={pipeline?.totals?.requests ?? null}
      />

      {err && <ErrorNote message={err} />}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Stat label="Chats" value={loading ? '…' : fmtNum(stats?.stats?.total_chats)} />
        <Stat label="Messages" value={loading ? '…' : fmtNum(stats?.stats?.total_messages)} />
        <Stat label="Users" value={loading ? '…' : fmtNum(stats?.stats?.total_users)} />
        <Stat label="Pending reminders" value={loading ? '…' : fmtNum(stats?.stats?.upcoming_reminders)} />
        <Stat label="Unread notifs" value={loading ? '…' : fmtNum(stats?.stats?.unread_notifications)} />
        <Stat label="Active threads" value={loading ? '…' : fmtNum(stats?.stats?.active_threads)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-1 cursor-pointer" >
          <PanelHead title="Pipeline (24h)" sub="requests · errors · timeouts" right={<button onClick={() => onNavigate('pipeline')} className="text-muted hover:text-ink"><Icon path={IconPaths.chevron} className="h-4 w-4" /></button>} />
          {loading ? (
            <LoadingRows n={3} />
          ) : (
            <div className="space-y-2 text-[13px]">
              <div className="flex justify-between"><span className="text-muted">Requests</span><span className="font-mono text-ink2">{fmtNum(pipeline?.totals?.requests)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Error rate</span><span className="font-mono text-coral">{fmtPct(pipeline?.totals?.error_rate)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Timeout rate</span><span className="font-mono text-amber">{fmtPct(pipeline?.totals?.timeout_rate)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Reranker fallback</span><span className="font-mono text-ink2">{fmtPct(pipeline?.totals?.reranker_fallback_rate)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Total p95</span><span className="font-mono text-ink2">{fmtMs(pipeline?.stages?.total_ms?.p95)}</span></div>
            </div>
          )}
        </Panel>

        <Panel>
          <PanelHead title="Vector DB" sub={vdb?.collection_name || '—'} right={<button onClick={() => onNavigate('vectordb')} className="text-muted hover:text-ink"><Icon path={IconPaths.chevron} className="h-4 w-4" /></button>} />
          {loading ? (
            <LoadingRows n={3} />
          ) : (
            <div className="space-y-2 text-[13px]">
              <div className="flex justify-between"><span className="text-muted">Points</span><span className="font-mono text-ink2">{fmtNum(vdb?.points_count)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Sources</span><span className="font-mono text-ink2">{fmtNum(vdb?.source_count)}</span></div>
              <div className="flex justify-between"><span className="text-muted">Status</span><Badge tone={vdb?.status === 'green' ? 'good' : 'warn'}>{vdb?.status || 'unknown'}</Badge></div>
              {Object.entries(vdb?.by_level || {}).map(([lvl, count]) => (
                <div key={lvl} className="flex justify-between"><span className="text-muted capitalize">{lvl}</span><span className="font-mono text-ink2">{fmtNum(count as number)}</span></div>
              ))}
            </div>
          )}
        </Panel>

        <Panel>
          <PanelHead title="Quick actions" />
          <div className="flex flex-col gap-2">
            <Button variant="default" onClick={() => onNavigate('ingest')}><Icon path={IconPaths.upload} className="h-3.5 w-3.5" /> Ingest content</Button>
            <Button variant="default" onClick={() => onNavigate('vectordb')}><Icon path={IconPaths.database} className="h-3.5 w-3.5" /> Inspect vector DB</Button>
            <Button variant="default" onClick={() => onNavigate('evaluations')}><Icon path={IconPaths.flask} className="h-3.5 w-3.5" /> Run evaluation</Button>
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ============================================================================
// CHATS & USERS
// ============================================================================

function ChatsView() {
  const [users, setUsers] = useState<any[]>([]);
  const [chats, setChats] = useState<any[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(true);
  const [loadingChats, setLoadingChats] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [skip, setSkip] = useState(0);
  const limit = 25;

  const loadUsers = useCallback(async () => {
    setLoadingUsers(true);
    try {
      const r = await getJson('/api/admin/users');
      setUsers(r.users || []);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoadingUsers(false);
    }
  }, []);

  const loadChats = useCallback(async (s: number) => {
    setLoadingChats(true);
    try {
      const r = await getJson(`/api/admin/chats?limit=${limit}&skip=${s}`);
      setChats(r.chats || []);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoadingChats(false);
    }
  }, []);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);
  useEffect(() => {
    loadChats(skip);
  }, [loadChats, skip]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-[22px] font-semibold text-ink">Chats &amp; Users</h1>
        <p className="text-[13px] text-muted mt-0.5">All conversations across users, most recently updated first.</p>
      </header>

      {err && <ErrorNote message={err} />}

      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <Panel>
          <PanelHead title="Users" sub={`${users.length} distinct`} />
          {loadingUsers ? (
            <LoadingRows n={6} />
          ) : users.length === 0 ? (
            <EmptyState label="No users yet." />
          ) : (
            <div className="max-h-[520px] space-y-1 overflow-y-auto pr-1">
              {users.map((u) => (
                <div key={u._id} className="flex items-center justify-between rounded-md px-2 py-1.5 text-[12.5px] hover:bg-white/[0.03]">
                  <span className="truncate text-ink2 font-mono">{u._id || 'anonymous'}</span>
                  <span className="shrink-0 text-muted font-mono">{u.chatCount}</span>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel>
          <PanelHead
            title="Recent chats"
            right={
              <div className="flex gap-2">
                <Button variant="ghost" disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - limit))}>Prev</Button>
                <Button variant="ghost" onClick={() => setSkip(skip + limit)}>Next</Button>
              </div>
            }
          />
          {loadingChats ? (
            <LoadingRows n={8} />
          ) : (
            <Table
              head={['User', 'Title', 'Updated', 'Created']}
              empty="No chats found."
              rows={chats.map((c) => [
                <span key="u">{c.userId || '—'}</span>,
                <span key="t" className="text-ink2 font-sans">{c.title || c._id}</span>,
                <span key="up">{fmtDate(c.updatedAt)}</span>,
                <span key="cr">{fmtDate(c.createdAt)}</span>,
              ])}
            />
          )}
        </Panel>
      </div>
    </div>
  );
}

// ============================================================================
// PIPELINE
// ============================================================================

function PipelineView() {
  const [hours, setHours] = useState(24);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async (h: number) => {
    setLoading(true);
    setErr(null);
    try {
      const r = await getJson(`/api/admin/pipeline/summary?hours=${h}`);
      setData(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(hours);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const stageOrder = ['router_ms', 'retrieval_ms', 'reranker_ms', 'generation_ms', 'reminder_llm_ms', 'rag_total_ms', 'total_ms'];
  const stageMax = data ? Math.max(1, ...stageOrder.map((k) => data.stages?.[k]?.p95 || 0)) : 1;
  const routerMax = data ? Math.max(1, ...(data.router_distribution || []).map((r: any) => r.count)) : 1;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-[22px] font-semibold text-ink">Pipeline</h1>
          <p className="text-[13px] text-muted mt-0.5">Latency stages, router distribution, and failures.</p>
        </div>
        <div className="flex items-center gap-2">
          {[1, 6, 24, 24 * 7].map((h) => (
            <button
              key={h}
              onClick={() => {
                setHours(h);
                load(h);
              }}
              className={cx('rounded-md border px-2.5 py-1 text-[12px] font-mono', hours === h ? 'border-signal/40 bg-signal/10 text-signal' : 'border-line text-muted hover:text-ink')}
            >
              {h < 24 ? `${h}h` : `${h / 24}d`}
            </button>
          ))}
        </div>
      </header>

      {err && <ErrorNote message={err} />}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Requests" value={loading ? '…' : fmtNum(data?.totals?.requests)} />
        <Stat label="Error rate" value={loading ? '…' : fmtPct(data?.totals?.error_rate)} tone={data?.totals?.error_rate > 0.02 ? 'bad' : 'good'} />
        <Stat label="Timeout rate" value={loading ? '…' : fmtPct(data?.totals?.timeout_rate)} tone={data?.totals?.timeout_rate > 0.02 ? 'warn' : 'good'} />
        <Stat label="Reranker fallback" value={loading ? '…' : fmtPct(data?.totals?.reranker_fallback_rate)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHead title="Stage latency (p95)" sub="router · retrieval · reranker · generation · total" />
          {loading ? (
            <LoadingRows n={6} />
          ) : (
            <div>
              {stageOrder.map((k) => (
                <BarRow key={k} label={k.replace('_ms', '')} value={data?.stages?.[k]?.p95 || 0} max={stageMax} formatted={fmtMs(data?.stages?.[k]?.p95)} tone={k === 'total_ms' ? 'amber' : 'signal'} />
              ))}
            </div>
          )}
        </Panel>

        <Panel>
          <PanelHead title="Router distribution" sub="sources selected per request" />
          {loading ? (
            <LoadingRows n={6} />
          ) : !data?.router_distribution?.length ? (
            <EmptyState label="No routing data." />
          ) : (
            <div>
              {data.router_distribution.map((r: any) => (
                <BarRow key={r._id} label={String(r._id)} value={r.count} max={routerMax} formatted={fmtNum(r.count)} />
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel>
        <PanelHead title="Slowest queries" sub="top 10 by total_ms" />
        {loading ? (
          <LoadingRows n={5} />
        ) : (
          <Table
            head={['Time', 'Total', 'Router', 'Retrieval', 'Reranker', 'Generation']}
            empty="No queries recorded."
            rows={(data?.slowest_queries || []).map((q: any) => [
              fmtDate(q.createdAt),
              <span key="t" className="text-amber">{fmtMs(q.total_ms)}</span>,
              fmtMs(q.router_ms),
              fmtMs(q.retrieval_ms),
              fmtMs(q.reranker_ms),
              fmtMs(q.generation_ms),
            ])}
          />
        )}
      </Panel>

      <Panel>
        <PanelHead title="Recent failures" sub="timeouts and errors" />
        {loading ? (
          <LoadingRows n={5} />
        ) : (
          <Table
            head={['Time', 'Timed out', 'Error']}
            empty="No failures in this window."
            rows={(data?.recent_failures || []).map((f: any) => [
              fmtDate(f.createdAt),
              f.timed_out ? <Badge tone="warn">timeout</Badge> : '—',
              f.error ? <span className="text-coral">{String(f.error).slice(0, 140)}</span> : '—',
            ])}
          />
        )}
      </Panel>
    </div>
  );
}

// ============================================================================
// EVALUATIONS
// ============================================================================

function EvaluationsView() {
  const [hours, setHours] = useState(24 * 7);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<string | null>(null);
  const [sampleSize, setSampleSize] = useState(100);
  const [runHours, setRunHours] = useState(24);

  const load = useCallback(async (h: number) => {
    setLoading(true);
    setErr(null);
    try {
      const r = await getJson(`/api/admin/evaluations/summary?hours=${h}`);
      setData(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(hours);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runEval = async () => {
    setRunning(true);
    setRunResult(null);
    try {
      const r = await postJson(`/api/admin/evaluations/run?hours=${runHours}&sample_size=${sampleSize}`);
      setRunResult(`Enqueued — task ${r.task_id}`);
    } catch (e: any) {
      setRunResult(`Failed: ${e.message}`);
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-[22px] font-semibold text-ink">Evaluations</h1>
          <p className="text-[13px] text-muted mt-0.5">RAGAS faithfulness &amp; relevancy trends.</p>
        </div>
        <div className="flex items-center gap-2">
          {[24, 24 * 7, 24 * 30].map((h) => (
            <button
              key={h}
              onClick={() => {
                setHours(h);
                load(h);
              }}
              className={cx('rounded-md border px-2.5 py-1 text-[12px] font-mono', hours === h ? 'border-signal/40 bg-signal/10 text-signal' : 'border-line text-muted hover:text-ink')}
            >
              {h / 24}d
            </button>
          ))}
        </div>
      </header>

      {err && <ErrorNote message={err} />}

      <Panel>
        <PanelHead title="Run a batch evaluation" sub="enqueues a Celery job — doesn't block the request" />
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Window (hours)">
            <TextInput type="number" value={runHours} onChange={(e) => setRunHours(Number(e.target.value))} className="w-28" />
          </Field>
          <Field label="Sample size">
            <TextInput type="number" value={sampleSize} onChange={(e) => setSampleSize(Number(e.target.value))} className="w-28" />
          </Field>
          <Button variant="primary" onClick={runEval} disabled={running}>
            <Icon path={IconPaths.play} className="h-3.5 w-3.5" /> {running ? 'Enqueuing…' : 'Run evaluation'}
          </Button>
          {runResult && <span className="text-[12.5px] font-mono text-muted">{runResult}</span>}
        </div>
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        {['faithfulness', 'answer_relevancy'].map((metric) => {
          const m = data?.metrics?.[metric];
          return (
            <Panel key={metric}>
              <PanelHead title={metric.replace('_', ' ')} sub={`${fmtNum(m?.count)} scored samples`} />
              {loading ? (
                <LoadingRows n={3} />
              ) : (
                <div className="grid grid-cols-4 gap-2 text-center">
                  <div>
                    <div className="text-[10.5px] uppercase text-muted font-mono">avg</div>
                    <div className="font-mono text-[16px] text-ink">{m?.avg ?? '—'}</div>
                  </div>
                  <div>
                    <div className="text-[10.5px] uppercase text-muted font-mono">p5</div>
                    <div className="font-mono text-[16px] text-coral">{m?.p5 ?? '—'}</div>
                  </div>
                  <div>
                    <div className="text-[10.5px] uppercase text-muted font-mono">p95</div>
                    <div className="font-mono text-[16px] text-signal">{m?.p95 ?? '—'}</div>
                  </div>
                  <div>
                    <div className="text-[10.5px] uppercase text-muted font-mono">min</div>
                    <div className="font-mono text-[16px] text-amber">{m?.min ?? '—'}</div>
                  </div>
                </div>
              )}
            </Panel>
          );
        })}
      </div>

      <Panel>
        <PanelHead title="Lowest faithfulness samples" sub="click a row to inspect the query, contexts, and answer" />
        {loading ? (
          <LoadingRows n={5} />
        ) : !data?.lowest_faithfulness_samples?.length ? (
          <EmptyState label="No evaluation samples in this window." />
        ) : (
          <div className="overflow-hidden rounded-md border border-line">
            <table className="w-full min-w-[560px] border-collapse text-[12.5px]">
              <thead>
                <tr className="bg-white/[0.03]">
                  {['Time', 'Faithfulness', 'Answer relevancy', ''].map((h) => (
                    <th key={h} className="border-b border-line px-3 py-2 text-left font-mono text-[10.5px] uppercase tracking-[0.08em] text-muted">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(data.lowest_faithfulness_samples || []).map((s: any) => (
                  <SampleDetailRow key={s._id} sample={s} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function SampleDetailRow({ sample }: { sample: any }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<any>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailErr, setDetailErr] = useState<string | null>(null);

  const toggle = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !detail && !loadingDetail) {
      setLoadingDetail(true);
      setDetailErr(null);
      try {
        const r = await getJson(`/api/admin/evaluations/sample/${sample._id}`);
        setDetail(r);
      } catch (e: any) {
        setDetailErr(e.message);
      } finally {
        setLoadingDetail(false);
      }
    }
  };

  return (
    <>
      <tr
        onClick={toggle}
        className="cursor-pointer border-b border-line/60 hover:bg-white/[0.03]"
      >
        <td className="px-3 py-2 align-top text-ink2 font-mono">{fmtDate(sample.createdAt)}</td>
        <td className="px-3 py-2 align-top font-mono text-coral">{sample.faithfulness ?? '—'}</td>
        <td className="px-3 py-2 align-top font-mono text-ink2">{sample.answer_relevancy ?? '—'}</td>
        <td className="px-3 py-2 align-top text-right text-muted">
          <Icon path={IconPaths.chevron} className={cx('inline-block h-3.5 w-3.5 transition-transform', expanded && 'rotate-90')} />
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-line/60 bg-white/[0.015]">
          <td colSpan={4} className="px-3 py-3">
            {loadingDetail ? (
              <LoadingRows n={3} />
            ) : detailErr ? (
              <ErrorNote message={detailErr} />
            ) : detail ? (
              <div className="space-y-3">
                <div>
                  <div className="mb-1 text-[10.5px] uppercase tracking-[0.08em] text-muted font-mono">Query</div>
                  <p className="text-[12.5px] text-ink font-mono">{detail.query || '—'}</p>
                </div>

                {!detail.found_pipeline_metrics ? (
                  <div className="text-[12px] text-amber font-mono">
                    No matching pipeline_metrics document — contexts/answer unavailable (it may have been deleted).
                  </div>
                ) : (
                  <>
                    <div>
                      <div className="mb-1 text-[10.5px] uppercase tracking-[0.08em] text-muted font-mono">
                        Retrieved contexts ({(detail.contexts || []).length})
                      </div>
                      {(detail.contexts || []).length === 0 ? (
                        <p className="text-[12px] text-muted font-mono">(none stored)</p>
                      ) : (
                        <div className="space-y-2">
                          {detail.contexts.map((c: string, i: number) => (
                            <div key={i} className="rounded-md border border-line bg-surface2/60 p-2.5">
                              <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-muted font-mono">Context {i + 1}</div>
                              <p className="whitespace-pre-wrap text-[12px] text-ink2 font-mono">{c}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div>
                      <div className="mb-1 text-[10.5px] uppercase tracking-[0.08em] text-muted font-mono">Answer</div>
                      <div className="rounded-md border border-signal/20 bg-signal/[0.04] p-2.5">
                        <p className="whitespace-pre-wrap text-[12.5px] text-ink2 font-mono">{detail.answer || '—'}</p>
                      </div>
                    </div>
                  </>
                )}
              </div>
            ) : null}
          </td>
        </tr>
      )}
    </>
  );
}

// ============================================================================
// INGEST
// ============================================================================

type IngestSub = 'scrape' | 'pdf' | 'flat' | 'documents' | 'test';

function IngestView() {
  const [sub, setSub] = useState<IngestSub>('scrape');
  // shared "staged content" produced by scrape/pdf, carried into preview + confirm
  const [staged, setStaged] = useState<{ source: string; title: string; structured: Record<string, string[]> } | null>(null);

  const subTabs: { key: IngestSub; label: string }[] = [
    { key: 'scrape', label: 'Scrape URL' },
    { key: 'pdf', label: 'Upload PDF' },
    { key: 'flat', label: 'Flat text' },
    { key: 'documents', label: 'Documents' },
    { key: 'test', label: 'Test retrieval' },
  ];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-[22px] font-semibold text-ink">Ingest</h1>
        <p className="text-[13px] text-muted mt-0.5">Pull content in, review the chunk breakdown, then confirm into Mongo + Qdrant.</p>
      </header>

      <div className="flex flex-wrap gap-1 border-b border-line pb-2">
        {subTabs.map((s) => (
          <button
            key={s.key}
            onClick={() => setSub(s.key)}
            className={cx('rounded-md px-3 py-1.5 text-[12.5px] font-mono', sub === s.key ? 'bg-signal/10 text-signal' : 'text-muted hover:text-ink')}
          >
            {s.label}
          </button>
        ))}
      </div>

      {sub === 'scrape' && <ScrapeUrlPanel onStaged={setStaged} />}
      {sub === 'pdf' && <ScrapePdfPanel onStaged={setStaged} />}
      {sub === 'flat' && <FlatTextPanel />}
      {sub === 'documents' && <DocumentsPanel />}
      {sub === 'test' && <TestRetrievalPanel />}

      {(sub === 'scrape' || sub === 'pdf') && staged && <StructuredReviewPanel staged={staged} onCleared={() => setStaged(null)} />}
    </div>
  );
}

function ScrapeUrlPanel({ onStaged }: { onStaged: (s: { source: string; title: string; structured: Record<string, string[]> }) => void }) {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const run = async () => {
    if (!url.trim()) return;
    setLoading(true);
    setErr(null);
    setResult(null);
    try {
      const r = await postJson('/api/admin/scrape/url', { url: url.trim() });
      setResult(r);
      onStaged({ source: r.source, title: r.title, structured: r.structured });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel>
      <PanelHead title="Scrape a webpage" sub="fetches + extracts structured heading/content — does not ingest yet" />
      <div className="flex gap-2">
        <TextInput placeholder="https://vit.ac.in/admissions" value={url} onChange={(e) => setUrl(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} />
        <Button variant="primary" onClick={run} disabled={loading}>
          <Icon path={IconPaths.search} className="h-3.5 w-3.5" /> {loading ? 'Fetching…' : 'Fetch'}
        </Button>
      </div>
      {err && <div className="mt-3"><ErrorNote message={err} /></div>}
      {result && (
        <div className="mt-4 grid grid-cols-3 gap-3 text-[12.5px]">
          <Stat label="Sections" value={result.section_count} />
          <Stat label="Words" value={fmtNum(result.word_count)} />
          <Stat label="Truncated" value={result.truncated ? 'yes' : 'no'} tone={result.truncated ? 'warn' : 'good'} />
        </div>
      )}
    </Panel>
  );
}

function ScrapePdfPanel({ onStaged }: { onStaged: (s: { source: string; title: string; structured: Record<string, string[]> }) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const run = async () => {
    if (!file) return;
    setLoading(true);
    setErr(null);
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const r = await postForm('/api/admin/scrape/pdf', form);
      setResult(r);
      onStaged({ source: r.source, title: r.title, structured: r.structured });
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel>
      <PanelHead title="Upload a PDF" sub="runs Docling extraction + hierarchical chunk preview" />
      <div className="flex items-center gap-2">
        <input ref={inputRef} type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] || null)} className="hidden" />
        <Button variant="default" onClick={() => inputRef.current?.click()}>
          <Icon path={IconPaths.upload} className="h-3.5 w-3.5" /> Choose PDF
        </Button>
        <span className="text-[12.5px] text-muted font-mono">{file ? file.name : 'no file selected'}</span>
        <Button variant="primary" onClick={run} disabled={!file || loading} className="ml-auto">
          {loading ? 'Processing…' : 'Process PDF'}
        </Button>
      </div>
      {err && <div className="mt-3"><ErrorNote message={err} /></div>}
      {result && (
        <div className="mt-4 grid grid-cols-3 gap-3 text-[12.5px] md:grid-cols-6">
          <Stat label="Pages" value={result.page_count} />
          <Stat label="Sections" value={result.section_count} />
          <Stat label="Grandchild" value={result.grandchild_count} />
          <Stat label="Child" value={result.child_count} />
          <Stat label="Words" value={fmtNum(result.word_count)} />
          <Stat label="Engine" value={result.chunking_engine} />
        </div>
      )}
    </Panel>
  );
}

function StructuredReviewPanel({ staged, onCleared }: { staged: { source: string; title: string; structured: Record<string, string[]> }; onCleared: () => void }) {
  const [structured, setStructured] = useState(staged.structured);
  const [title, setTitle] = useState(staged.title);
  const [source, setSource] = useState(staged.source);
  const [preview, setPreview] = useState<any>(null);
  const [previewing, setPreviewing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmResult, setConfirmResult] = useState<any>(null);

  useEffect(() => {
    setStructured(staged.structured);
    setTitle(staged.title);
    setSource(staged.source);
    setPreview(null);
    setConfirmResult(null);
  }, [staged]);

  const headings = Object.keys(structured || {});

  const updateHeadingText = (heading: string, text: string) => {
    setStructured((prev) => ({ ...prev, [heading]: text.split('\n').filter((l) => l.trim().length > 0) }));
  };

  const runPreview = async () => {
    setPreviewing(true);
    setErr(null);
    try {
      const r = await postJson('/api/admin/scrape/preview-chunks', { url: source, structured });
      setPreview(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setPreviewing(false);
    }
  };

  const confirm = async () => {
    setConfirming(true);
    setErr(null);
    setConfirmResult(null);
    try {
      const r = await postJson('/api/admin/ingest/confirm', { source, title, structured });
      setConfirmResult(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <Panel>
      <PanelHead title="Review &amp; ingest" sub={`${headings.length} heading section(s) staged from "${staged.source}"`} right={<Button variant="ghost" onClick={onCleared}>Clear</Button>} />

      <div className="grid gap-3 md:grid-cols-2 mb-4">
        <Field label="Title"><TextInput value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="Source"><TextInput value={source} onChange={(e) => setSource(e.target.value)} /></Field>
      </div>

      <div className="max-h-[360px] space-y-3 overflow-y-auto pr-1 mb-4">
        {headings.map((h) => (
          <div key={h}>
            <div className="mb-1 text-[12px] font-mono text-ink2">{h}</div>
            <TextArea rows={3} value={(structured[h] || []).join('\n')} onChange={(e) => updateHeadingText(h, e.target.value)} />
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="default" onClick={runPreview} disabled={previewing}>
          {previewing ? 'Building preview…' : 'Preview chunks'}
        </Button>
        <Button variant="primary" onClick={confirm} disabled={confirming}>
          <Icon path={IconPaths.check} className="h-3.5 w-3.5" /> {confirming ? 'Ingesting…' : 'Confirm & ingest'}
        </Button>
      </div>

      {err && <div className="mt-3"><ErrorNote message={err} /></div>}

      {preview && (
        <div className="mt-4 grid grid-cols-3 gap-3">
          <Stat label="Grandchild" value={preview.counts?.grandchild} />
          <Stat label="Child" value={preview.counts?.child} />
          <Stat label="Parent" value={preview.counts?.parent} />
        </div>
      )}

      {confirmResult && (
        <div className="mt-4 rounded-md border border-signal/30 bg-signal/10 px-3 py-2 text-[12.5px] text-signal font-mono">
          Ingested successfully — {JSON.stringify(confirmResult).slice(0, 200)}
        </div>
      )}
    </Panel>
  );
}

function FlatTextPanel() {
  const [source, setSource] = useState('');
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [chunkSize, setChunkSize] = useState(800);
  const [chunkOverlap, setChunkOverlap] = useState(120);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<any>(null);

  const run = async () => {
    setLoading(true);
    setErr(null);
    setResult(null);
    try {
      const r = await postJson('/api/admin/ingest/confirm', {
        source,
        title,
        text,
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
      });
      setResult(r);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel>
      <PanelHead title="Ingest flat text" sub="splits with RecursiveCharacterTextSplitter — for content without natural headings" />
      <div className="grid gap-3 md:grid-cols-2 mb-3">
        <Field label="Source / URL"><TextInput value={source} onChange={(e) => setSource(e.target.value)} placeholder="manual:hostel-rules-2026" /></Field>
        <Field label="Title"><TextInput value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Hostel rules 2026" /></Field>
      </div>
      <Field label="Text">
        <TextArea rows={8} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste raw content here…" />
      </Field>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <Field label="Chunk size"><TextInput type="number" className="w-28" value={chunkSize} onChange={(e) => setChunkSize(Number(e.target.value))} /></Field>
        <Field label="Chunk overlap"><TextInput type="number" className="w-28" value={chunkOverlap} onChange={(e) => setChunkOverlap(Number(e.target.value))} /></Field>
        <Button variant="primary" onClick={run} disabled={loading || !source.trim() || !text.trim()}>
          {loading ? 'Ingesting…' : 'Confirm & ingest'}
        </Button>
      </div>
      {err && <div className="mt-3"><ErrorNote message={err} /></div>}
      {result && (
        <div className="mt-4 rounded-md border border-signal/30 bg-signal/10 px-3 py-2 text-[12.5px] text-signal font-mono">
          Ingested — {JSON.stringify(result).slice(0, 200)}
        </div>
      )}
    </Panel>
  );
}

function DocumentsPanel() {
  const [docs, setDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [purging, setPurging] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const r = await getJson('/api/admin/ingest/documents?limit=100');
      setDocs(r.documents || []);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const purge = async (parentId: string) => {
    if (!confirm(`Purge all vectors + parent doc for:\n${parentId}\n\nThis cannot be undone.`)) return;
    setPurging(parentId);
    try {
      await postJson('/api/admin/ingest/purge', { parent_id: parentId });
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setPurging(null);
    }
  };

  return (
    <Panel>
      <PanelHead title="Ingested documents" sub={`${docs.length} recent`} right={<Button variant="ghost" onClick={load}><Icon path={IconPaths.refresh} className="h-3.5 w-3.5" /></Button>} />
      {loading ? (
        <LoadingRows n={6} />
      ) : (
        <Table
          head={['Source', 'Title', 'Created', 'Action']}
          empty="Nothing ingested yet."
          rows={docs.map((d) => [
            <span key="s" className="text-ink2 max-w-[280px] block truncate">{d.parent_id || d.source}</span>,
            d.title || '—',
            fmtDate(d.createdAt),
            <Button key="p" variant="danger" onClick={() => purge(d.parent_id || d.source)} disabled={purging === (d.parent_id || d.source)}>
              <Icon path={IconPaths.trash} className="h-3 w-3" /> Purge
            </Button>,
          ])}
        />
      )}
    </Panel>
  );
}

function TestRetrievalPanel() {
  const [query, setQuery] = useState('');
  const [includeParent, setIncludeParent] = useState(true);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [results, setResults] = useState<any[] | null>(null);

  const run = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setErr(null);
    setResults(null);
    try {
      const r = await postJson('/api/admin/ingest/test', { query: query.trim(), include_parent: includeParent });
      setResults(r.results || []);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Panel>
      <PanelHead title="Test retrieval" sub="runs a query through the live chat retriever" />
      <div className="flex gap-2">
        <TextInput placeholder="e.g. hostel curfew timings" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} />
        <Button variant="primary" onClick={run} disabled={loading}>
          <Icon path={IconPaths.search} className="h-3.5 w-3.5" /> {loading ? 'Searching…' : 'Run'}
        </Button>
      </div>
      <label className="mt-2 flex items-center gap-2 text-[12.5px] text-muted font-mono">
        <input type="checkbox" checked={includeParent} onChange={(e) => setIncludeParent(e.target.checked)} />
        include parent context
      </label>

      {err && <div className="mt-3"><ErrorNote message={err} /></div>}

      {results && (
        <div className="mt-4 space-y-3">
          {results.length === 0 ? (
            <EmptyState label="No matches." />
          ) : (
            results.map((r, i) => (
              <div key={i} className="rounded-md border border-line bg-surface2/60 p-3">
                <div className="mb-1 flex flex-wrap gap-2 text-[11px] font-mono text-muted">
                  {r.metadata?.heading && <Badge>{r.metadata.heading}</Badge>}
                  {r.metadata?.level && <Badge tone="good">{r.metadata.level}</Badge>}
                  {r.metadata?.source && <span className="truncate">{r.metadata.source}</span>}
                </div>
                <p className="text-[12.5px] text-ink2 font-mono whitespace-pre-wrap">{(r.content || '').slice(0, 500)}</p>
              </div>
            ))
          )}
        </div>
      )}
    </Panel>
  );
}

// ============================================================================
// VECTOR DB
// ============================================================================

type VdbSub = 'stats' | 'sources' | 'orphans' | 'points' | 'duplicates';

function VectorDbView() {
  const [sub, setSub] = useState<VdbSub>('stats');
  const subTabs: { key: VdbSub; label: string }[] = [
    { key: 'stats', label: 'Stats' },
    { key: 'sources', label: 'Sources' },
    { key: 'orphans', label: 'Orphans' },
    { key: 'points', label: 'Points' },
    { key: 'duplicates', label: 'Duplicates' },
  ];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-[22px] font-semibold text-ink">Vector DB</h1>
        <p className="text-[13px] text-muted mt-0.5">Qdrant collection health, cross-checked against MongoDB.</p>
      </header>

      <div className="flex flex-wrap gap-1 border-b border-line pb-2">
        {subTabs.map((s) => (
          <button
            key={s.key}
            onClick={() => setSub(s.key)}
            className={cx('rounded-md px-3 py-1.5 text-[12.5px] font-mono', sub === s.key ? 'bg-signal/10 text-signal' : 'text-muted hover:text-ink')}
          >
            {s.label}
          </button>
        ))}
      </div>

      {sub === 'stats' && <VdbStatsPanel />}
      {sub === 'sources' && <VdbSourcesPanel />}
      {sub === 'orphans' && <VdbOrphansPanel />}
      {sub === 'points' && <VdbPointsPanel />}
      {sub === 'duplicates' && <VdbDuplicatesPanel />}
    </div>
  );
}

function VdbStatsPanel() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setData(await getJson('/api/admin/vectordb/stats'));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <Panel><LoadingRows n={6} /></Panel>;
  if (err) return <ErrorNote message={err} />;

  const sourceMax = Math.max(1, ...(data?.top_sources || []).map((s: any) => s[1]));

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Points" value={fmtNum(data?.points_count)} />
        <Stat label="Indexed" value={fmtNum(data?.indexed_vectors_count)} />
        <Stat label="Sources" value={fmtNum(data?.source_count)} />
        <Stat label="Status" value={<Badge tone={data?.status === 'green' ? 'good' : 'warn'}>{data?.status}</Badge>} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel>
          <PanelHead title="By level" />
          {Object.entries(data?.by_level || {}).map(([lvl, count]) => (
            <BarRow key={lvl} label={lvl} value={count as number} max={Math.max(1, ...Object.values(data?.by_level || {}).map((v: any) => v))} formatted={fmtNum(count as number)} />
          ))}
        </Panel>
        <Panel>
          <PanelHead title="By ingested_by" />
          {Object.entries(data?.by_ingested_by || {}).map(([who, count]) => (
            <BarRow key={who} label={who} value={count as number} max={Math.max(1, ...Object.values(data?.by_ingested_by || {}).map((v: any) => v))} formatted={fmtNum(count as number)} tone="amber" />
          ))}
        </Panel>
      </div>
      <Panel>
        <PanelHead title="Top sources" sub={`${data?.top_sources?.length || 0} of ${fmtNum(data?.source_count)}`} />
        {(data?.top_sources || []).map(([src, count]: [string, number]) => (
          <BarRow key={src} label={src} value={count} max={sourceMax} formatted={fmtNum(count)} />
        ))}
      </Panel>
    </div>
  );
}

function VdbSourcesPanel() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [onlyOrphans, setOnlyOrphans] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const r = await getJson('/api/admin/vectordb/sources?limit=500');
      setRows(r.sources || []);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = onlyOrphans ? rows.filter((r) => !r.has_parent_doc) : rows;

  return (
    <Panel>
      <PanelHead
        title="Sources"
        sub={`${rows.length} total`}
        right={
          <label className="flex items-center gap-2 text-[12px] font-mono text-muted">
            <input type="checkbox" checked={onlyOrphans} onChange={(e) => setOnlyOrphans(e.target.checked)} />
            orphans only
          </label>
        }
      />
      {loading ? (
        <LoadingRows n={8} />
      ) : err ? (
        <ErrorNote message={err} />
      ) : (
        <Table
          head={['Source', 'Grandchild', 'Child', 'Flat', 'Total', 'Parent doc']}
          empty="No sources indexed."
          rows={filtered.slice(0, 200).map((r) => [
            <span key="s" className="block max-w-[320px] truncate text-ink2">{r.source}</span>,
            r.grandchild,
            r.child,
            r.flat,
            r.total,
            r.has_parent_doc ? <Badge tone="good">ok</Badge> : <Badge tone="bad">orphan</Badge>,
          ])}
        />
      )}
    </Panel>
  );
}

function VdbOrphansPanel() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [repairing, setRepairing] = useState<'vector' | 'mongo' | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setData(await getJson('/api/admin/vectordb/orphans'));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const repair = async (side: 'vector' | 'mongo', ids: string[]) => {
    if (!ids.length) return;
    if (!confirm(`Repair ${ids.length} ${side} orphan(s)? This deletes data and cannot be undone.`)) return;
    setRepairing(side);
    try {
      await postJson('/api/admin/vectordb/orphans/repair', { side, parent_ids: ids });
      await load();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setRepairing(null);
    }
  };

  if (loading) return <Panel><LoadingRows n={6} /></Panel>;
  if (err) return <ErrorNote message={err} />;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel>
        <PanelHead
          title="Vector orphans"
          sub="in Qdrant, missing from page_parents"
          right={
            <Button variant="danger" onClick={() => repair('vector', data?.vector_orphans || [])} disabled={repairing !== null || !data?.vector_orphans?.length}>
              <Icon path={IconPaths.trash} className="h-3.5 w-3.5" /> Delete vectors
            </Button>
          }
        />
        {!data?.vector_orphans?.length ? (
          <EmptyState label="None found — in sync." />
        ) : (
          <div className="max-h-[320px] space-y-1 overflow-y-auto font-mono text-[12px] text-ink2">
            {data.vector_orphans.map((id: string) => (
              <div key={id} className="truncate rounded px-2 py-1 hover:bg-white/[0.03]">{id}</div>
            ))}
          </div>
        )}
      </Panel>

      <Panel>
        <PanelHead
          title="Mongo orphans"
          sub="in page_parents, missing from Qdrant"
          right={
            <Button variant="danger" onClick={() => repair('mongo', data?.mongo_orphans || [])} disabled={repairing !== null || !data?.mongo_orphans?.length}>
              <Icon path={IconPaths.trash} className="h-3.5 w-3.5" /> Delete docs
            </Button>
          }
        />
        {!data?.mongo_orphans?.length ? (
          <EmptyState label="None found — in sync." />
        ) : (
          <div className="max-h-[320px] space-y-1 overflow-y-auto font-mono text-[12px] text-ink2">
            {data.mongo_orphans.map((id: string) => (
              <div key={id} className="truncate rounded px-2 py-1 hover:bg-white/[0.03]">{id}</div>
            ))}
          </div>
        )}
      </Panel>

      <Panel className="lg:col-span-2">
        <div className="flex items-center gap-4 text-[12.5px] font-mono text-muted">
          <span>in sync: <span className="text-signal">{fmtNum(data?.in_sync_count)}</span></span>
          <span>vector orphans: <span className="text-coral">{fmtNum(data?.vector_orphan_count)}</span></span>
          <span>mongo orphans: <span className="text-amber">{fmtNum(data?.mongo_orphan_count)}</span></span>
        </div>
      </Panel>
    </div>
  );
}

function VdbPointsPanel() {
  const [source, setSource] = useState('');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [points, setPoints] = useState<any[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);

  const search = async () => {
    if (!source.trim()) return;
    setLoading(true);
    setErr(null);
    setPoints(null);
    setSelected(new Set());
    try {
      const r = await getJson(`/api/admin/vectordb/points?source=${encodeURIComponent(source.trim())}&limit=500`);
      setPoints(r.points || []);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  };

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const deleteSelected = async () => {
    if (!selected.size) return;
    if (!confirm(`Delete ${selected.size} point(s)? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await postJson('/api/admin/vectordb/points/delete', { point_ids: Array.from(selected) });
      await search();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Panel>
      <PanelHead title="Points by source" sub="inspect and surgically remove individual chunks" />
      <div className="flex gap-2">
        <TextInput placeholder="parent_id / source URL" value={source} onChange={(e) => setSource(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} />
        <Button variant="primary" onClick={search} disabled={loading}>
          <Icon path={IconPaths.search} className="h-3.5 w-3.5" /> {loading ? 'Loading…' : 'Search'}
        </Button>
        {points && points.length > 0 && (
          <Button variant="danger" onClick={deleteSelected} disabled={!selected.size || deleting}>
            <Icon path={IconPaths.trash} className="h-3.5 w-3.5" /> Delete ({selected.size})
          </Button>
        )}
      </div>

      {err && <div className="mt-3"><ErrorNote message={err} /></div>}

      {points && (
        <div className="mt-4">
          <Table
            head={['', 'Level', 'Heading', 'Point ID', 'Preview']}
            empty="No points for this source."
            rows={points.map((p) => [
              <input key="c" type="checkbox" checked={selected.has(p.point_id)} onChange={() => toggle(p.point_id)} />,
              <Badge key="l" tone={p.level === 'grandchild' ? 'good' : 'default'}>{p.level}</Badge>,
              p.heading || '—',
              <span key="id" className="text-muted">{p.point_id.slice(0, 12)}…</span>,
              <span key="p" className="block max-w-[320px] truncate text-ink2">{p.content_preview}</span>,
            ])}
          />
        </div>
      )}
    </Panel>
  );
}

function VdbDuplicatesPanel() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      setData(await getJson('/api/admin/vectordb/duplicates'));
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const entries = Object.entries(data?.child_ids_with_multiple_points || {});

  return (
    <Panel>
      <PanelHead title="Duplicate child_ids" sub={data?.note} right={<Button variant="ghost" onClick={load}><Icon path={IconPaths.refresh} className="h-3.5 w-3.5" /></Button>} />
      {loading ? (
        <LoadingRows n={6} />
      ) : err ? (
        <ErrorNote message={err} />
      ) : entries.length === 0 ? (
        <EmptyState label="No duplicates found." />
      ) : (
        <Table
          head={['child_id', 'point count']}
          rows={entries.map(([cid, count]) => [
            <span key="c" className="block max-w-[420px] truncate text-ink2">{cid}</span>,
            <Badge key="n" tone="warn">{count as number}</Badge>,
          ])}
        />
      )}
    </Panel>
  );
}