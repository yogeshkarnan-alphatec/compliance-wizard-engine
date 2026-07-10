import { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { type ColumnDef, createColumnHelper } from '@tanstack/react-table';
import clsx from 'clsx';
import { api, type JobRow } from '../lib/api';
import { DataTable } from '../components/DataTable';
import { Pagination } from '../components/Pagination';
import { TableSkeleton } from '../components/ui/Loaders';
import { EmptyState, ErrorState } from '../components/ui/States';
import { JobStatusBadge } from '../components/ui/Badge';
import { formatDate, relativeAge, formatDateTime } from '../lib/format';

const col = createColumnHelper<JobRow>();

/** A job is still moving while anything is queued or processing — poll then. */
function hasActive(summary: { status: string; count: number }[]): boolean {
  return summary.some((s) => (s.status === 'queued' || s.status === 'processing') && s.count > 0);
}

export default function JobsPage() {
  const [params, setParams] = useSearchParams();

  const page = Number(params.get('page') ?? '1');
  const perPage = Number(params.get('per_page') ?? '25');
  const status = params.get('status') ?? '';

  const query = useQuery({
    queryKey: ['jobs', page, perPage, status],
    queryFn: () => api.jobs({ page, perPage, status: status || undefined }),
    placeholderData: keepPreviousData,
    // Keep the view live while jobs are still draining; idle once everything settled.
    refetchInterval: (q) => (q.state.data && hasActive(q.state.data.summary) ? 5000 : false),
  });

  const columns = useMemo<ColumnDef<JobRow, unknown>[]>(
    () =>
      [
        col.accessor('label', {
          header: 'Document',
          cell: (c) => <span className="line-clamp-1 max-w-[20rem] font-medium">{c.getValue()}</span>,
        }),
        col.accessor('jurisdiction', {
          header: 'Jurisdiction',
          cell: (c) => c.getValue() || '—',
        }),
        col.accessor('status', {
          header: 'Status',
          cell: (c) => <JobStatusBadge status={c.getValue()} />,
        }),
        col.accessor('attempts', { header: 'Attempts' }),
        col.accessor('error', {
          header: 'Detail',
          cell: (c) => {
            const err = c.row.original.error;
            if (!err) return <span className="text-slate-400">—</span>;
            return (
              <span
                title={`${err.stage}: ${err.message}`}
                className="line-clamp-1 max-w-[22rem] cursor-help text-red-600 dark:text-red-400"
              >
                <span className="font-medium">{err.stage}:</span> {err.message}
              </span>
            );
          },
        }),
        col.accessor('updated_at', {
          header: 'Updated',
          cell: (c) => (
            <span title={formatDateTime(c.getValue())} className="whitespace-nowrap text-slate-500">
              {relativeAge(c.getValue()) || formatDate(c.getValue())}
            </span>
          ),
        }),
      ] as ColumnDef<JobRow, unknown>[],
    [],
  );

  const setPage = (p: number) => {
    params.set('page', String(p));
    setParams(params, { replace: true });
  };
  const setPerPage = (n: number) => {
    params.set('per_page', String(n));
    params.set('page', '1');
    setParams(params, { replace: true });
  };
  const setStatus = (s: string) => {
    // Clicking the active chip clears the filter.
    if (s && s !== status) params.set('status', s);
    else params.delete('status');
    params.set('page', '1');
    setParams(params, { replace: true });
  };

  const summary = query.data?.summary ?? [];
  const total = summary.reduce((n, s) => n + s.count, 0);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => setStatus('')}
          className={clsx(
            'flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors',
            status === ''
              ? 'border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-500 dark:bg-brand-500/10 dark:text-brand-400'
              : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800',
          )}
        >
          <span>All</span>
          <span className="text-base font-bold">{total}</span>
        </button>
        {summary.map((s) => (
          <button
            key={s.status}
            type="button"
            onClick={() => setStatus(s.status)}
            className={clsx(
              'flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors',
              status === s.status
                ? 'border-brand-500 bg-brand-50 dark:border-brand-500 dark:bg-brand-500/10'
                : 'border-slate-200 bg-white hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800',
            )}
          >
            <JobStatusBadge status={s.status} />
            <span className="text-base font-bold text-slate-900 dark:text-white">{s.count}</span>
          </button>
        ))}
      </div>

      {query.isLoading ? (
        <TableSkeleton rows={8} cols={6} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : query.data && query.data.rows.length === 0 ? (
        <EmptyState
          title="No jobs"
          hint={status ? `No jobs with status “${status}”.` : 'Queue a document from the Import tab to get started.'}
        />
      ) : (
        query.data && (
          <div className={query.isFetching ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
            <DataTable columns={columns} data={query.data.rows} />
            <div className="mt-4">
              <Pagination
                page={query.data.page}
                perPage={perPage}
                onPageChange={setPage}
                onPerPageChange={setPerPage}
              />
            </div>
          </div>
        )
      )}
    </section>
  );
}
