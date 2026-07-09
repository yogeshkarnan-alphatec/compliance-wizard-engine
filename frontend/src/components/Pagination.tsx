import clsx from 'clsx';
import type { PageMeta } from '../lib/api';

interface PaginationProps {
  page: PageMeta;
  perPage: number;
  onPageChange: (page: number) => void;
  onPerPageChange: (perPage: number) => void;
  perPageOptions?: number[];
}

/** Build a compact page-number window with ellipses, e.g. 1 … 4 5 [6] 7 8 … 20. */
function pageWindow(current: number, total: number, radius = 1): (number | '…')[] {
  const pages = new Set<number>([1, total]);
  for (let p = current - radius; p <= current + radius; p++) {
    if (p >= 1 && p <= total) pages.add(p);
  }
  const sorted = [...pages].sort((a, b) => a - b);
  const out: (number | '…')[] = [];
  let prev = 0;
  for (const p of sorted) {
    if (prev && p - prev > 1) out.push('…');
    out.push(p);
    prev = p;
  }
  return out;
}

export function Pagination({
  page,
  perPage,
  onPageChange,
  onPerPageChange,
  perPageOptions = [25, 50, 100],
}: PaginationProps) {
  const window = pageWindow(page.page, page.total_pages);

  return (
    <div className="flex flex-col items-center justify-between gap-3 sm:flex-row">
      <p className="text-sm text-slate-500 dark:text-slate-400">
        {page.total === 0 ? (
          'No results'
        ) : (
          <>
            Showing <span className="font-medium text-slate-700 dark:text-slate-200">{page.start_index}</span>–
            <span className="font-medium text-slate-700 dark:text-slate-200">{page.end_index}</span> of{' '}
            <span className="font-medium text-slate-700 dark:text-slate-200">{page.total}</span>
          </>
        )}
      </p>

      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1 text-sm text-slate-500 dark:text-slate-400">
          Per page
          <select
            value={perPage}
            onChange={(e) => onPerPageChange(Number(e.target.value))}
            className="rounded-md border border-slate-300 bg-white px-2 py-1 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          >
            {perPageOptions.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>

        <nav className="flex items-center gap-1" aria-label="Pagination">
          <PageButton disabled={!page.has_prev} onClick={() => onPageChange(page.page - 1)}>
            ‹
          </PageButton>
          {window.map((p, i) =>
            p === '…' ? (
              <span key={`e${i}`} className="px-2 text-slate-400">
                …
              </span>
            ) : (
              <PageButton key={p} active={p === page.page} onClick={() => onPageChange(p)}>
                {p}
              </PageButton>
            ),
          )}
          <PageButton disabled={!page.has_next} onClick={() => onPageChange(page.page + 1)}>
            ›
          </PageButton>
        </nav>
      </div>
    </div>
  );
}

function PageButton({
  children,
  onClick,
  active,
  disabled,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'min-w-[2rem] rounded-md px-2.5 py-1 text-sm font-medium transition-colors',
        active
          ? 'bg-brand-600 text-white'
          : 'text-slate-600 hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-transparent dark:text-slate-300 dark:hover:bg-slate-800',
      )}
    >
      {children}
    </button>
  );
}
