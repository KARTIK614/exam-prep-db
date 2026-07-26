/**
 * Hand-rolled TypeScript types mirroring the Rust DTOs in
 * `backend/src/schemas/*.rs` and `backend/src/models/*.rs`. Field names
 * are 1:1 snake_case matches so `JSON.parse` yields these shapes with
 * zero transformation.
 *
 * When a Rust DTO isn't yet implemented on the backend (e.g. analytics
 * endpoints from R4 §3.9), the type below reflects the *plan-document*
 * shape and should be treated as a best-effort guess. Any deviation
 * from the eventual DTO is called out in the Phase 9 report.
 */

// ---------- Error envelope (from AppError::IntoResponse) ------------------

export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    request_id: string | null;
  };
}

/** Thrown by the API client on any non-2xx response. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, requestId: string | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

// ---------- Auth ----------------------------------------------------------

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  name?: string;
}
export interface RegisterResponse {
  user_id: number;
  access_token: string;
  refresh_token: string;
}
export interface LoginRequest {
  username_or_email: string;
  password: string;
}
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  user_id: number;
  role: string;
}
export interface RefreshRequest {
  refresh_token: string;
}
export interface RefreshResponse {
  access_token: string;
  refresh_token: string;
}
export interface LogoutRequest {
  refresh_token?: string;
}
export interface ForgotPasswordRequest {
  email: string;
}
export interface ForgotPasswordResponse {
  message: string;
}
export interface ResetPasswordRequest {
  new_password: string;
}
export interface MeResponse {
  id: number;
  username: string;
  email: string | null;
  role: string;
  created_at: string | null;
  last_login: string | null;
}
export interface UpdateMeRequest {
  email?: string;
  current_password?: string;
  new_password?: string;
}

// ---------- Settings ------------------------------------------------------

export interface UserSettings {
  target_score?: number;
  weak_threshold?: number;
  target_seconds_per_q?: number;
  default_neg_ratio?: number;
  dark_mode?: boolean;
  [k: string]: unknown;
}

// ---------- Topics --------------------------------------------------------

export interface Topic {
  id: number;
  name: string | null;
  subject: string | null;
  paper: string | null;
  weightage: number | null;
}

export interface TopicWithCount extends Topic {
  question_count: number;
}

// ---------- Questions -----------------------------------------------------

export interface Question {
  id: number;
  topic_id: number | null;
  question_text: string | null;
  option_a: string | null;
  option_b: string | null;
  option_c: string | null;
  option_d: string | null;
  correct_option: string | null;
  explanation: string | null;
  difficulty: string | null;
  source: string | null;
  language: string | null;
  disabled: boolean;
  updated_at: string | null;
  confidence: string | null;
  section: string | null;
  sub_topic: string | null;
  pyq_exam: string | null;
  pyq_year: number | null;
  review_notes: string | null;
  confidence_reviewed_at: string | null;
}

export interface QuestionListResponse {
  items: Question[];
  next_cursor: string | null;
}

// ---------- Search --------------------------------------------------------

export interface SearchHit extends Question {
  snippet: string;
  rank: number | null;
}
export interface SearchResponse {
  items: SearchHit[];
  next_cursor: string | null;
  backend: 'fts5' | 'like';
}

// ---------- Tests ---------------------------------------------------------

export interface CreateTestRequest {
  topic_ids: number[];
  question_count: number;
  test_mode: 'practice' | 'exam';
  pyq_only?: boolean;
  pyq_year_min?: number;
  pyq_year_max?: number;
  difficulty?: 'easy' | 'medium' | 'hard' | null;
  neg_marking_preset?: 'none' | 'third' | 'quarter' | 'fifth' | 'custom';
  neg_marking_ratio?: number;
}

export interface CreateTestResponse {
  test_id: number;
  question_ids: number[];
  test_mode: string;
  negative_ratio: number;
}

export interface TestQuestion {
  id: number;
  question_text: string | null;
  option_a: string | null;
  option_b: string | null;
  option_c: string | null;
  option_d: string | null;
  order_index: number;
}

export interface TestResponseSnapshot {
  question_id: number;
  selected_option: string | null;
  marked_for_review: boolean;
  visit_count: number;
  time_spent_sec: number | null;
}

export interface TestStateResponse {
  test_id: number;
  test_mode: string;
  negative_ratio: number;
  started_at: string | null;
  questions: TestQuestion[];
  responses: TestResponseSnapshot[];
  status: 'in_progress' | 'completed' | 'abandoned';
}

export interface SubmitAnswerRequest {
  question_id: number;
  selected_option?: string | null;
  marked_for_review: boolean;
  time_spent_sec: number;
}

export interface MarkForReviewRequest {
  question_id: number;
  marked: boolean;
}

export interface TopicBreakdownRow {
  topic_id: number | null;
  topic_name: string | null;
  correct: number;
  total: number;
  accuracy_pct: number;
}

export interface FinishResponse {
  test_id: number;
  correct: number;
  wrong: number;
  unanswered: number;
  score_pct: number;
  raw_marks: number;
  negative_ratio: number;
  breakdown_by_topic: TopicBreakdownRow[];
}

export interface ResultsQuestionRow {
  question_id: number;
  question_text: string | null;
  selected_option: string | null;
  correct_option: string | null;
  is_correct: boolean;
  explanation: string | null;
  time_spent_sec: number | null;
  topic_name: string | null;
}

export interface ResultsResponse extends FinishResponse {
  questions: ResultsQuestionRow[];
}

export interface TestHistoryItem {
  id: number;
  test_mode: string | null;
  status: string | null;
  total_questions: number | null;
  score: number | null;
  raw_marks: number | null;
  wrong_count: number | null;
  unanswered_count: number | null;
  negative_ratio: number | null;
  started_at: string | null;
  completed_at: string | null;
  time_taken_sec: number | null;
  computed_grade: string | null;
}
export interface TestListResponse {
  items: TestHistoryItem[];
  next_cursor: string | null;
}

// ---------- Analytics -----------------------------------------------------
// Inferred from R4 §3.9 endpoint list — backend not yet implemented, so
// treat these shapes as tentative. The UI is coded defensively (empty
// state on any missing field) so backend evolution can proceed without
// FE breakage.

export type MasteryTier = 'weak' | 'on_track' | 'untested' | 'mastered';

export interface MasteryTile {
  topic_id: number;
  name: string;
  subject: string | null;
  paper: string | null;
  weightage: number | null;
  current_score: number;
  test_count: number;
  tier: MasteryTier;
  days_since?: number | null;
  last_studied?: string | null;
}

export interface MasteryResponse {
  tiles: MasteryTile[];
  grouped_by_paper?: { I?: MasteryTile[]; II?: MasteryTile[] };
}

export interface NextTopicSuggestion {
  topic_id: number;
  name: string;
  weightage: number | null;
  next_score: number | null;
  reason: string | null;
}
export interface NextTopicsResponse {
  next_topics: NextTopicSuggestion[];
}

export interface ConsistencyResponse {
  score: number;
  active_days: number;
  activity: Array<{ date: string; has_activity: boolean }>;
}

export interface ErrorDistResponse {
  by_type: Array<{ error_type: string; count: number }>;
  trends: Array<{ date: string; error_type: string; count: number }>;
}

export interface HeatmapCell {
  attempted: number;
  correct: number;
  accuracy: number;
}
export interface HeatmapResponse {
  dim: 'difficulty' | 'recency';
  topics: Array<{
    topic_id: number;
    name: string;
    weightage: number | null;
    cells: Record<string, HeatmapCell | null>;
  }>;
}

export interface PacingResponse {
  pace_by_difficulty: Array<{ difficulty: string; avg_time: number; n: number }>;
  time_trend: Array<{
    test_id: number;
    paper: string | null;
    avg_time: number;
    score: number | null;
    date: string;
  }>;
  ma_pace: Array<number | null>;
  target_sec: number;
  slow_wrong: Array<{
    question_id: number;
    question_text: string;
    difficulty: string | null;
    time_spent_sec: number;
    topic: string | null;
  }>;
}

export interface PaperPerfResponse {
  by_paper: Array<{ paper: string; tests: number; avg_score: number }>;
}

// ---------- Errors / SRS review ------------------------------------------

export interface ErrorEntry {
  id: number;
  question_id: number;
  question_text: string | null;
  topic_id: number | null;
  topic_name: string | null;
  error_type: string | null;
  root_cause: string | null;
  explanation: string | null;
  created_at: string | null;
  resolved: boolean;
  sr_box: number | null;
  sr_due_at: string | null;
}

export interface ErrorLogResponse {
  errors: ErrorEntry[];
  next_cursor: string | null;
  sr_summary?: {
    due_today: number;
    due_tomorrow: number;
    by_box: Record<string, number>;
  };
}

export interface ReviewCard {
  error_id: number;
  question_id: number;
  question_text: string | null;
  option_a?: string | null;
  option_b?: string | null;
  option_c?: string | null;
  option_d?: string | null;
  correct_option?: string | null;
  explanation?: string | null;
  topic_name: string | null;
  sr_box: number;
  sr_due_at: string | null;
  if_ok_box: number;
  if_ok_days: number;
  if_no_box: number;
  if_no_days: number;
}

export interface ReviewQueueResponse {
  cards: ReviewCard[];
  summary: {
    due_today: number;
    due_tomorrow: number;
    by_box: Record<string, number>;
  };
}

// ---------- Bookmarks -----------------------------------------------------

export interface BookmarkEntry {
  bookmark_id: number;
  question: Question;
  note: string | null;
  created_at: string | null;
}
export interface BookmarksResponse {
  bookmarks: BookmarkEntry[];
  next_cursor: string | null;
}

// ---------- Question flag ------------------------------------------------

export type FlagCategory =
  | 'wrong_answer'
  | 'ambiguous'
  | 'typo_question'
  | 'typo_options'
  | 'explanation_missing'
  | 'duplicate'
  | 'other';

export interface FlagQuestionRequest {
  category: FlagCategory;
  note?: string;
  test_id?: number;
}

// ---------- Dashboard aggregate ------------------------------------------

/**
 * Aggregated dashboard payload — R4 §3.9 "overview" endpoint. Combines
 * consistency, next-weak-topic, and recent-test summary in one round trip.
 * Marked tentative until the Rust handler ships.
 */
