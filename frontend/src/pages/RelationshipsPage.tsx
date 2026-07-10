import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type RelEdge } from '../lib/api';
import { PageLoader, Spinner } from '../components/ui/Loaders';
import { Card, EmptyState, ErrorState } from '../components/ui/States';
import { Badge, ConfidenceBadge } from '../components/ui/Badge';

function EdgeRow({
  edge,
  regId,
  relationTypes,
  onDone,
}: {
  edge: RelEdge;
  regId: string;
  relationTypes: string[];
  onDone: () => void;
}) {
  const action = useMutation({
    mutationFn: (body: { action: string; relation_type?: string }) => api.edgeAction(regId, edge.id, body),
    onSuccess: onDone,
  });

  return (
    <tr>
      <td className="px-4 py-2.5">
        <select
          defaultValue={edge.relation_type}
          onChange={(e) => action.mutate({ action: 'correct', relation_type: e.target.value })}
          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
        >
          {relationTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </td>
      <td className="px-4 py-2.5 text-slate-700 dark:text-slate-300">{edge.target}</td>
      <td className="px-4 py-2.5">
        <Badge tone="slate">{edge.source}</Badge>
      </td>
      <td className="px-4 py-2.5">
        <ConfidenceBadge value={edge.confidence} />
      </td>
      <td className="px-4 py-2.5 text-right">
        <button
          type="button"
          disabled={action.isPending}
          onClick={() => action.mutate({ action: 'delete' })}
          className="inline-flex items-center gap-1 rounded-md border border-red-300 px-2.5 py-1 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/30"
        >
          {action.isPending ? <Spinner className="h-3.5 w-3.5" /> : null}
          Delete
        </button>
      </td>
    </tr>
  );
}

export default function RelationshipsPage() {
  const { id = '' } = useParams();
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ['relationships', id],
    queryFn: () => api.relationships(id),
    enabled: !!id,
  });

  if (query.isLoading) return <PageLoader />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  if (!query.data) return null;
  const data = query.data;
  const invalidate = () => qc.invalidateQueries({ queryKey: ['relationships', id] });

  return (
    <article className="space-y-6">
      <div>
        <Link to={`/regulations/${id}`} className="text-sm text-brand-600 hover:underline dark:text-brand-500">
          ← Regulation
        </Link>
        <h1 className="mt-2 text-xl font-semibold text-slate-900 dark:text-white">Relationships</h1>
        <p className="mt-1 text-slate-600 dark:text-slate-300">{data.title}</p>
      </div>

      <section className="space-y-2">
        <h2 className="font-semibold text-slate-900 dark:text-white">Edges ({data.edges.length})</h2>
        {data.edges.length === 0 ? (
          <EmptyState title="No edges" hint="This regulation has no outgoing relationships." />
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
            <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead className="bg-slate-50 dark:bg-slate-900">
                <tr className="text-left text-slate-600 dark:text-slate-300">
                  <th className="px-4 py-2.5 font-semibold">Type</th>
                  <th className="px-4 py-2.5 font-semibold">Target</th>
                  <th className="px-4 py-2.5 font-semibold">Source</th>
                  <th className="px-4 py-2.5 font-semibold">Conf.</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900">
                {data.edges.map((edge) => (
                  <EdgeRow
                    key={edge.id}
                    edge={edge}
                    regId={id}
                    relationTypes={data.relation_types}
                    onDone={invalidate}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold text-slate-900 dark:text-white">Amendment chain ({data.chain.length})</h2>
        {data.chain.length === 0 ? (
          <p className="text-sm text-slate-500">No amendment/supersession chain.</p>
        ) : (
          <Card>
            <ol className="space-y-2">
              {data.chain.map((node, i) => (
                <li key={`${node.regulation_id}-${i}`} className="flex items-center gap-2 text-sm">
                  <span className="text-xs text-slate-400" style={{ marginLeft: `${(node.depth - 1) * 16}px` }}>
                    ↳
                  </span>
                  <Badge tone="blue">{node.relation_type}</Badge>
                  <span className="font-mono text-slate-500">{node.source_id}</span>
                  <span className="text-slate-700 dark:text-slate-300">{node.title || ''}</span>
                </li>
              ))}
            </ol>
          </Card>
        )}
      </section>
    </article>
  );
}
