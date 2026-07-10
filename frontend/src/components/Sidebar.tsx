import { useEffect, useState, type ComponentType, type SVGProps } from 'react';
import { Link, useLocation } from 'react-router-dom';
import clsx from 'clsx';
import { ThemeToggle } from './ThemeToggle';
import {
  ChevronLeftIcon,
  DataIcon,
  HsIcon,
  ImportIcon,
  JobsIcon,
  MenuIcon,
  QueueIcon,
  WizardIcon,
  XIcon,
} from './ui/Icons';

type IconType = ComponentType<SVGProps<SVGSVGElement>>;

const LINKS: { to: string; label: string; Icon: IconType }[] = [
  { to: '/regulations', label: 'All Data', Icon: DataIcon },
  { to: '/import', label: 'Import', Icon: ImportIcon },
  { to: '/jobs', label: 'Jobs', Icon: JobsIcon },
  { to: '/review', label: 'Review Queue', Icon: QueueIcon },
  { to: '/review/hs-mapping', label: 'HS / Applicability', Icon: HsIcon },
  { to: '/wizard', label: 'Wizard', Icon: WizardIcon },
];

const COLLAPSE_KEY = 'sidebar-collapsed';

/** Longest-prefix-wins: on /review/hs-mapping only that link is active, not /review. */
function activeLink(pathname: string): string {
  let best = '';
  for (const l of LINKS) {
    if ((pathname === l.to || pathname.startsWith(l.to + '/')) && l.to.length > best.length) {
      best = l.to;
    }
  }
  return best;
}

/** One nav row. Collapsed (desktop only) → icon-only + tooltip; otherwise icon + label. */
function NavItem({
  to,
  label,
  Icon,
  active,
  collapsed,
}: {
  to: string;
  label: string;
  Icon: IconType;
  active: boolean;
  collapsed: boolean;
}) {
  return (
    <Link
      to={to}
      aria-label={collapsed ? label : undefined}
      className={clsx(
        'group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
        collapsed && 'md:justify-center md:px-0',
        active
          ? 'bg-brand-600 text-white shadow-sm shadow-brand-600/30'
          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white',
      )}
    >
      <Icon className={clsx('h-[18px] w-[18px] shrink-0', active ? 'opacity-100' : 'opacity-70')} />
      <span className={clsx('truncate', collapsed && 'md:hidden')}>{label}</span>

      {/* Collapsed-only hover tooltip. Only shows on desktop (md+), where labels are
          hidden. Anchored above-left so long labels extend right instead of clipping
          off the screen's left edge. */}
      {collapsed && (
        <span
          role="tooltip"
          className="pointer-events-none absolute bottom-full left-0 z-50 mb-1.5 hidden whitespace-nowrap rounded-md bg-slate-900 px-2 py-1 text-xs font-medium text-white shadow-lg dark:bg-slate-700 md:group-hover:block"
        >
          {label}
        </span>
      )}
    </Link>
  );
}

export function Sidebar() {
  const { pathname } = useLocation();
  const active = activeLink(pathname);

  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1');
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
  }, [collapsed]);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => setMobileOpen(false), [pathname]);

  return (
    <>
      {/* Mobile top bar — only surfaces the menu trigger + brand on small screens. */}
      <div className="fixed inset-x-0 top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/85 px-4 backdrop-blur dark:border-slate-800 dark:bg-slate-950/85 md:hidden">
        <button
          type="button"
          onClick={() => setMobileOpen(true)}
          className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          aria-label="Open navigation"
        >
          <MenuIcon className="h-5 w-5" />
        </button>
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-xs font-bold text-white">
          CW
        </span>
        <span className="text-sm font-semibold text-slate-900 dark:text-white">Compliance Wizard</span>
      </div>

      {/* Backdrop for the mobile drawer. */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-sm md:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        className={clsx(
          'z-50 flex flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950',
          // Mobile: off-canvas drawer, fixed width, slides in.
          'fixed inset-y-0 left-0 w-64 transition-transform duration-200',
          mobileOpen ? 'translate-x-0' : '-translate-x-full',
          // Desktop: static sticky column, width animates on collapse.
          'md:sticky md:top-0 md:h-screen md:translate-x-0 md:transition-[width]',
          collapsed ? 'md:w-16' : 'md:w-64',
        )}
      >
        {/* Header: logo + brand, with a close button on mobile. */}
        <div
          className={clsx(
            'flex h-20 items-center gap-2.5 border-b border-slate-200 px-4 dark:border-slate-800',
            collapsed && 'md:justify-center md:px-0',
          )}
        >
          <Link to="/regulations" className="flex min-w-0 items-center gap-2.5">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-bold text-white shadow-md shadow-brand-600/30">
              CW
            </span>
            <span className={clsx('flex min-w-0 flex-col leading-none', collapsed && 'md:hidden')}>
              <span className="truncate text-sm font-semibold text-slate-900 dark:text-white">
                Compliance Wizard
              </span>
              <span className="truncate text-[11px] text-slate-400">Regulation engine</span>
            </span>
          </Link>
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            className="ml-auto rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800 md:hidden"
            aria-label="Close navigation"
          >
            <XIcon className="h-5 w-5" />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-3 md:overflow-visible">
          {LINKS.map(({ to, label, Icon }) => (
            <NavItem key={to} to={to} label={label} Icon={Icon} active={active === to} collapsed={collapsed} />
          ))}
        </nav>

        {/* Footer: theme toggle + desktop collapse control. */}
        <div
          className={clsx(
            'flex items-center gap-2 border-t border-slate-200 p-3 dark:border-slate-800',
            collapsed ? 'md:flex-col' : 'justify-between',
          )}
        >
          <ThemeToggle />
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="hidden items-center gap-2 rounded-lg px-2 py-2 text-sm text-slate-500 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800 md:flex"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand' : 'Collapse'}
          >
            <ChevronLeftIcon className={clsx('h-[18px] w-[18px] transition-transform', collapsed && 'rotate-180')} />
            <span className={clsx(collapsed && 'md:hidden')}>Collapse</span>
          </button>
        </div>
      </aside>
    </>
  );
}
