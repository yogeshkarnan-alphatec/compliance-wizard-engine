import clsx from 'clsx';
import type { ReactNode } from 'react';

type Tone = 'green' | 'amber' | 'red' | 'blue' | 'slate';

const TONES: Record<Tone, string> = {
  green: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  amber: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  red: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  blue: 'bg-brand-100 text-brand-700 dark:bg-brand-500/20 dark:text-brand-500',
  slate: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
};

export function Badge({ tone = 'slate', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={clsx('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', TONES[tone])}>
      {children}
    </span>
  );
}

/** Map a regulation ingestion status to a coloured badge. */
export function StatusBadge({ status }: { status: string }) {
  const tone: Tone =
    status === 'ingested'
      ? 'green'
      : status === 'failed'
        ? 'red'
        : status === 'processing' || status === 'queued'
          ? 'amber'
          : 'slate';
  return <Badge tone={tone}>{status}</Badge>;
}

/** Review status (pending / human-approved / auto-approved / rejected). */
export function ReviewBadge({ status }: { status: string }) {
  const tone: Tone =
    status === 'human-approved' || status === 'auto-approved'
      ? 'green'
      : status === 'rejected'
        ? 'red'
        : 'amber';
  return <Badge tone={tone}>{status}</Badge>;
}

/** Ingestion job status (queued / processing / done / failed). */
export function JobStatusBadge({ status }: { status: string }) {
  const tone: Tone =
    status === 'done'
      ? 'green'
      : status === 'failed'
        ? 'red'
        : status === 'processing'
          ? 'blue'
          : 'amber';
  return <Badge tone={tone}>{status}</Badge>;
}

/** Confidence value coloured by band. */
export function ConfidenceBadge({ value }: { value: number }) {
  const tone: Tone = value >= 0.8 ? 'green' : value >= 0.5 ? 'amber' : 'red';
  return <Badge tone={tone}>{value.toFixed(2)}</Badge>;
}

/** Wizard applicability status. */
export function ApplicabilityBadge({ status }: { status: string }) {
  const tone: Tone =
    status === 'APPLIES'
      ? 'green'
      : status === 'EXCLUDED'
        ? 'slate'
        : status === 'POSSIBLY_APPLIES'
          ? 'blue'
          : 'amber';
  return <Badge tone={tone}>{status.replace(/_/g, ' ')}</Badge>;
}
