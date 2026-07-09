import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Nav } from './Nav';

const BRAND = 'Compliance Wizard';

/** Human title for the current path (dynamic detail routes get a generic label). */
function sectionTitle(pathname: string): string {
  if (pathname === '/regulations') return 'All Data';
  if (pathname.startsWith('/regulations/')) return 'Regulation';
  if (pathname === '/import') return 'Import';
  if (pathname === '/review') return 'Review Queue';
  if (pathname.startsWith('/review/field/')) return 'Field review';
  if (pathname.startsWith('/review/condition/')) return 'Condition review';
  if (pathname === '/review/hs-mapping') return 'HS / Applicability';
  if (pathname.startsWith('/review/relationships/')) return 'Relationships';
  if (pathname === '/wizard') return 'Wizard';
  if (pathname === '/') return '';
  return 'Not found';
}

export function Layout() {
  const { pathname } = useLocation();

  useEffect(() => {
    const section = sectionTitle(pathname);
    document.title = section ? `${section} · ${BRAND}` : BRAND;
  }, [pathname]);

  return (
    <div className="min-h-full">
      <Nav />
      <main className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}
