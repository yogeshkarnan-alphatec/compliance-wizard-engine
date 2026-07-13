/** Typed client for the FastAPI JSON API. All calls go through `http`, which
 *  normalises errors into `HttpError` so React Query surfaces a useful message. */

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'HttpError';
  }
}

async function http<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail: string = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail ?? body?.message ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new HttpError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return (await res.json()) as T;
}

// --- Response types (mirror ui/api/*.py) -----------------------------------

export interface PageMeta {
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
  start_index: number;
  end_index: number;
  has_prev: boolean;
  has_next: boolean;
}

export interface RegulationRow {
  id: string;
  source_id: string;
  title: string;
  document_type: string;
  jurisdiction: string;
  status: string;
  fields: number;
  conditions: number;
  relationships: number;
  created_at: string | null;
}

export interface RegulationsResponse {
  rows: RegulationRow[];
  page: PageMeta;
}

export interface FieldEntry {
  field_name: string;
  value: string;
  reference: string;
  confidence: number;
  review_status: string;
  segment: number | null;
}

export interface FieldGroup {
  field_name: string;
  count: number;
  entries: FieldEntry[];
  min_conf: number;
  status: string;
}

export interface Condition {
  parameter_name: string;
  condition_type: string;
  structured: boolean;
  operator: string;
  value_min: number | null;
  value_max: number | null;
  value_enum: string[] | null;
  value_bool: boolean | null;
  unit: string;
  raw_text: string;
  confidence: number;
  review_status: string;
}

export interface Relationship {
  relation_type: string;
  target: string;
  source: string;
  confidence: number;
}

export interface HsMap {
  hs_code: string;
  match_type: string;
  confidence: number;
  review_status: string;
}

export interface RegulationMeta {
  id: string;
  source_id: string;
  title: string;
  summary: string;
  document_type: string;
  jurisdiction: string;
  status: string;
  publication_date: string | null;
  entry_into_force_date: string | null;
  oj_reference: string;
  file_path: string;
  created_at: string | null;
}

export interface RegulationDetail {
  reg: RegulationMeta;
  field_groups: FieldGroup[];
  total_fields: number;
  conditions: Condition[];
  relationships: Relationship[];
  hs: HsMap[];
}

export interface SearchResult {
  celex: string;
  title: string;
  document_type: string;
}

export interface SearchResponse {
  results: SearchResult[];
  query: string;
  error: string;
}

export interface MessageResponse {
  message: string;
  job_id?: string;
  source_id?: string | null;
}

export interface QueueItem {
  kind: 'field' | 'condition';
  type_label: string;
  id: string;
  regulation: string;
  jurisdiction: string;
  name: string;
  value: string;
  confidence: number;
  reason: string;
  reason_label: string;
  reason_hint: string;
  appeared: string;
  appeared_rel: string;
}

export interface ReviewQueueResponse {
  items: QueueItem[];
  page: PageMeta;
  filters: { jurisdiction: string; min_conf: number; max_conf: number };
}

export interface JobError {
  stage: string;
  message: string;
}

