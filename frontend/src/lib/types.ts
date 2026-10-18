// API DTOs mirroring backend pydantic schemas (backend/app/schemas/*).

export type Role = "editor" | "doctor" | "admin";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  created_at?: string | null;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  status: string;
  demo_data: boolean;
  summary_status: string;
  created_at?: string | null;
  updated_at?: string | null;
  source_count: number;
  claim_count: number;
  deliverable_count: number;
}

export interface Source {
  id: string;
  project_id: string;
  kind: string;
  original_filename?: string | null;
  url?: string | null;
  doi?: string | null;
  title?: string | null;
  authors?: string[] | null;
  year?: number | null;
  journal?: string | null;
  canonical_url?: string | null;
  status: string;
  error?: string | null;
  page_count?: number | null;
  char_count?: number | null;
  byte_size?: number | null;
  is_sample: boolean;
  created_at?: string | null;
}

export interface SourceDetail extends Source {
  pages: { page: number; chars: number; preview: string }[];
  full_text_preview: string;
  metadata: Record<string, unknown>;
  extraction_method?: string | null;
}

export interface SummaryBucket {
  text?: string;
  page?: number | null;
  source_id?: string | null;
  section?: string | null;
}

export interface ProjectSummary {
  status?: string;
  mode?: string;
  mode_label?: string;
  excluded_sources?: string[];
  [bucket: string]: unknown;
}

export interface ProjectDetail extends Project {
  sources: Source[];
  summary: ProjectSummary | null;
  findings: {
    id: string;
    source_id?: string | null;
    category: string;
    text: string;
    page?: number | null;
    section?: string | null;
  }[];
}

export interface Evidence {
  id: string;
  claim_id: string;
  source_id: string;
  relation: "supports" | "contradicts" | string;
  excerpt: string;
  page?: number | null;
  section?: string | null;
  doi?: string | null;
  url?: string | null;
  locator_method: string;
  source_title?: string | null;
  source_filename?: string | null;
  source_year?: number | null;
  source_journal?: string | null;
}

export type ClaimStatus =
  | "supported"
  | "partially_supported"
  | "unsupported"
  | "conflicting"
  | "needs_human_review";

export interface Claim {
  id: string;
  project_id: string;
  claim_text: string;
  kind: string;
  risk_level: "high" | "medium" | "low" | string;
  population?: string | null;
  study_design?: string | null;
  outcome?: string | null;
  effect_size?: string | null;
  limitations?: string | null;
  status: ClaimStatus | string;
  verification_notes: string;
  created_at?: string | null;
  evidence: Evidence[];
}

export interface SourceExcerpt {
  source_id: string;
  title?: string | null;
  page?: number | null;
  section?: string | null;
  excerpt: string;
  surrounding_text: string;
  doi?: string | null;
  url?: string | null;
}

export interface Slide {
  index: number;
  headline: string;
  body: string;
  claim_ids: string[];
  visual_direction?: string;
  footnote?: string;
}

export interface SourceNote {
  text: string;
  source_id?: string | null;
  doi?: string | null;
  url?: string | null;
}

export interface CarouselPayload {
  concept: string;
  audience: string;
  main_message: string;
  slides: Slide[];
  caption: string;
  hashtags: string[];
  source_notes: SourceNote[];
  limitations: string[];
  disclaimer: string;
}

export interface StaticPayload {
  concept: string;
  audience: string;
  main_message: string;
  headline: string;
  body: string;
  claim_ids: string[];
  visual_direction?: string;
  caption: string;
  hashtags: string[];
  source_notes: SourceNote[];
  limitations: string[];
  disclaimer: string;
}

export interface ReelScene {
  index: number;
  start_seconds: number;
  end_seconds: number;
  on_screen_text: string;
  voiceover: string;
  visual_direction?: string;
  claim_ids: string[];
}

export interface ReelPayload {
  concept: string;
  audience: string;
  main_message: string;
  duration_seconds: number;
  hook: string;
  scenes: ReelScene[];
  on_screen_captions: boolean;
  caption: string;
  hashtags: string[];
  source_notes: SourceNote[];
  limitations: string[];
  disclaimer: string;
  closing_takeaway: string;
}

export interface DeckTable {
  headers: string[];
  rows: string[][];
}

export interface DeckSlide {
  index: number;
  kind: string;
  title: string;
  bullets: string[];
  table?: DeckTable | null;
  claim_ids: string[];
  source_notes: string[];
}

export interface DeckPayload {
  concept: string;
  audience: string;
  main_message: string;
  deck_title: string;
  subtitle: string;
  slides: DeckSlide[];
  caption: string;
  hashtags: string[];
  source_notes: SourceNote[];
  limitations: string[];
  disclaimer: string;
}

export type Payload = CarouselPayload | StaticPayload | ReelPayload | DeckPayload;

export type ExportKind = "full" | "evidence_report" | "source_manifest" | "captions";

export interface ExportResult {
  asset_id: string;
  filename: string;
  download_url: string;
  approved: boolean;
  validation_status: string;
  kind: ExportKind | string;
}

export interface SettingsInfo {
  app: string;
  version: string;
  environment: string;
  demo: boolean;
  ai: { enabled: boolean; provider: string; model?: string | null };
  database: { engine: string; connected: boolean };
  worker: { kind: string; max_workers: number };
  rendering: {
    ffmpeg_available: boolean;
    pptx_available: boolean;
    reel_fps: number;
    carousel_max_slides: number;
  };
  limits: {
    max_upload_bytes: number;
    min_sources_per_project: number;
    max_sources_per_project: number;
  };
}

