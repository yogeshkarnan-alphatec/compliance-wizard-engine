import { useEffect } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api, type Condition, type HsMap, type Relationship } from '../lib/api';
import { PageLoader } from '../components/ui/Loaders';
import { ErrorState, Card } from '../components/ui/States';
import { Badge, StatusBadge } from '../components/ui/Badge';
import { MiniPagination } from '../components/ui/MiniPagination';
import { useClientPage } from '../hooks/useClientPage';
import { formatDate, formatDateTime } from '../lib/format';
import type { ReactNode } from 'react';

const SECTION_PAGE_SIZE = 8;

function confTone(c: number) {
  return c >= 0.8 ? 'green' : c >= 0.5 ? 'amber' : 'red';
}

/** One-line constraint for a structured condition (operator + bounds/enum/bool + unit). */
function conditionConstraint(c: Condition): string {
  if (!c.structured) return 'unstructured';
  const parts: string[] = [];
  if (c.operator) parts.push(c.operator);
  if (c.value_min != null) parts.push(`min=${c.value_min}`);
  if (c.value_max != null) parts.push(`max=${c.value_max}`);
  if (c.value_enum != null) parts.push(`in [${c.value_enum.join(', ')}]`);
  if (c.value_bool != null) parts.push(`=${c.value_bool}`);
  if (c.unit) parts.push(c.unit);
  return parts.join(' ') || '—';
}

function MetaRow({ label, children }: { label: string; children: ReactNode }) {
  if (children === '' || children == null) return null;
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
      <dt className="w-40 shrink-0 text-sm font-medium text-slate-500 dark:text-slate-400">{label}</dt>
      <dd className="text-sm text-slate-800 dark:text-slate-200">{children}</dd>
    </div>
  );
}

function SectionTable({ head, children }: { head: ReactNode; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
      <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
        <thead className="bg-slate-50 dark:bg-slate-900">
          <tr className="text-left text-slate-600 dark:text-slate-300">{head}</tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900">
          {children}
        </tbody>
      </table>
    </div>
  );
}

const th = 'px-4 py-2.5 font-semibold whitespace-nowrap';
const td = 'px-4 py-2.5 text-slate-700 dark:text-slate-300 align-top';

function RelationshipsSection({ relationships, regId }: { relationships: Relationship[]; regId: string }) {
  const p = useClientPage(relationships, SECTION_PAGE_SIZE);
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-900 dark:text-white">Relationships ({relationships.length})</h2>
        <Link to={`/review/relationships/${regId}`} className="text-sm text-brand-600 hover:underline dark:text-brand-500">
          Review edges →
        </Link>
      </div>
      {relationships.length === 0 ? (
        <p className="text-sm text-slate-500">None.</p>
      ) : (
        <>
          <SectionTable
            head={
              <>
                <th className={th}>Type</th>
                <th className={th}>Target</th>
                <th className={th}>Source</th>
                <th className={th}>Conf.</th>
              </>
            }
          >
            {p.pageItems.map((r, i) => (
              <tr key={p.start + i}>
                <td className={td}>{r.relation_type}</td>
                <td className={td}>{r.target}</td>
                <td className={td}>{r.source}</td>
                <td className={td}>
                  <Badge tone={confTone(r.confidence)}>{r.confidence.toFixed(2)}</Badge>
                </td>
              </tr>
            ))}
          </SectionTable>
          <MiniPagination {...p} onPage={p.setPage} />
        </>
      )}
    </section>
  );
}

function HsSection({ hs }: { hs: HsMap[] }) {
  const p = useClientPage(hs, SECTION_PAGE_SIZE);
  return (
    <section className="space-y-2">
      <h2 className="font-semibold text-slate-900 dark:text-white">HS mappings ({hs.length})</h2>
      {hs.length === 0 ? (
        <p className="text-sm text-slate-500">None.</p>
      ) : (
        <>
          <SectionTable
            head={
              <>
                <th className={th}>HS code</th>
                <th className={th}>Match</th>
                <th className={th}>Conf.</th>
                <th className={th}>Status</th>
              </>
            }
          >
            {p.pageItems.map((h, i) => (
              <tr key={p.start + i}>
                <td className={td}>{h.hs_code}</td>
                <td className={td}>{h.match_type}</td>
                <td className={td}>
                  <Badge tone={confTone(h.confidence)}>{h.confidence.toFixed(2)}</Badge>
                </td>
                <td className={td}>{h.review_status}</td>
              </tr>
            ))}
          </SectionTable>
          <MiniPagination {...p} onPage={p.setPage} />
        </>
      )}
    </section>
  );
}

