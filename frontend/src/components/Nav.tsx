import { useEffect, useState, type ComponentType, type SVGProps } from 'react';
import { Link, useLocation } from 'react-router-dom';
import clsx from 'clsx';
import { ThemeToggle } from './ThemeToggle';
import { DataIcon, HsIcon, ImportIcon, QueueIcon, WizardIcon, XIcon } from './ui/Icons';

type IconType = ComponentType<SVGProps<SVGSVGElement>>;

const LINKS: { to: string; label: string; Icon: IconType }[] = [
  { to: '/regulations', label: 'All Data', Icon: DataIcon },
  { to: '/import', label: 'Import', Icon: ImportIcon },
  { to: '/review', label: 'Review Queue', Icon: QueueIcon },
  { to: '/review/hs-mapping', label: 'HS / Applicability', Icon: HsIcon },
  { to: '/wizard', label: 'Wizard', Icon: WizardIcon },
];

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

function useScrolled() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  return scrolled;
}

function pillClass(active: boolean) {
  return clsx(
    'group relative flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all',
    active
      ? 'bg-brand-600 text-white shadow-sm shadow-brand-600/30'
      : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white',
  );
}

export function Nav() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const active = activeLink(pathname);
  const scrolled = useScrolled();

  // Close the mobile menu whenever the route changes.
  useEffect(() => setOpen(false), [pathname]);

  return (
    <header
      className={clsx(
        'sticky top-0 z-30 border-b transition-all duration-200',
        scrolled
          ? 'border-slate-200/80 bg-white/85 shadow-sm backdrop-blur-md dark:border-slate-800 dark:bg-slate-950/85'
          : 'border-transparent bg-white/60 backdrop-blur dark:bg-slate-950/60',
      )}
    >
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <div className="flex items-center gap-8">
          <Link to="/regulations" className="flex items-center gap-2.5">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 text-sm font-bold text-white shadow-md shadow-brand-600/30">
              CW
            </span>
            <span className="hidden flex-col leading-none lg:flex">
              <span className="text-sm font-semibold text-slate-900 dark:text-white">Compliance Wizard</span>
              <span className="text-[11px] text-slate-400">Regulation engine</span>
            </span>
          </Link>

          <nav className="hidden items-center gap-1 md:flex">
            {LINKS.map(({ to, label, Icon }) => (
              <Link key={to} to={to} className={pillClass(active === to)}>
                <Icon className={clsx('h-[18px] w-[18px]', active === to ? 'opacity-100' : 'opacity-70')} />
                <span className="hidden lg:inline">{label}</span>
              </Link>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-1.5">
          <ThemeToggle />
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800 md:hidden"
            aria-label="Toggle navigation"
            aria-expanded={open}
          >
            {open ? (
              <XIcon className="h-5 w-5" />
            ) : (
              <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path d="M3 5h14v2H3V5zm0 4h14v2H3V9zm0 4h14v2H3v-2z" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      <div
        className={clsx(
          'overflow-hidden border-t border-slate-200 transition-[max-height,opacity] duration-300 dark:border-slate-800 md:hidden',
          open ? 'max-h-96 opacity-100' : 'max-h-0 border-transparent opacity-0',
        )}
      >
        <nav className="flex flex-col gap-1 px-4 py-3">
          {LINKS.map(({ to, label, Icon }) => (
            <Link key={to} to={to} className={pillClass(active === to)}>
              <Icon className="h-[18px] w-[18px]" />
              {label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
