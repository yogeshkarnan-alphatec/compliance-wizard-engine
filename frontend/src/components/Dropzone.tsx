import { useRef, useState, type DragEvent } from 'react';
import clsx from 'clsx';
import { FileIcon, UploadCloudIcon, XIcon } from './ui/Icons';

interface DropzoneProps {
  file: File | null;
  onFileChange: (file: File | null) => void;
  accept: string[]; // e.g. ['.pdf', '.docx']
  disabled?: boolean;
}

function extOf(name: string): string {
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i).toLowerCase() : '';
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function Dropzone({ file, onFileChange, accept, disabled }: DropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');

  const accepted = (f: File): boolean => {
    if (accept.includes(extOf(f.name))) return true;
    setError(`Unsupported type. Allowed: ${accept.join(', ')}`);
    return false;
  };

  const pick = (f: File | undefined) => {
    if (!f) return;
    setError('');
    if (accepted(f)) onFileChange(f);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    pick(e.dataTransfer.files?.[0]);
  };

  const onDragOver = (e: DragEvent) => {
    e.preventDefault();
    if (!disabled) setDragging(true);
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && !disabled && inputRef.current?.click()}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={() => setDragging(false)}
        className={clsx(
          'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors',
          dragging
            ? 'border-brand-500 bg-brand-50 dark:bg-brand-500/10'
            : 'border-slate-300 hover:border-brand-400 hover:bg-slate-50 dark:border-slate-700 dark:hover:border-brand-500 dark:hover:bg-slate-800/50',
          disabled && 'pointer-events-none opacity-60',
        )}
      >
        <span
          className={clsx(
            'grid h-14 w-14 place-items-center rounded-full transition-colors',
            dragging ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400',
          )}
        >
          <UploadCloudIcon className="h-7 w-7" />
        </span>
        <div>
          <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {dragging ? 'Drop to upload' : 'Drag & drop your document here'}
          </p>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            or <span className="font-medium text-brand-600 dark:text-brand-500">click to browse</span> ·{' '}
            {accept.map((a) => a.replace('.', '').toUpperCase()).join(', ')}
          </p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={accept.join(',')}
          className="hidden"
          onChange={(e) => pick(e.target.files?.[0])}
        />
      </div>

      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}

      {file && (
        <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2.5 dark:border-slate-800 dark:bg-slate-900">
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-brand-100 text-brand-600 dark:bg-brand-500/20 dark:text-brand-500">
              <FileIcon className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-slate-700 dark:text-slate-200">{file.name}</p>
              <p className="text-xs text-slate-400">{humanSize(file.size)}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              onFileChange(null);
              setError('');
              if (inputRef.current) inputRef.current.value = '';
            }}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
            aria-label="Remove file"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </div>
      )}
    </div>
  );
}