export interface DashboardOverview {
  tests: { total: number; avg_score: number; total_time_sec: number };
  last_test: TestHistoryItem | null;
  consistency: {
    score: number;
    active_days: number;
    activity_28d: Array<{ date: string; has_activity: boolean }>;
  };
  sr_due_today: number;
}

// ---------- Admin --------------------------------------------------------

export interface AdminStatsResponse {
  flags_open: number;
  flags_total: number;
  questions: number;
  questions_disabled: number;
  topics: number;
  users: number;
  uploads: number;
  review_medium: number;
  review_synthetic: number;
  deficit_topics: number;
  recent_flags: Array<{
    id: number;
    question_id: number;
    category: string;
    note: string | null;
    created_at: string | null;
    question_text: string | null;
  }>;
}

export interface AdminFlag {
  id: number;
  question_id: number;
  category: string;
  note: string | null;
  status: string;
  created_at: string | null;
  question_text: string | null;
  user_id: number | null;
}

export interface DuplicatePair {
  q1: Question;
  q2: Question;
  jaccard: number;
  isize: number;
  n1: number;
  n2: number;
  suggested_keep: number;
  suggested_disable: number;
  q1_refs: number;
  q2_refs: number;
}
export interface DuplicatesResponse {
  pairs: DuplicatePair[];
  threshold: number;
  total_trigrams: number;
}

export interface AdminUser {
  id: number;
  username: string;
  email: string | null;
  role: string;
  is_active: boolean;
  created_at: string | null;
  last_login: string | null;
}

export interface AdminUpload {
  id: number;
  filename: string;
  status: string;
  topic_id: number | null;
  uploaded_at: string | null;
  extracted_count?: number;
}
