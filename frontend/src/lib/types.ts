// Типы ответов API (см. Swagger: /api/docs)

export type Role = 'candidate' | 'employer'
export type GradeId = 'intern' | 'junior' | 'middle' | 'senior' | 'lead'

export interface Me {
  id: string
  email: string
  role: Role | null
  display_name: string | null
  consents: Record<string, boolean>
  has_profile: boolean
  has_company: boolean
  onboarding_step: 'choose_role' | 'survey' | 'test' | 'company' | 'done'
}

export interface AuthConfig {
  mode: 'keycloak' | 'dev'
  keycloak_url: string
  realm: string
  client_id: string
  consent_version: string
  consent_texts: Record<string, string>
}

export interface Catalog {
  grades: { id: GradeId; name: string; title: string; experience: string; order: number }[]
  specializations: { id: string; name: string; title: string; description: string; blueprint: Record<string, number>; stack_languages: string[] }[]
  assessment_skills: { id: string; title: string; anchor?: boolean; families: number }[]
  industries: { id: string; title: string }[]
  work_formats: { id: string; title: string }[]
  search_statuses: { id: string; title: string; visible: boolean }[]
  decline_reasons: { id: string; title: string }[]
  fsp: {
    levels: { id: string; title: string; weight: number }[]
    results: { id: string; title: string; weight: number }[]
    disciplines: { id: string; title: string }[]
  }
  technologies: { name: string; assess: string[]; specializations: Record<string, number> }[]
  bank: { families: number; by_skill: Record<string, number> }
}

export interface SkillScore {
  status: 'confirmed' | 'uncertain' | 'weak' | 'no_data'
  theta?: number | null
  se?: number | null
  n: number
  title: string
}

export interface FspAchievement {
  id?: string
  title: string
  discipline: string
  level: string
  result: string
  place?: number | null
  date: string
  role?: string | null
  team?: string | null
}

export interface Job {
  title: string
  start?: string | null
  end?: string | null
  description?: string | null
}

export interface Profile {
  user_id: string
  full_name: string | null
  contact_email: string | null
  phone: string | null
  telegram: string | null
  github: string | null
  city: string | null
  headline: string | null
  about: string | null
  experience_years: number | null
  soft_skills: string[]
  experience: Job[]
  education: string | null
  survey_completed_at: string | null
  industries: string[]
  specialization: string | null
  stack: string[]
  work_formats: string[]
  salary_from: number | null
  salary_to: number | null
  search_status: string
  claimed_grade: GradeId | null
  confirmed_grade: GradeId | null
  confirmed_at: string | null
  category: string | null
  theta: number | null
  skill_scores: Record<string, SkillScore>
  tasks_score: number
  fsp_id: string | null
  fsp_linked_at: string | null
  fsp_synced_at: string | null
  fsp_profile: { full_name?: string; region?: string; sport_rank?: string } | null
  fsp_achievements: FspAchievement[]
  show_fsp: boolean
  excluded_industries: string[]
  excluded_companies: string[]
  hidden: boolean
  resume_parsed: Record<string, unknown> | null
}

export interface Dashboard {
  category: string | null
  onboarding_step: string
  invitations_new: number
  invitations_total: number
  applications_total: number
  tasks_open: number
  fsp_linked: boolean
  profile_completeness: number
  next_actions: string[]
}

export interface Item {
  position: number
  kind: 'single' | 'multi' | 'number' | 'text' | 'order' | 'scenario' | 'probe'
  stage: 'knowledge' | 'scenario' | 'probe'
  task: string | null
  prompt: string
  code: string | null
  code_lang: string | null
  options: string[] | null
  skill: string
  skill_title: string
  time_limit: number
  issued_at: string
}

export interface AttemptResult {
  theta: number
  se: number
  n_items: number
  claimed_grade: GradeId
  p_claimed: number
  p_next: number | null
  decision: 'confirmed' | 'not_confirmed'
  suggestion: 'upgrade' | 'downgrade' | null
  estimated_grade: GradeId
  skills: Record<string, { status: SkillScore['status']; theta: number | null; se: number | null; n: number; n_correct: number }>
  explanation: string[]
  tab_switches: number
  knowledge_p_claimed?: number
  scenario?: ScenarioOutcome | null
  integrity?: IntegrityReport | null
}

