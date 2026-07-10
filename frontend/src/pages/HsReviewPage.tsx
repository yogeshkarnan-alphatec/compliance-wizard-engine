import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type HsRow } from '../lib/api';
import { Pagination } from '../components/Pagination';
import { TableSkeleton, Spinner } from '../components/ui/Loaders';
import { Card, EmptyState, ErrorState } from '../components/ui/States';
import { Badge, ConfidenceBadge } from '../components/ui/Badge';

function HsMappingCard({ row, onDone }: { row: HsRow; onDone: () => void }) {
  const [chosen, setChosen] = useState('');
  const action = useMutation({
    mutationFn: (body: { action: string; chosen_code?: string }) => api.hsAction(row.id, body),
    onSuccess: onDone,
  });

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-medium text-slate-800 dark:text-slate-200">{row.regulation}</p>
          <div className="mt-1 flex items-center gap-2 text-sm">
            <span className="font-mono text-slate-700 dark:text-slate-300">{row.hs_code}</span>
            <ConfidenceBadge value={row.confidence} />
            <Badge tone="slate">{row.match_type}</Badge>
            <span className="text-xs text-slate-400" title={row.appeared}>
              {row.appeared_rel}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={chosen}
            onChange={(e) => setChosen(e.target.value)}
            className="max-w-xs rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          >
            <option value="">Choose correct code…</option>
            {row.candidates.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} — {c.desc}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!chosen || action.isPending}
            onClick={() => action.mutate({ action: 'select', chosen_code: chosen })}
            className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            Set
          </button>
          <button
            type="button"
            disabled={action.isPending}
            onClick={() => action.mutate({ action: 'approve' })}
            className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            Approve
          </button>
          <button
            type="button"
            disabled={action.isPending}
            onClick={() => action.mutate({ action: 'reject' })}
            className="rounded-md border border-red-300 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/30"
          >
            Reject
          </button>
          {action.isPending && <Spinner className="h-4 w-4" />}
        </div>
      </div>
    </Card>
  );
}

export default function HsReviewPage() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const page = Number(params.get('page') ?? '1');
  const perPage = Number(params.get('per_page') ?? '25');

  const query = useQuery({
    queryKey: ['hs-review', page, perPage],
    queryFn: () => api.hsReview(page, perPage),
    placeholderData: keepPreviousData,
  });

  const setPage = (p: number) => {
    params.set('page', String(p));
    setParams(params, { replace: true });
  };
  const setPerPage = (n: number) => {
    params.set('per_page', String(n));
    params.set('page', '1');
    setParams(params, { replace: true });
  };
  const invalidate = () => qc.invalidateQueries({ queryKey: ['hs-review'] });

  return (
    <section className="space-y-4">
      {query.isLoading ? (
        <TableSkeleton rows={5} cols={4} />
      ) : query.isError ? (
        <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />
      ) : query.data && query.data.rows.length === 0 ? (
        <EmptyState title="Nothing to review" hint="No HS mappings are currently pending." />
      ) : (
        query.data && (
          <div className={query.isFetching ? 'space-y-3 opacity-60' : 'space-y-3'}>
            {query.data.rows.map((row) => (
              <HsMappingCard key={row.id} row={row} onDone={invalidate} />
            ))}
            <Pagination
              page={query.data.page}
              perPage={perPage}
              onPageChange={setPage}
              onPerPageChange={setPerPage}
            />
          </div>
        )
      )}
    </section>
  );
}
