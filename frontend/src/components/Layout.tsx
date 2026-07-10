import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';

const BRAND = 'Compliance Wizard';

type SectionMeta = { title: string; subtitle: string };

/** Title + one-line subtitle for the current path. Dynamic detail routes get a
 *  generic title and no subtitle (they render their own contextual heading). */
function sectionMeta(pathname: string): SectionMeta {
  if (pathname === '/regulations')
    return { title: 'All Data', subtitle: 'Every ingested regulation. Click a row for the full extracted record.' };
  if (pathname.startsWith('/regulations/')) return { title: 'Regulation', subtitle: '' };
  if (pathname === '/import')
    return {
      title: 'Import',
      subtitle: 'Search EU legislation and ingest it, or upload a document directly — both run the same pipeline.',
    };
  if (pathname === '/jobs')
    return {
      title: 'Jobs',
      subtitle: 'Documents queued from Import, drained by the background worker. Failed jobs show why inline.',
    };
  if (pathname === '/review')
    return { title: 'Review Queue', subtitle: 'Pending fields and conditions, lowest confidence first. Click a row to review it.' };
  if (pathname.startsWith('/review/field/')) return { title: 'Field review', subtitle: '' };
  if (pathname.startsWith('/review/condition/')) return { title: 'Condition review', subtitle: '' };
  if (pathname === '/review/hs-mapping')
    return {
      title: 'HS / Applicability',
      subtitle: 'HS↔regulation mappings flagged ambiguous or below threshold. Pick the correct code or resolve.',
    };
  if (pathname.startsWith('/review/relationships/')) return { title: 'Relationships', subtitle: '' };
  if (pathname === '/wizard')
    return { title: 'Wizard', subtitle: 'Enter an HS code and product attributes (JSON) to see which directives apply.' };
  if (pathname === '/') return { title: '', subtitle: '' };
  return { title: 'Not found', subtitle: '' };
}

export function Layout() {
  const { pathname } = useLocation();
  const { title, subtitle } = sectionMeta(pathname);

  useEffect(() => {
    document.title = title ? `${title} · ${BRAND}` : BRAND;
  }, [title]);

  return (
    <div className="flex min-h-screen">
      <Sidebar />
      {/* Content column. pt-14 clears the fixed mobile top bar; md screens use the sidebar. */}
      <div className="flex min-w-0 flex-1 flex-col pt-14 md:pt-0">
        {/* Page-title bar. h-20 matches the sidebar's logo header, so this bottom
            rule lines up with the divider under the logo into one continuous line. */}
        <header className="flex h-20 shrink-0 flex-col justify-center border-b border-slate-200 px-4 dark:border-slate-800 sm:px-6 lg:px-8">
          <h1 className="text-2xl font-medium leading-tight text-slate-900 dark:text-white">{title}</h1>
          {subtitle && <p className="truncate text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
        </header>
        <main className="mx-auto w-full px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