export interface IntegrityReport {
  level: 'clean' | 'review' | 'void'
  items_left: number
  away_ms: number
  paste_attempts: number
  copy_attempts: number
  lz: number | null
  reasons: string[]
  leaves_left: number
}

export interface ScenarioOutcome {
  scenario_id: string
  title: string
  grade: GradeId
  category: number
  category_title: string
  total: number
  method: 'llm' | 'keywords'
  comment: string | null
  criteria: { id: string; title: string; score: number; evidence: string }[]
  probe: { question: string; score: number | null; evidence: string } | null
}

export interface Attempt {
  id: string
  specialization: string
  grade: GradeId
  kind: string
  status: 'in_progress' | 'passed' | 'failed' | 'abandoned' | 'voided'
  started_at: string
  finished_at: string | null
  answered: number
  max_items: number
  min_items: number
  blueprint: Record<string, number>
  item: Item | null
  result: AttemptResult | null
  has_scenario: boolean
  integrity: { items_left: number; leaves_left: number; level: string } | null
}

export interface Eligibility {
  specialization: string | null
  claimed_grade: GradeId | null
  confirmed_grade: GradeId | null
  confirmed_at: string | null
  last_change_at: string | null
  in_progress: string | null
  options: { grade: GradeId; allowed: boolean; kind: string; reason: string | null; available_at: string | null }[]
  rules: string[]
}

export interface Reason {
  kind: 'positive' | 'neutral' | 'negative'
  text: string
}

export interface CandidateCard {
  id: string
  alias: string
  revealed: boolean
  full_name: string | null
  contacts: Record<string, string> | null
  category: string | null
  specialization: string | null
  grade: GradeId | null
  confirmed_at: string | null
  city: string | null
  headline: string | null
  about: string | null
  experience_years: number | null
  stack: string[]
  confirmed_skills: string[]
  skill_scores: Record<string, string>
  test_percentile: number | null
  work_formats: string[]
  search_status: string
  last_active_days: number | null
  fsp_linked: boolean
  fsp_visible: boolean
  fsp_strength: number
  fsp: FspAchievement[]
  profile_strength: number
  salary_fit: string | null
  assessment: {
    integrity: { level: 'clean' | 'review' | 'void'; reasons: string[] }
    scenario: { title: string; category: number; category_title: string; method: string } | null
  } | null
}

export interface Ranked {
  card: CandidateCard
  score: number
  components: Record<string, number>
  reasons: Reason[]
  missing: string[]
  adjacent: boolean
  salary_fit: string
  shortlisted: boolean
}

export interface SearchSummary {
  id: string
  title: string
  specialization: string
  grade: GradeId
  category: string
  version: number
  created_at: string
  updated_at: string
  shortlist: number
  filters: Filters
}

export interface Filters {
  grades?: GradeId[]
  skills?: string[]
  confirmed_skills?: string[]
  has_fsp?: boolean | null
  formats?: string[]
  salary_fit_only?: boolean
  only_active?: boolean
  exclude_adjacent?: boolean
  min_score?: number | null
  cities?: string[]
}

export interface CategorySummary {
  specialization: string
  grade: GradeId
  label: string
  total: number
  with_fsp: number
  salary_median: number | null
  in_budget_share: number | null
  relation: 'target' | 'adjacent' | 'alternative'
}

export interface SearchOut {
  search: SearchSummary
  need: {
    text: string
    team_description: string | null
    skills: Record<string, number>
    salary_from: number | null
    salary_to: number | null
    work_format: string | null
    industry: string | null
    include_adjacent: boolean
    explanation: string[]
  }
  base_total: number
  filtered_total: number
  results: Ranked[]
  categories: CategorySummary[]
  versions: { version: number; filters: Filters; note: string | null; created_at: string }[]
}

