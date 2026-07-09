import { useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { type ColumnDef, createColumnHelper } from '@tanstack/react-table';
import { api, type RegulationRow } from '../lib/api';
import { DataTable } from '../components/DataTable';
import { Pagination } from '../components/Pagination';
import { TableSkeleton } from '../components/ui/Loaders';
import { ErrorState, EmptyState } from '../components/ui/States';
import { StatusBadge } from '../components/ui/Badge';
import { formatDate, formatDateTime } from '../lib/format';

function DateCell({ iso }: { iso: string | null }) {
  return (
    <span title={formatDateTime(iso)} className="whitespace-nowrap text-slate-500 dark:text-slate-400">
      {formatDate(iso)}
    </span>
  );
}

const col = createColumnHelper<RegulationRow>();

export default function RegulationsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();

  const page = Number(params.get('page') ?? '1');
  const perPage = Number(params.get('per_page') ?? '25');
  const includeStubs = params.get('include_stubs') === '1';

  const query = useQuery({
    queryKey: ['regulations', page, perPage, includeStubs],
    queryFn: () => api.regulations(page, perPage, includeStubs),
    placeholderData: keepPreviousData,
  });

  const columns = useMemo<ColumnDef<RegulationRow, unknown>[]>(
    () =>
      [
        col.accessor('source_id', {
          header: 'CELEX / ID',
          cell: (c) => <span className="font-medium text-brand-600 dark:text-brand-500">{c.getValue()}</span>,
        }),
        col.accessor('title', {
          header: 'Title',
          cell: (c) => <span className="line-clamp-1 max-w-md">{c.getValue() || '—'}</span>,
        }),
        col.accessor('document_type', { header: 'Type', cell: (c) => c.getValue() || '—' }),
        col.accessor('jurisdiction', { header: 'Juris.', cell: (c) => c.getValue() || '—' }),
        col.accessor('status', { header: 'Status', cell: (c) => <StatusBadge status={c.getValue()} /> }),
        col.accessor('fields', { header: 'Fields' }),
        col.accessor('conditions', { header: 'Conds' }),
        col.accessor('relationships', { header: 'Rels' }),
        col.accessor('created_at', {
          header: 'Created',
          cell: (c) => <DateCell iso={c.getValue() as string | null} />,
        }),
      ] as ColumnDef<RegulationRow, unknown>[],
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
  const toggleStubs = () => {
    if (includeStubs) params.delete('include_stubs');
    else params.set('include_stubs', '1');
    params.set('page', '1');
    setParams(params, { replace: true });
  };

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white">All Data</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Every ingested regulation. Click a row for the full extracted record.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
          <input
            type="checkbox"
            checked={includeStubs}
            onChange={toggleStubs}
            className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
          />
          Include referenced-only stubs
        </label>
      </div>

      {query.isLoading ? (
        <TableSkeleton rows={perPage > 10 ? 10 : perPage} cols={9} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : query.data && query.data.rows.length === 0 ? (
        <EmptyState title="No regulations yet" hint="Ingest one from the Import page to see it here." />
      ) : (
        query.data && (
          <div className={query.isFetching ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
            <DataTable
              columns={columns}
              data={query.data.rows}
              onRowClick={(row) => navigate(`/regulations/${row.id}`)}
            />
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
