import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../lib/api';
import { Card, EmptyState } from '../components/ui/States';
import { Spinner } from '../components/ui/Loaders';
import { ApplicabilityBadge, ConfidenceBadge } from '../components/ui/Badge';

export default function WizardPage() {
  const [hsCode, setHsCode] = useState('');
  const [attrs, setAttrs] = useState('{}');
  const [jsonError, setJsonError] = useState('');

  const wizard = useMutation({
    mutationFn: (payload: { hs: string; attrs: Record<string, unknown> }) =>
      api.wizardQuery(payload.hs, payload.attrs),
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setJsonError('');
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(attrs || '{}');
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('must be a JSON object');
      }
    } catch (err) {
      setJsonError(`Invalid product attributes JSON: ${(err as Error).message}`);
      return;
    }
    wizard.mutate({ hs: hsCode, attrs: parsed });
  };

  const results = wizard.data;

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Compliance Wizard</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Enter an HS code and product attributes (JSON) to see which directives apply.
        </p>
      </div>

      <Card>
        <form onSubmit={submit} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-[200px_1fr]">
            <label className="text-sm text-slate-600 dark:text-slate-300">
              HS code
              <input
                value={hsCode}
                onChange={(e) => setHsCode(e.target.value)}
                placeholder="8501.10"
                required
                className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              />
            </label>
            <label className="text-sm text-slate-600 dark:text-slate-300">
              Product attributes (JSON)
              <textarea
                value={attrs}
                onChange={(e) => setAttrs(e.target.value)}
                rows={3}
                spellCheck={false}
                className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 font-mono text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              />
            </label>
          </div>
          <button
            type="submit"
            disabled={wizard.isPending}
            className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50"
          >
            {wizard.isPending && <Spinner className="h-4 w-4 text-white" />}
            Query
          </button>
          {jsonError && <p className="text-sm text-red-600 dark:text-red-400">{jsonError}</p>}
          {wizard.isError && (
            <p className="text-sm text-red-600 dark:text-red-400">{(wizard.error as Error).message}</p>
          )}
        </form>
      </Card>

      {results &&
        (results.length === 0 ? (
          <EmptyState title="No candidate regulations" hint="No directives matched this HS code." />
        ) : (
          <section className="space-y-2">
            <h2 className="font-semibold text-slate-900 dark:text-white">Results ({results.length})</h2>
            <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
              <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                <thead className="bg-slate-50 dark:bg-slate-900">
                  <tr className="text-left text-slate-600 dark:text-slate-300">
                    <th className="px-4 py-2.5 font-semibold">Status</th>
                    <th className="px-4 py-2.5 font-semibold">Regulation</th>
                    <th className="px-4 py-2.5 font-semibold">Juris.</th>
                    <th className="px-4 py-2.5 font-semibold">Conf.</th>
                    <th className="px-4 py-2.5 font-semibold">Missing attrs</th>
                    <th className="px-4 py-2.5 font-semibold">Notes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900">
                  {results.map((r) => (
                    <tr key={r.regulation_id}>
                      <td className="px-4 py-2.5">
                        <ApplicabilityBadge status={r.applicability_status} />
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="text-slate-800 dark:text-slate-200">{r.regulation_title}</div>
                        {r.regulation_summary && (
                          <div className="text-xs text-slate-500 dark:text-slate-400">{r.regulation_summary}</div>
                        )}
                        {r.evidence_references.length > 0 && (
                          <div className="mt-1 text-xs text-slate-400">{r.evidence_references.join(' · ')}</div>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-slate-700 dark:text-slate-300">{r.jurisdiction}</td>
                      <td className="px-4 py-2.5">
                        <ConfidenceBadge value={r.confidence} />
                      </td>
                      <td className="px-4 py-2.5 text-slate-700 dark:text-slate-300">
                        {r.missing_attributes.join(', ') || '—'}
                      </td>
                      <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                        {r.relationship_notes || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
    </section>
  );
}