export interface NeedParse {
  specialization: string | null
  spec_scores: Record<string, number>
  grade: GradeId | null
  grade_reason: string | null
  skills: Record<string, number>
  must: string[]
  plus: string[]
  salary_from: number | null
  salary_to: number | null
  work_format: string | null
  blueprint: Record<string, number>
  explanation: string[]
}

export interface Company {
  id: string
  name: string
  description: string | null
  industry: string | null
  website: string | null
  city: string | null
  contact_email: string | null
  contact_phone: string | null
  contact_telegram: string | null
  inn: string | null
  webhook_url: string | null
  created_at: string
}

export interface Invitation {
  id: string
  status: 'sent' | 'viewed' | 'accepted' | 'declined' | 'withdrawn'
  title: string
  description: string
  salary_from: number
  salary_to: number
  contact_method: string
  contact_value: string
  company_id: string
  company_name: string
  company_industry: string | null
  company_description: string | null
  company_stats: { invitations_90d: number; acceptance_rate: number | null; application_response_rate: number | null } | null
  candidate_id: string
  candidate_alias: string
  candidate_category: string | null
  candidate_name: string | null
  candidate_contacts: Record<string, string> | null
  vacancy_id: string | null
  search_id: string | null
  salary_fit: string | null
  decline_reason: string | null
  decline_comment: string | null
  created_at: string
  viewed_at: string | null
  responded_at: string | null
}

export interface Vacancy {
  id: string
  company_id: string
  company_name: string
  company_industry: string | null
  company_stats: Invitation['company_stats']
  title: string
  text: string
  specialization: string
  grade: GradeId
  category: string
  skills: Record<string, number>
  salary_from: number
  salary_to: number
  work_format: string | null
  city: string | null
  status: string
  blueprint: Record<string, number>
  created_at: string
  updated_at: string
  applications: number | null
  match: { score: number; reasons: Reason[]; missing: string[] } | null
  applied: boolean | null
}

export interface Application {
  id: string
  vacancy_id: string
  vacancy_title: string
  company_name: string
  status: string
  cover_letter: string | null
  employer_comment: string | null
  created_at: string
  updated_at: string
  candidate: CandidateCard | null
  match: { score: number; reasons: Reason[]; missing: string[] } | null
}

export interface TaskOut {
  id: string
  title: string
  kind: 'auto' | 'open'
  specialization: string
  skill: string | null
  prompt: string | null
  rubric: string | null
  active: boolean
  created_at: string
  assigned: number
  submitted: number
}

export interface Assignment {
  id: string
  task_id: string
  title: string
  company_name: string
  kind: 'auto' | 'open'
  status: 'assigned' | 'submitted' | 'reviewed' | 'expired'
  prompt: string
  code: string | null
  code_lang: string | null
  options: string[] | null
  answer_kind: string
  assigned_at: string
  due_at: string | null
  submitted_at: string | null
  correct: boolean | null
  score: number | null
  feedback: string | null
  candidate_alias: string | null
  answer: Record<string, unknown> | null
}

export interface PreviewOut {
  specialization: string | null
  grade: GradeId
  blueprint: Record<string, number>
  parsed_skills: Record<string, number>
  explanation: string[]
  tests: {
    label: string
    items: {
      family_id: string
      family_title: string
      skill: string
      skill_title: string
      level: number
      difficulty_b: number
      info_at_cut: number
      kind: string
      prompt: string
      code: string | null
      code_lang: string | null
      options: string[] | null
    }[]
    mean_b: number
    total_information: number
    skill_mix: Record<string, number>
  }[]
  shared_families: number
  shared_instances: number
}

export interface CategoryCell {
  specialization: string
  grade: GradeId
  label: string
  total: number
  with_fsp: number
  active: number
}

export interface Insights {
  invitations: Record<string, number>
  decline_reasons: { reason: string; title: string; count: number; share: number }[]
  acceptance_rate: number | null
  median_response_hours: number | null
  market: {
    category: string
    candidates: number
    salary_p25: number | null
    salary_median: number | null
    salary_p75: number | null
    declines_total: number
    declines_salary_share: number | null
  }[]
}
