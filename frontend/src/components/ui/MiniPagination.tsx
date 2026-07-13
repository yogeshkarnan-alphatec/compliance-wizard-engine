import clsx from 'clsx';

interface MiniPaginationProps {
  page: number;
  totalPages: number;
  total: number;
  start: number;
  end: number;
  onPage: (page: number) => void;
}

/** Compact prev/next pager for in-page sections (no per-page selector). */
export function MiniPagination({ page, totalPages, total, start, end, onPage }: MiniPaginationProps) {
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between px-1 pt-2 text-xs text-slate-500 dark:text-slate-400">
      <span>
        {start}–{end} of {total}
      </span>
      <div className="flex items-center gap-1">
        <Btn disabled={page <= 1} onClick={() => onPage(page - 1)}>
          ‹
        </Btn>
        <span className="px-1">
          {page} / {totalPages}
        </span>
        <Btn disabled={page >= totalPages} onClick={() => onPage(page + 1)}>
          ›
        </Btn>
      </div>
    </div>
  );
}

function Btn({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        'min-w-[1.75rem] rounded-md px-2 py-1 font-medium transition-colors',
        'text-slate-600 hover:bg-slate-100 disabled:opacity-40 disabled:hover:bg-transparent dark:text-slate-300 dark:hover:bg-slate-800',
      )}
    >
      {children}
    </button>
  );
}
