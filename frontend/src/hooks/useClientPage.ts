import { useMemo, useState } from 'react';

/** Client-side pagination over an in-memory array (already fully fetched). */
export function useClientPage<T>(items: T[], pageSize: number) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const current = Math.min(page, totalPages);

  const pageItems = useMemo(
    () => items.slice((current - 1) * pageSize, current * pageSize),
    [items, current, pageSize],
  );

  return {
    page: current,
    setPage,
    totalPages,
    total: items.length,
    start: items.length === 0 ? 0 : (current - 1) * pageSize + 1,
    end: Math.min(current * pageSize, items.length),
    pageItems,
  };
}
