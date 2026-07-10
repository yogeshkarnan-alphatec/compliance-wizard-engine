import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { PageLoader, Spinner } from '../components/ui/Loaders';
import { Card, ErrorState } from '../components/ui/States';
import { ConfidenceBadge, ReviewBadge } from '../components/ui/Badge';

export default function FieldDetailPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const query = useQuery({ queryKey: ['field', id], queryFn: () => api.fieldDetail(id), enabled: !!id });

  const [value, setValue] = useState('');
  const [note, setNote] = useState('');
  const [bodyId, setBodyId] = useState('');

  useEffect(() => {
    if (query.data) setValue(query.data.mapped_value);
  }, [query.data]);

  const action = useMutation({
    mutationFn: (body: { action: string; value?: string; body_id?: string; note?: string }) =>
      api.fieldAction(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review-queue'] });
      navigate('/review');
    },
  });

  if (query.isLoading) return <PageLoader />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  if (!query.data) return null;
  const f = query.data;

  return (
    <article className="space-y-6">
      <div>
        <Link to="/review" className="text-sm text-brand-600 hover:underline dark:text-brand-500">
          ← Review Queue
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white">{f.field_name}</h1>
          <ReviewBadge status={f.review_status} />
          <ConfidenceBadge value={f.confidence} />
        </div>
        <p className="mt-1 text-slate-600 dark:text-slate-300">{f.regulation}</p>
      </div>

      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm dark:border-amber-900/50 dark:bg-amber-950/30">
        <span className="font-medium text-amber-800 dark:text-amber-300">{f.reason_label}</span>
        <span className="text-amber-700 dark:text-amber-400"> — {f.reason_hint}</span>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-500 dark:text-slate-400">
            {f.has_source ? 'Source snippet' : 'Citation'}
          </h2>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm text-slate-700 dark:text-slate-300">
            {f.has_source ? f.snippet : f.reference}
          </pre>
        </Card>
        <Card>
          <h2 className="mb-2 text-sm font-semibold text-slate-500 dark:text-slate-400">Extracted → mapped</h2>
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-sm text-slate-700 dark:text-slate-300">
            {f.raw_value}
          </pre>
          <dl className="mt-3 space-y-1 text-xs text-slate-500 dark:text-slate-400">
            <div>Reference: {f.reference}</div>
            <div>
              Pipeline: {f.extracted_by || '—'} → {f.mapped_by || '—'}
            </div>
          </dl>
        </Card>
      </div>

      <Card>
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Review</h2>

        {f.is_cert_body && f.cert_bodies.length > 0 && (
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="text-sm text-slate-600 dark:text-slate-300">
              Resolve to certification body
              <select
                value={bodyId}
                onChange={(e) => setBodyId(e.target.value)}
                className="mt-1 block w-64 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              >
                <option value="">— select —</option>
                {f.cert_bodies.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!bodyId || action.isPending}
              onClick={() => action.mutate({ action: 'resolve', body_id: bodyId, note })}
              className="rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
            >
              Resolve
            </button>
          </div>
        )}

        <label className="mt-4 block text-sm text-slate-600 dark:text-slate-300">
          Corrected value
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            rows={2}
            className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          />
        </label>
        <label className="mt-3 block text-sm text-slate-600 dark:text-slate-300">
          Reviewer note (optional)
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          />
        </label>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={action.isPending}
            onClick={() => action.mutate({ action: 'approve', note })}
            className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {action.isPending && <Spinner className="h-4 w-4 text-white" />}
            Approve
          </button>
          <button
            type="button"
            disabled={action.isPending}
            onClick={() => action.mutate({ action: 'edit', value, note })}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            Save edit &amp; approve
          </button>
          <button
            type="button"
            disabled={action.isPending}
            onClick={() => action.mutate({ action: 'reject', note })}
            className="rounded-md border border-red-300 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/30"
          >
            Reject
          </button>
        </div>
        {action.isError && (
          <p className="mt-2 text-sm text-red-600 dark:text-red-400">{(action.error as Error).message}</p>
        )}
      </Card>
    </article>
  );
}
