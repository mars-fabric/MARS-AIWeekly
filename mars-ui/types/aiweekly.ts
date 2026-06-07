/** Types for AI Weekly Report phase-based pipeline. */

export interface AIWeeklyStage {
    stage_number: number
    stage_name: string
    status: 'pending' | 'running' | 'completed' | 'failed'
    error?: string
    started_at?: string
    completed_at?: string
}

export interface AIWeeklyTaskState {
    task_id: string
    status: string
    progress: number
    stages: AIWeeklyStage[]
    total_cost?: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
    total_cost_usd?: number | null
}

export interface AIWeeklyCreateResponse {
    task_id: string
    work_dir: string
    stages: AIWeeklyStage[]
}

export interface AIWeeklyRefineResponse {
    refined_content: string
    message: string
    method?: 'diff' | 'fallback'
    edits_applied?: number
    edits_failed?: number
}

export interface AIWeeklyRefinementMessage {
    id: string
    role: 'user' | 'assistant'
    content: string
    timestamp: number
    original_content?: string
    method?: 'diff' | 'fallback'
    edits_applied?: number
    edits_failed?: number
}

export const AIWEEKLY_STAGE_NAMES: Record<number, string> = {
    1: 'Data Collection',
    2: 'Content Curation',
    3: 'Report Generation',
    4: 'Quality Review',
}

/** Wizard step labels shown in the stepper. */
export const AIWEEKLY_STEP_LABELS = [
    'Setup',
    'Data Collection',
    'Content Curation',
    'Report Generation',
    'Quality Review',
]

/** Map wizard step index → backend stage number (null for setup). */
export const AIWEEKLY_WIZARD_STEP_TO_STAGE: Record<number, number | null> = {
    0: null,
    1: 1,
    2: 2,
    3: 3,
    4: 4,
}

/** Shared-state keys for each stage (used in save/refine endpoints). */
export const AIWEEKLY_STAGE_SHARED_KEYS: Record<number, string> = {
    1: 'raw_collection',
    2: 'curated_items',
    3: 'draft_report',
    4: 'final_report',
}

export type AIWeeklyWizardStep = 0 | 1 | 2 | 3 | 4

/** Model option for the AI Weekly model selectors (reuses modelOptions list). */
export interface AIWeeklyModelOption {
    value: string
    label: string
}

/** Available models for AI Weekly stages. */
export const AIWEEKLY_AVAILABLE_MODELS: AIWeeklyModelOption[] = [
    { value: 'gpt-5.1-2025-11-13', label: 'GPT-5.1 (Azure)' },
    { value: 'gpt-4o', label: 'GPT-4o (Azure)' },
    { value: 'bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0', label: 'Claude Haiku 4.5 (Bedrock)' },
    { value: 'bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0', label: 'Claude Sonnet 4.5 (Bedrock)' },
    { value: 'bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0', label: 'Claude Sonnet 4 (Bedrock)' },
    { value: 'bedrock/anthropic.claude-sonnet-4-6', label: 'Claude Sonnet 4.6 (Bedrock)' },
    { value: 'bedrock/amazon.nova-lite-v1:0', label: 'Amazon Nova Lite (Bedrock)' },
    { value: 'bedrock/amazon.nova-pro-v1:0', label: 'Amazon Nova Pro (Bedrock)' },
    { value: 'bedrock/us.meta.llama4-scout-17b-instruct-v1:0', label: 'Llama 4 Scout 17B (Bedrock)' },
    { value: 'bedrock/us.meta.llama3-3-70b-instruct-v1:0', label: 'Llama 3.3 70B (Bedrock)' },
    { value: 'bedrock/mistral.mistral-large-2402-v1:0', label: 'Mistral Large (Bedrock)' },
]

/** Config overrides for AI Weekly LLM stages (Stages 2-4). */
export interface AIWeeklyStageConfig {
    /** Primary generation model (Stages 2-4) */
    model?: string
    /** Review pass model (defaults to primary model) */
    review_model?: string
    /** Specialist/fact-check model (defaults to primary model) */
    specialist_model?: string
    /** LLM temperature (0-1) */
    temperature?: number
    /** Number of review passes */
    n_reviews?: number
}
