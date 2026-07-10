import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import { PageLoader, Spinner } from '../components/ui/Loaders';
import { Card, ErrorState } from '../components/ui/States';
import { Badge, ConfidenceBadge, ReviewBadge } from '../components/ui/Badge';

export default function ConditionDetailPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const query = useQuery({ queryKey: ['condition', id], queryFn: () => api.conditionDetail(id), enabled: !!id });

  const [paramName, setParamName] = useState('');
  const [rawText, setRawText] = useState('');

  useEffect(() => {
    if (query.data) {
      setParamName(query.data.parameter_name);
      setRawText(query.data.raw_text);
    }
  }, [query.data]);

  const action = useMutation({
    mutationFn: (body: { action: string; parameter_name?: string; raw_text?: string }) =>
      api.conditionAction(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['review-queue'] });
      navigate('/review');
    },
  });

  if (query.isLoading) return <PageLoader />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  if (!query.data) return null;
  const c = query.data;

  return (
    <article className="space-y-6">
      <div>
        <Link to="/review" className="text-sm text-brand-600 hover:underline dark:text-brand-500">
          ← Review Queue
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
            {c.parameter_name || 'Applicability condition'}
          </h1>
          <ReviewBadge status={c.review_status} />
          <ConfidenceBadge value={c.confidence} />
          <Badge tone={c.is_structured ? 'green' : 'amber'}>
            {c.is_structured ? 'structured' : 'unstructured'}
          </Badge>
        </div>
        <p className="mt-1 text-slate-600 dark:text-slate-300">{c.regulation}</p>
      </div>

      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm dark:border-amber-900/50 dark:bg-amber-950/30">
        <span className="font-medium text-amber-800 dark:text-amber-300">{c.reason_label}</span>
        <span className="text-amber-700 dark:text-amber-400"> — {c.reason_hint}</span>
      </div>

      <Card>
        <dl className="space-y-2 text-sm">
          <div className="flex gap-3">
            <dt className="w-32 shrink-0 text-slate-500 dark:text-slate-400">Summary</dt>
            <dd className="text-slate-800 dark:text-slate-200">{c.summary}</dd>
          </div>
          <div className="flex gap-3">
            <dt className="w-32 shrink-0 text-slate-500 dark:text-slate-400">Type</dt>
            <dd className="text-slate-800 dark:text-slate-200">{c.condition_type}</dd>
          </div>
          <div className="flex gap-3">
            <dt className="w-32 shrink-0 text-slate-500 dark:text-slate-400">Reference</dt>
            <dd className="text-slate-800 dark:text-slate-200">{c.reference}</dd>
          </div>
        </dl>
      </Card>

      <Card>
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Review</h2>
        <label className="mt-3 block text-sm text-slate-600 dark:text-slate-300">
          Parameter name
          <input
            value={paramName}
            onChange={(e) => setParamName(e.target.value)}
            className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          />
        </label>
        <label className="mt-3 block text-sm text-slate-600 dark:text-slate-300">
          Raw clause
          <textarea
            value={rawText}
            onChange={(e) => setRawText(e.target.value)}
            rows={3}
            className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
          />
        </label>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={action.isPending}
            onClick={() => action.mutate({ action: 'approve' })}
            className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            {action.isPending && <Spinner className="h-4 w-4 text-white" />}
            Approve
          </button>
          <button
            type="button"
            disabled={action.isPending}
            onClick={() => action.mutate({ action: 'edit', parameter_name: paramName, raw_text: rawText })}
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            Save edit &amp; approve
          </button>
          <button
            type="button"
            disabled={action.isPending}
            onClick={() => action.mutate({ action: 'reject' })}
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
