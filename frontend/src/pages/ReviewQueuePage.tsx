import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { type ColumnDef, createColumnHelper } from '@tanstack/react-table';
import { api, type QueueItem } from '../lib/api';
import { DataTable } from '../components/DataTable';
import { Pagination } from '../components/Pagination';
import { TableSkeleton, Spinner } from '../components/ui/Loaders';
import { EmptyState, ErrorState, Card } from '../components/ui/States';
import { Badge, ConfidenceBadge } from '../components/ui/Badge';

const col = createColumnHelper<QueueItem>();

export default function ReviewQueuePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [threshold, setThreshold] = useState(0.9);

  const page = Number(params.get('page') ?? '1');
  const perPage = Number(params.get('per_page') ?? '25');
  const jurisdiction = params.get('jurisdiction') ?? '';
  const minConf = params.get('min_conf') ?? '';
  const maxConf = params.get('max_conf') ?? '';

  const query = useQuery({
    queryKey: ['review-queue', page, perPage, jurisdiction, minConf, maxConf],
    queryFn: () =>
      api.reviewQueue({
        page,
        perPage,
        jurisdiction: jurisdiction || undefined,
        minConf: minConf ? Number(minConf) : undefined,
        maxConf: maxConf ? Number(maxConf) : undefined,
      }),
    placeholderData: keepPreviousData,
  });

  const bulk = useMutation({
    mutationFn: () => api.bulkApprove(threshold),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['review-queue'] }),
  });

  const columns = useMemo<ColumnDef<QueueItem, unknown>[]>(
    () =>
      [
        col.accessor('type_label', {
          header: 'Type',
          cell: (c) => <Badge tone={c.row.original.kind === 'field' ? 'blue' : 'slate'}>{c.getValue()}</Badge>,
        }),
        col.accessor('regulation', {
          header: 'Regulation',
          cell: (c) => <span className="line-clamp-1 max-w-[16rem]">{c.getValue()}</span>,
        }),
        col.accessor('jurisdiction', {
          header: 'Jurisdiction',
          cell: (c) => c.getValue() || '—',
        }),
        col.accessor('name', { header: 'Item' }),
        col.accessor('value', {
          header: 'Value',
          cell: (c) => <span className="line-clamp-1 max-w-[16rem]">{c.getValue() || '—'}</span>,
        }),
        col.accessor('confidence', {
          header: 'Conf.',
          cell: (c) => <ConfidenceBadge value={c.getValue()} />,
        }),
        col.accessor('reason_label', {
          header: 'Reason',
          cell: (c) => (
            <span title={c.row.original.reason_hint} className="cursor-help underline decoration-dotted">
              {c.getValue()}
            </span>
          ),
        }),
        col.accessor('appeared', {
          header: 'Appeared',
          cell: (c) => (
            <span title={c.row.original.appeared_rel} className="text-slate-500">
              {c.getValue()}
            </span>
          ),
        }),
      ] as ColumnDef<QueueItem, unknown>[],
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
  const setJurisdiction = (v: string) => {
    if (v) params.set('jurisdiction', v);
    else params.delete('jurisdiction');
    params.set('page', '1');
    setParams(params, { replace: true });
  };
  const setConf = (key: 'min_conf' | 'max_conf', v: string) => {
    if (v) params.set(key, v);
    else params.delete(key);
    params.set('page', '1');
    setParams(params, { replace: true });
  };

  return (
    <section className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-end gap-4">
          <label className="text-sm text-slate-600 dark:text-slate-300">
            Jurisdiction
            <input
              defaultValue={jurisdiction}
              onBlur={(e) => setJurisdiction(e.target.value.trim())}
              onKeyDown={(e) => e.key === 'Enter' && setJurisdiction((e.target as HTMLInputElement).value.trim())}
              placeholder="e.g. EU"
              className="mt-1 block w-32 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
            />
          </label>
          <label className="text-sm text-slate-600 dark:text-slate-300">
            Min confidence
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              defaultValue={minConf}
              onBlur={(e) => setConf('min_conf', e.target.value.trim())}
              onKeyDown={(e) => e.key === 'Enter' && setConf('min_conf', (e.target as HTMLInputElement).value.trim())}
              placeholder="0.00"
              className="mt-1 block w-24 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
            />
          </label>
          <label className="text-sm text-slate-600 dark:text-slate-300">
            Max confidence
            <input
              type="number"
              min={0}
              max={1}
              step={0.05}
              defaultValue={maxConf}
              onBlur={(e) => setConf('max_conf', e.target.value.trim())}
              onKeyDown={(e) => e.key === 'Enter' && setConf('max_conf', (e.target as HTMLInputElement).value.trim())}
              placeholder="1.00"
              className="mt-1 block w-24 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
            />
          </label>
          <div className="flex items-end gap-2">
            <label className="text-sm text-slate-600 dark:text-slate-300">
              Bulk-approve fields ≥
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))}
                className="ml-2 w-20 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              />
            </label>
            <button
              type="button"
              onClick={() => bulk.mutate()}
              disabled={bulk.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              {bulk.isPending && <Spinner className="h-4 w-4 text-white" />}
              Approve
            </button>
            {bulk.isSuccess && (
              <span className="text-sm text-emerald-600 dark:text-emerald-400">
                Approved {bulk.data.approved}
              </span>
            )}
          </div>
        </div>
      </Card>

      {query.isLoading ? (
        <TableSkeleton rows={8} cols={8} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : query.data && query.data.items.length === 0 ? (
        <EmptyState title="Nothing pending" hint="All extracted items have been reviewed." />
      ) : (
        query.data && (
          <div className={query.isFetching ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
            <DataTable
              columns={columns}
              data={query.data.items}
              onRowClick={(row) =>
                navigate(row.kind === 'field' ? `/review/field/${row.id}` : `/review/condition/${row.id}`)
              }
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
