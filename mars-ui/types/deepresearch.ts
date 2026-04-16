/** Available model options for stage configuration */
export interface ModelOption {
          value: string
          label: string
}

export const AVAILABLE_MODELS: ModelOption[] = [
          { value: 'gpt-4.1-2025-04-14', label: 'GPT-4.1' },
          { value: 'gpt-4.1-mini', label: 'GPT-4.1 Mini' },
          { value: 'gpt-4o', label: 'GPT-4o' },
          { value: 'gpt-4o-mini-2024-07-18', label: 'GPT-4o Mini' },
          { value: 'gpt-4.5-preview-2025-02-27', label: 'GPT-4.5 Preview' },
          { value: 'gpt-5-2025-08-07', label: 'GPT-5' },
          { value: 'o3-mini-2025-01-31', label: 'o3-mini' },
          { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
          { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
          { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
          { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
          { value: 'claude-3.5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
]

export interface RefinementMessage {
          id: string
          role: 'user' | 'assistant'
          content: string
          timestamp: number
}
