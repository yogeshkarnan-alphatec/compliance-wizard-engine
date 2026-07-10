import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { api, type SearchResult } from '../lib/api';
import { Card, EmptyState, ErrorState } from '../components/ui/States';
import { Spinner } from '../components/ui/Loaders';
import { Badge } from '../components/ui/Badge';
import { Dropzone } from '../components/Dropzone';
import { SearchIcon, UploadCloudIcon, XIcon } from '../components/ui/Icons';

const ACCEPT = ['.pdf', '.docx'];

function SectionHeader({
  icon,
  title,
  subtitle,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-brand-100 text-brand-600 dark:bg-brand-500/20 dark:text-brand-500">
        {icon}
      </span>
      <div>
        <h2 className="font-semibold text-slate-900 dark:text-white">{title}</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
      </div>
    </div>
  );
}

export default function ImportPage() {
  const [input, setInput] = useState('');
  const [query, setQuery] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [flash, setFlash] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null);

  const search = useQuery({
    queryKey: ['search', query],
    queryFn: () => api.search(query),
    enabled: query.length > 0,
  });

  const enqueue = useMutation({
    mutationFn: (r: SearchResult) => api.enqueue(r.celex, r.title),
    onSuccess: (d) => setFlash({ tone: 'ok', text: d.message }),
    onError: (e: Error) => setFlash({ tone: 'err', text: e.message }),
  });

  const upload = useMutation({
    mutationFn: (f: File) => api.upload(f),
    onSuccess: (d) => {
      setFlash({ tone: 'ok', text: d.message });
      setFile(null);
    },
    onError: (e: Error) => setFlash({ tone: 'err', text: e.message }),
  });

  return (
    <section className="space-y-6">
      {flash && (
        <div
          className={
            'flex items-start justify-between gap-3 rounded-lg border px-4 py-3 text-sm ' +
            (flash.tone === 'ok'
              ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-300'
              : 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300')
          }
        >
          <span>{flash.text}</span>
          <button type="button" onClick={() => setFlash(null)} aria-label="Dismiss">
            <XIcon className="h-4 w-4" />
          </button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Search */}
        <Card className="space-y-4">
          <SectionHeader
            icon={<SearchIcon className="h-5 w-5" />}
            title="Search EU legislation"
            subtitle="Find a directive by name, then ingest it from EUR-Lex."
          />
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setQuery(input.trim());
            }}
            className="flex gap-2"
          >
            <div className="relative flex-1">
              <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="e.g. machinery safety"
                className="w-full rounded-lg border border-slate-300 bg-white py-2 pl-9 pr-3 text-sm text-slate-800 placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              />
            </div>
            <button
              type="submit"
              className="inline-flex items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-700"
            >
              {search.isFetching && query ? <Spinner className="h-4 w-4 text-white" /> : null}
              Search
            </button>
          </form>
        </Card>

        {/* Upload */}
        <Card className="space-y-4">
          <SectionHeader
            icon={<UploadCloudIcon className="h-5 w-5" />}
            title="Upload a document"
            subtitle="Already have the file? Drop it in for the same pipeline."
          />
          <Dropzone file={file} onFileChange={setFile} accept={ACCEPT} disabled={upload.isPending} />
          <button
            type="button"
            disabled={!file || upload.isPending}
            onClick={() => file && upload.mutate(file)}
            className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {upload.isPending ? <Spinner className="h-4 w-4 text-white" /> : <UploadCloudIcon className="h-4 w-4" />}
            {upload.isPending ? 'Uploading…' : 'Upload & ingest'}
          </button>
        </Card>
      </div>

      {/* Search results */}
      {query && (
        <div>
          {search.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Spinner className="h-4 w-4" /> Searching EUR-Lex…
            </div>
          ) : search.isError ? (
            <ErrorState message={(search.error as Error).message} onRetry={() => search.refetch()} />
          ) : search.data?.error ? (
            <ErrorState message={search.data.error} />
          ) : search.data ? (
            search.data.results.length === 0 ? (
              <EmptyState title="No matching legislation" hint="Try fewer or different words." />
            ) : (
              <div>
                <p className="mb-2 text-sm text-slate-500 dark:text-slate-400">
                  {search.data.results.length} result{search.data.results.length === 1 ? '' : 's'} for “{query}”
                </p>
                <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
                  <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                    <thead className="bg-slate-50 dark:bg-slate-900">
                      <tr className="text-left text-slate-600 dark:text-slate-300">
                        <th className="px-4 py-2.5 font-semibold">CELEX</th>
                        <th className="px-4 py-2.5 font-semibold">Type</th>
                        <th className="px-4 py-2.5 font-semibold">Title</th>
                        <th className="px-4 py-2.5" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900">
                      {search.data.results.map((r) => (
                        <tr key={r.celex} className="hover:bg-slate-50 dark:hover:bg-slate-800/60">
                          <td className="whitespace-nowrap px-4 py-2.5 font-mono font-medium text-slate-700 dark:text-slate-300">
                            {r.celex}
                          </td>
                          <td className="px-4 py-2.5">
                            <Badge tone="blue">{r.document_type}</Badge>
                          </td>
                          <td className="px-4 py-2.5 text-slate-700 dark:text-slate-300">
                            <span className="line-clamp-2">{r.title}</span>
                          </td>
                          <td className="px-4 py-2.5 text-right">
                            <button
                              type="button"
                              disabled={enqueue.isPending}
                              onClick={() => enqueue.mutate(r)}
                              className="whitespace-nowrap rounded-lg border border-brand-600 px-3 py-1.5 text-sm font-medium text-brand-600 transition-colors hover:bg-brand-50 disabled:opacity-50 dark:hover:bg-brand-500/10"
                            >
                              Ingest →
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          ) : null}
        </div>
      )}
    </section>
  );
}