export interface ClaimStats {
  total: number;
  supported: number;
  partially_supported: number;
  needs_human_review: number;
  conflicting: number;
  unsupported: number;
  high_risk: number;
}

export interface PendingReview {
  deliverable_id: string;
  project_id: string;
  project_name: string;
  format: string;
  version_id?: string | null;
  version_number?: number | null;
  status: string;
  submitted_at?: string | null;
}

export interface SafetyCheck {
  rule: string;
  severity: "error" | "warning" | string;
  message: string;
}

export interface SafetyCheckRow {
  claim_id: string;
  claim_text: string;
  status: string;
  risk_level: string;
  checks: SafetyCheck[];
}

export interface SafetyChecksReport {
  project_id: string;
  note: string;
  totals: { error: number; warning: number };
  claims: SafetyCheckRow[];
  deliverables: {
    deliverable_id: string;
    format: string;
    version_number: number;
    status: string;
    errors: number;
    warnings: number;
  }[];
}

export interface ValidationIssue {
  rule: string;
  severity: "error" | "warning";
  message: string;
  claim_id?: string | null;
  location?: string | null;
}

export interface ValidationReport {
  status?: "passed" | "warnings" | "failed" | "pending" | string;
  issues: ValidationIssue[];
  rules_version?: string;
  checked_at?: string;
  used_claim_ids?: string[];
  counts?: { errors: number; warnings: number };
  note?: string;
}

export interface Asset {
  id: string;
  kind: string;
  filename: string;
  mime: string;
  byte_size?: number | null;
  label?: string | null;
  created_at?: string | null;
}

export interface ContentVersion {
  id: string;
  deliverable_id: string;
  version_number: number;
  payload: Record<string, unknown>;
  generation_mode: string;
  generation_mode_label: string;
  model_name?: string | null;
  prompt_version?: string | null;
  material_hash: string;
  validation: ValidationReport;
  validation_status: string;
  created_at?: string | null;
  assets: Asset[];
}

export interface ReviewRecord {
  id: string;
  deliverable_id: string;
  version_id: string;
  version_number: number;
  reviewer_id?: string | null;
  reviewer_name?: string | null;
  decision: "approved" | "rejected" | "changes_requested" | string;
  comments: string;
  created_at?: string | null;
}

export interface ReviewComment {
  id: string;
  deliverable_id: string;
  version_id?: string | null;
  reviewer_id?: string | null;
  reviewer_name?: string | null;
  body: string;
  anchor?: string | null;
  resolved: boolean;
  created_at?: string | null;
}

export interface PublishingItem {
  id: string;
  deliverable_id: string;
  version_id: string;
  status: "queued" | "ready_to_publish" | "published" | "withdrawn" | string;
  method: string;
  note: string;
  created_at?: string | null;
  published_at?: string | null;
  // enriched by the list endpoint
  project_id: string;
  project_name: string;
  format: string;
  version_number: number;
  concept: string;
  deliverable_status: string;
  eligible: boolean;
  reasons: string[];
  has_export: boolean;
}

export interface Deliverable {
  id: string;
  project_id: string;
  format: "carousel" | "static" | "reel" | string;
  concept: string;
  audience: string;
  main_message: string;
  status: string;
  current_version_id?: string | null;
  approved_version_id?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface DeliverableDetail extends Deliverable {
  versions: ContentVersion[];
  current_version: ContentVersion | null;
  comments: ReviewComment[];
  reviews: ReviewRecord[];
  publishing_item?: PublishingItem | null;
  blocked_claims: string[];
}

export interface StageRun {
  id: string;
  ordinal: number;
  stage: string;
  label: string;
  status: "pending" | "running" | "succeeded" | "failed" | "skipped" | string;
  error?: string | null;
  detail: Record<string, unknown>;
  started_at?: string | null;
  finished_at?: string | null;
  duration_ms?: number | null;
}

export interface PipelineRun {
  id: string;
  project_id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | string;
  mode: string;
  pipeline_version: string;
  error?: string | null;
  meta: Record<string, unknown>;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string | null;
  stages: StageRun[];
}

export interface ActivityItem {
  type: string;
  text: string;
  at?: string | null;
  project_id?: string | null;
}

export interface PipelineStatusRow {
  project_id: string;
  project_name: string;
  project_status: string;
  run_status?: string | null;
  run_kind?: string | null;
  run_id?: string | null;
  stages_total: number;
  stages_succeeded: number;
  failed_stage?: string | null;
  failed_error?: string | null;
}

export interface FailedStageRow {
  run_id: string;
  project_id: string;
  project_name: string;
  stage: string;
  error?: string | null;
  at?: string | null;
}

export interface DashboardStats {
  projects: number;
  papers_processed: number;
  drafts_generated: number;
  awaiting_review: number;
  approved_deliverables: number;
  failed_jobs: number;
  ai_enabled: boolean;
  recent_projects: Project[];
  recent_activity: ActivityItem[];
  pipeline_status: PipelineStatusRow[];
  failed_stage_runs: FailedStageRow[];
  pending_reviews: PendingReview[];
  claim_stats: ClaimStats;
}

export interface HealthInfo {
  status: string;
  app: string;
  version: string;
  ai_enabled: boolean;
  llm_provider: string;
  database: string;
}