export interface JobRow {
  id: string;
  label: string;
  source_id: string;
  jurisdiction: string;
  status: string;
  attempts: number;
  error: JobError | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface JobStatusCount {
  status: string;
  count: number;
}

export interface JobsResponse {
  rows: JobRow[];
  page: PageMeta;
  summary: JobStatusCount[];
  status: string;
}

export interface CertBody {
  id: string;
  name: string;
}

export interface FieldDetail {
  field_id: string;
  regulation: string;
  field_name: string;
  raw_value: string;
  mapped_value: string;
  reference: string;
  confidence: number;
  reason: string;
  reason_label: string;
  reason_hint: string;
  review_status: string;
  extracted_by: string;
  mapped_by: string;
  has_source: boolean;
  snippet: string;
  is_cert_body: boolean;
  cert_bodies: CertBody[];
}

export interface ConditionDetail {
  condition_id: string;
  regulation: string;
  parameter_name: string;
  summary: string;
  raw_text: string;
  is_structured: boolean;
  condition_type: string;
  reference: string;
  confidence: number;
  reason: string;
  reason_label: string;
  reason_hint: string;
  review_status: string;
}

export interface HsCandidate {
  code: string;
  desc: string;
}

export interface HsRow {
  id: string;
  regulation: string;
  hs_code: string;
  confidence: number;
  match_type: string;
  appeared: string;
  appeared_rel: string;
  candidates: HsCandidate[];
}

export interface HsReviewResponse {
  rows: HsRow[];
  page: PageMeta;
}

export interface RelEdge {
  id: string;
  relation_type: string;
  target: string;
  confidence: number;
  source: string;
}

export interface ChainNode {
  regulation_id: string;
  source_id: string;
  title: string;
  relation_type: string;
  depth: number;
}

export interface RelationshipsResponse {
  regulation_id: string;
  title: string;
  edges: RelEdge[];
  chain: ChainNode[];
  relation_types: string[];
}

export type ApplicabilityStatus = 'APPLIES' | 'EXCLUDED' | 'POSSIBLY_APPLIES' | 'UNCERTAIN';

export interface WizardResult {
  regulation_id: string;
  regulation_title: string;
  regulation_summary: string | null;
  jurisdiction: string;
  applicability_status: ApplicabilityStatus;
  matched_conditions: unknown[];
  missing_attributes: string[];
  evidence_references: string[];
  confidence: number;
  relationship_notes: string | null;
}

// --- Endpoints -------------------------------------------------------------

export const api = {
  regulations: (page: number, perPage: number, includeStubs: boolean) =>
    http<RegulationsResponse>(
      `/api/regulations?page=${page}&per_page=${perPage}&include_stubs=${includeStubs}`,
    ),

  regulation: (id: string) => http<RegulationDetail>(`/api/regulations/${id}`),

  search: (q: string) => http<SearchResponse>(`/api/import/search?q=${encodeURIComponent(q)}`),

  enqueue: (celex: string, title?: string) =>
    http<MessageResponse>('/api/import/enqueue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ celex, title }),
    }),

  upload: (file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return http<MessageResponse>('/api/import/upload', { method: 'POST', body: fd });
  },

  // --- Jobs ----------------------------------------------------------------
  jobs: (params: { page: number; perPage: number; status?: string }) => {
    const q = new URLSearchParams({
      page: String(params.page),
      per_page: String(params.perPage),
    });
    if (params.status) q.set('status', params.status);
    return http<JobsResponse>(`/api/jobs?${q.toString()}`);
  },

  // --- Review queue --------------------------------------------------------
  reviewQueue: (params: {
    page: number;
    perPage: number;
    jurisdiction?: string;
    minConf?: number;
    maxConf?: number;
  }) => {
    const q = new URLSearchParams({
      page: String(params.page),
      per_page: String(params.perPage),
    });
    if (params.jurisdiction) q.set('jurisdiction', params.jurisdiction);
    if (params.minConf != null) q.set('min_conf', String(params.minConf));
    if (params.maxConf != null) q.set('max_conf', String(params.maxConf));
    return http<ReviewQueueResponse>(`/api/review?${q.toString()}`);
  },

  bulkApprove: (threshold: number, reviewer = 'reviewer') =>
    http<{ approved: number }>('/api/review/bulk-approve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ threshold, reviewer }),
    }),

  // --- Field / condition detail --------------------------------------------
  fieldDetail: (id: string) => http<FieldDetail>(`/api/review/field/${id}`),

  fieldAction: (id: string, body: { action: string; value?: string; body_id?: string; note?: string }) =>
    http<{ status: string }>(`/api/review/field/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  conditionDetail: (id: string) => http<ConditionDetail>(`/api/review/condition/${id}`),

  conditionAction: (id: string, body: { action: string; parameter_name?: string; raw_text?: string }) =>
    http<{ status: string }>(`/api/review/condition/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  // --- HS review -----------------------------------------------------------
  hsReview: (page: number, perPage: number) =>
    http<HsReviewResponse>(`/api/review/hs-mapping?page=${page}&per_page=${perPage}`),

  hsAction: (id: string, body: { action: string; chosen_code?: string }) =>
    http<{ status: string }>(`/api/review/hs-mapping/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  // --- Relationships -------------------------------------------------------
  relationships: (regId: string) => http<RelationshipsResponse>(`/api/review/relationships/${regId}`),

  edgeAction: (regId: string, edgeId: string, body: { action: string; relation_type?: string }) =>
    http<{ ok: boolean }>(`/api/review/relationships/${regId}/edge/${edgeId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),

  // --- Wizard --------------------------------------------------------------
  wizardQuery: (hs_code: string, product_attributes: Record<string, unknown>) =>
    http<WizardResult[]>('/api/wizard/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hs_code, product_attributes }),
    }),
};
