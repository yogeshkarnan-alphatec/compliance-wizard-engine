/** Date/time formatting helpers for ISO strings coming from the API. */

/** Compact date, e.g. "22 Jun 2026". Returns "—" for empty/invalid. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/** Full local date + time, e.g. "22 Jun 2026, 14:30" — used for hover tooltips. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** Coarse relative age, e.g. "3 days ago". Returns "" for empty/invalid. */
export function relativeAge(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const secs = (Date.now() - d.getTime()) / 1000;
  if (secs < 60) return 'just now';
  const mins = secs / 60;
  if (mins < 60) return `${Math.floor(mins)} min ago`;
  const hours = mins / 60;
  if (hours < 24) return `${Math.floor(hours)} hr ago`;
  const days = hours / 24;
  if (days < 30) return `${Math.floor(days)} day${Math.floor(days) === 1 ? '' : 's'} ago`;
  const months = days / 30;
  if (months < 12) return `${Math.floor(months)} mo ago`;
  return `${Math.floor(months / 12)} yr ago`;
}