export default function RegulationDetailPage() {
  const { id = '' } = useParams();
  const query = useQuery({
    queryKey: ['regulation', id],
    queryFn: () => api.regulation(id),
    enabled: Boolean(id),
  });

  // Refine the tab title to the specific CELEX id once the record loads.
  const sourceId = query.data?.reg.source_id;
  useEffect(() => {
    if (sourceId) document.title = `${sourceId} · Compliance Wizard`;
  }, [sourceId]);

  if (query.isLoading) return <PageLoader />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} onRetry={() => query.refetch()} />;
  if (!query.data) return null;

  const { reg, field_groups, total_fields, conditions, relationships, hs } = query.data;

  return (
    <article className="space-y-6">
      <div>
        <Link to="/regulations" className="text-sm text-brand-600 hover:underline dark:text-brand-500">
          ← All Data
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white">{reg.source_id}</h1>
          <StatusBadge status={reg.status} />
          {reg.document_type && <Badge tone="blue">{reg.document_type}</Badge>}
        </div>
        <p className="mt-1 text-slate-600 dark:text-slate-300">{reg.title || '(no title)'}</p>
      </div>

      <Card>
        <dl className="space-y-2">
          <MetaRow label="Jurisdiction">{reg.jurisdiction}</MetaRow>
          <MetaRow label="Publication date">
            {reg.publication_date ? formatDate(reg.publication_date) : ''}
          </MetaRow>
          <MetaRow label="Entry into force">
            {reg.entry_into_force_date ? formatDate(reg.entry_into_force_date) : ''}
          </MetaRow>
          <MetaRow label="OJ reference">{reg.oj_reference}</MetaRow>
          <MetaRow label="Created">
            <span title={formatDateTime(reg.created_at)}>{formatDate(reg.created_at)}</span>
          </MetaRow>
          <MetaRow label="Summary">{reg.summary}</MetaRow>
          <MetaRow label="File">{reg.file_path || '(acquired via EUR-Lex — no PDF)'}</MetaRow>
        </dl>
      </Card>

      <section className="space-y-2">
        <h2 className="font-semibold text-slate-900 dark:text-white">
          Fields ({field_groups.length} fields · {total_fields} values)
        </h2>
        {field_groups.length === 0 ? (
          <p className="text-sm text-slate-500">No fields extracted.</p>
        ) : (
          <SectionTable
            head={
              <>
                <th className={th}>Field</th>
                <th className={th}>Value(s)</th>
                <th className={th}>Reference / segment</th>
                <th className={th}>Conf.</th>
                <th className={th}>Status</th>
              </>
            }
          >
            {field_groups.map((g) => (
              <tr key={g.field_name}>
                <td className={td}>
                  {g.field_name}
                  {g.count > 1 && <span className="ml-1 text-xs text-slate-400">×{g.count}</span>}
                </td>
                <td className={td}>
                  {g.count === 1 ? (
                    g.entries[0].value || '—'
                  ) : (
                    <>
                      <ul className="list-disc space-y-0.5 pl-4">
                        {g.entries.map((e, i) => (
                          <li key={i}>
                            {e.value || '—'}
                            {e.review_status !== 'auto-approved' && (
                              <span className="ml-1 text-xs text-slate-400">· {e.review_status}</span>
                            )}
                          </li>
                        ))}
                      </ul>
                      <details className="mt-1">
                        <summary className="cursor-pointer text-xs text-slate-500">
                          show per-item detail ({g.count})
                        </summary>
                        <div className="mt-1 overflow-x-auto">
                          <table className="min-w-full text-xs">
                            <thead className="text-slate-500">
                              <tr className="text-left">
                                <th className="py-1 pr-3 font-medium">Value</th>
                                <th className="py-1 pr-3 font-medium">Reference</th>
                                <th className="py-1 pr-3 font-medium">Seg</th>
                                <th className="py-1 pr-3 font-medium">Conf.</th>
                                <th className="py-1 font-medium">Status</th>
                              </tr>
                            </thead>
                            <tbody>
                              {g.entries.map((e, i) => (
                                <tr key={i} className="align-top">
                                  <td className="py-1 pr-3">{e.value || '—'}</td>
                                  <td className="py-1 pr-3">{e.reference || '—'}</td>
                                  <td className="py-1 pr-3">{e.segment ?? '—'}</td>
                                  <td className="py-1 pr-3">{e.confidence.toFixed(2)}</td>
                                  <td className="py-1">{e.review_status}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    </>
                  )}
                </td>
                <td className={td}>
                  {g.count === 1 ? (
                    <>
                      {g.entries[0].reference || '—'}
                      {g.entries[0].segment != null && (
                        <span className="text-slate-400"> · seg {g.entries[0].segment}</span>
                      )}
                    </>
                  ) : (
                    <span className="text-slate-400">{g.count} sources</span>
                  )}
                </td>
                <td className={td}>
                  {g.count === 1 ? (
                    <Badge tone={confTone(g.entries[0].confidence)}>{g.entries[0].confidence.toFixed(2)}</Badge>
                  ) : (
                    <Badge tone={confTone(g.min_conf)}>≥{g.min_conf.toFixed(2)}</Badge>
                  )}
                </td>
                <td className={td}>{g.status}</td>
              </tr>
            ))}
          </SectionTable>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="font-semibold text-slate-900 dark:text-white">Applicability conditions ({conditions.length})</h2>
        {conditions.length === 0 ? (
          <p className="text-sm text-slate-500">None.</p>
        ) : (
          <SectionTable
            head={
              <>
                <th className={th}>Parameter</th>
                <th className={th}>Type</th>
                <th className={th}>Structured</th>
                <th className={th}>Constraint</th>
                <th className={th}>Raw text</th>
                <th className={th}>Conf.</th>
                <th className={th}>Status</th>
              </>
            }
          >
            {conditions.map((c, i) => (
              <tr key={i}>
                <td className={td}>{c.parameter_name}</td>
                <td className={td}>{c.condition_type}</td>
                <td className={td}>
                  <Badge tone={c.structured ? 'green' : 'amber'}>{c.structured ? 'yes' : 'no'}</Badge>
                </td>
                <td className={td}>
                  {c.structured ? conditionConstraint(c) : <span className="text-slate-400">unstructured</span>}
                </td>
                <td className={td}>{c.raw_text || '—'}</td>
                <td className={td}>
                  <Badge tone={confTone(c.confidence)}>{c.confidence.toFixed(2)}</Badge>
                </td>
                <td className={td}>{c.review_status}</td>
              </tr>
            ))}
          </SectionTable>
        )}
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <RelationshipsSection relationships={relationships} regId={reg.id} />
        <HsSection hs={hs} />
      </div>
    </article>
  );
}
