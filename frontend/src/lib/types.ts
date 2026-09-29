export type Stage =
  | "applied" | "screening" | "screened" | "assessment" | "interview" | "evaluation" | "selection"
  | "verification" | "offer" | "hired" | "rejected" | "withdrawn";

export const STAGES: Stage[] = [
  "applied", "screening", "screened", "assessment", "interview", "evaluation", "selection", "verification", "offer",
  "hired",
];

export interface Me {
  id: string;
  email: string;
  full_name: string;
  organization_id: string | null;
  organization_name: string | null;
  roles: string[];
  permissions: string[];
}

export interface ApprovalStep {
  id: string;
  step_order: number;
  approver_role: string;
  status: string;
  decided_at: string | null;
  comment: string | null;
}

export interface Requisition {
  id: string;
  reference: string;
  title: string;
  status: string;
  headcount: number;
  employment_type: string;
  location: string | null;
  remote_policy: string;
  job_level: string | null;
  justification: string;
  responsibilities: string[];
  required_skills: string[];
  preferred_skills: string[];
  min_years_experience: number | null;
  budget_min: string | null;
  budget_max: string | null;
  currency: string;
  target_start_date: string | null;
  created_at: string;
  ai_validation: {
    valid: boolean;
    completeness: number;
    issues: { severity: string; field: string; message: string }[];
    suggestions: string[];
    approval_route: string[];
  } | null;
  approval?: { status: string; current_step: number; steps: ApprovalStep[] } | null;
  job_ids?: string[];
}

export interface Requirement {
  id?: string;
  kind: string;
  name: string;
  min_years: number | null;
  is_mandatory: boolean;
  weight: number;
}

export interface Job {
  id: string;
  title: string;
  slug: string;
  status: string;
  description: string;
  advertisement: string | null;
  location: string | null;
  remote_policy: string;
  employment_type: string;
  job_level: string | null;
  salary_min: string | null;
  salary_max: string | null;
  currency: string;
  published_at: string | null;
  requisition_id: string | null;
  requirements: Requirement[];
  screening_config: { knockout_questions?: { id: string; question: string; expected: boolean | string }[] };
  created_at: string;
}

export interface Candidate {
  id: string;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string;
  phone?: string | null;
  location: string | null;
  headline: string | null;
  current_title: string | null;
  current_company: string | null;
  years_experience: number | null;
  source: string;
  tags: string[];
  anonymized_at: string | null;
  created_at: string;
  summary?: string | null;
  skills?: { name: string; category: string | null; source: string; evidence: string | null }[];
  experience?: { title: string | null; company: string | null; start: string | null; end: string | null; months: number }[];
  education?: { degree: string; field: string | null; institution: string | null }[];
  languages?: string[];
  application_ids?: string[];
  consent_given_at?: string | null;
  retention_until?: string | null;
}

export interface Application {
  id: string;
  job_id: string;
  candidate_id: string;
  stage: Stage;
  status: string;
  source: string;
  applied_at: string;
  stage_changed_at: string;
  match_score: number | null;
  candidate_name: string | null;
  job_title: string | null;
  rejection_reason: string | null;
  history?: { id: string; from_stage: Stage | null; to_stage: Stage; actor_type: string; reason: string | null;
    changed_at: string }[];
  workflow?: { current_node: string; status: string; waiting_on: string | null;
    history: { from: string; to: string; event: string; at: string; note: string | null }[] } | null;
}

export interface Screening {
  id: string;
  eligible: boolean;
  score: number;
  recommendation: string;
  review_status: string;
  summary: string;
  rule_results: { rule: string; passed: boolean; mandatory: boolean; detail: string; evidence: string | null }[];
  facts: { statement: string; evidence: string | null; source: string }[];
  interpretations: { kind: string; text: string; ai_generated: boolean }[];
  reviewer_decision: string | null;
  override_reason: string | null;
  created_at: string;
}

export interface Interview {
  id: string;
  application_id: string;
  kind: string;
  round: number;
  status: string;
  scheduled_start: string;
  scheduled_end: string;
  timezone: string;
  location: string | null;
  meeting_url: string | null;
  interviewers: { user_id: string; role: string }[];
  candidate_name: string | null;
  job_title: string | null;
  template_id: string | null;
  ai_summary: {
    summary: string;
    competency_evidence: { competency: string; quotes: string[]; evidence_strength: string; ai_generated: boolean }[];
    follow_up_questions: string[];
    ai_generated: boolean;
  } | null;
}

export interface Evaluation {
  id: string;
  overall_score: number | null;
  ai_recommendation: string | null;
  ai_rationale: string | null;
  risks: string[];
  competency_matrix: Record<string, { mean: number; n: number; spread: number }>;
  decision: string | null;
  decision_rationale: string | null;
  created_at: string;
}

export interface Offer {
  id: string;
  application_id: string;
  version: number;
  status: string;
  job_title: string;
  base_salary: string;
  currency: string;
  bonus_pct: number | null;
  benefits: string[];
  start_date: string | null;
  expires_at: string | null;
  within_band: boolean | null;
  letter_body: string | null;
  sent_at: string | null;
  approvals: ApprovalStep[];
  created_at: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  title: string | null;
  is_active: boolean;
  role_keys: string[];
  last_login_at: string | null;
}
