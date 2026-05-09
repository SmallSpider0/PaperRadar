import { cn } from '../lib/utils';

export function PageShell({ sidebar, header, children, sidebarCollapsed = false }) {
  return (
    <div className="min-h-screen w-full bg-slate-50 text-slate-900">
      <div className="flex min-h-screen w-full gap-6 px-3 py-4 lg:px-4 lg:py-6">
        <aside className={cn('hidden shrink-0 transition-all duration-200 lg:block', sidebarCollapsed ? 'w-20' : 'w-72')}>{sidebar}</aside>
        <div className="flex min-w-0 flex-1 flex-col gap-6 pr-2">
          {header}
          <main className="min-w-0">{children}</main>
        </div>
      </div>
    </div>
  );
}

export function Card({ className, children }) {
  return <div className={cn('rounded-xl border border-slate-200 bg-white shadow-panel', className)}>{children}</div>;
}

export function CardContent({ className, children }) {
  return <div className={cn('p-5', className)}>{children}</div>;
}

export function Badge({ className, children, tone = 'default' }) {
  const tones = {
    default: 'bg-slate-100 text-slate-700',
    primary: 'bg-blue-100 text-blue-700',
    success: 'bg-emerald-100 text-emerald-700',
    warning: 'bg-amber-100 text-amber-700',
  };
  return <span className={cn('inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium', tones[tone], className)}>{children}</span>;
}

export function Button({ className, children, variant = 'primary', ...props }) {
  const variants = {
    primary: 'bg-blue-600 text-white hover:bg-blue-700',
    secondary: 'bg-white text-slate-900 border border-slate-200 hover:bg-slate-50',
    ghost: 'bg-transparent text-slate-700 hover:bg-slate-100',
  };
  return (
    <button
      className={cn('inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition', variants[variant], className)}
      {...props}
    >
      {children}
    </button>
  );
}

export function Input(props) {
  return <input className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-0 placeholder:text-slate-400 focus:border-blue-500" {...props} />;
}
