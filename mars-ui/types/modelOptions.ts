/** Available model options for stage configuration */
export interface ModelOption {
          value: string
          label: string
}

// Confirmed active Azure OpenAI deployments on azureft.openai.azure.com
export const AVAILABLE_MODELS: ModelOption[] = [
          { value: 'gpt-4o', label: 'GPT-4o 2024-11-20 (Azure) — best quality' },
          { value: 'gpt-4o-mini', label: 'GPT-4o Mini (Azure) — fast' },
]

export interface RefinementMessage {
          id: string
          role: 'user' | 'assistant'
          content: string
          timestamp: number
}
