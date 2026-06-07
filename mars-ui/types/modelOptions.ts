/** Available model options for stage configuration */
export interface ModelOption {
          value: string
          label: string
}

export const AVAILABLE_MODELS: ModelOption[] = [
          { value: 'gpt-5.1-2025-11-13', label: 'GPT-5.1 (Azure)' },
          { value: 'gpt-4o', label: 'GPT-4o (Azure)' },
          { value: 'bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0', label: 'Claude Haiku 4.5 (Bedrock)' },
          { value: 'bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0', label: 'Claude Sonnet 4.5 (Bedrock)' },
          { value: 'bedrock/anthropic.claude-sonnet-4-6', label: 'Claude Sonnet 4.6 (Bedrock)' },
          { value: 'bedrock/amazon.nova-lite-v1:0', label: 'Amazon Nova Lite (Bedrock)' },
          { value: 'bedrock/amazon.nova-pro-v1:0', label: 'Amazon Nova Pro (Bedrock)' },
          { value: 'bedrock/us.meta.llama4-scout-17b-instruct-v1:0', label: 'Llama 4 Scout 17B (Bedrock)' },
          { value: 'bedrock/us.meta.llama3-3-70b-instruct-v1:0', label: 'Llama 3.3 70B (Bedrock)' },
          { value: 'bedrock/mistral.mistral-large-2402-v1:0', label: 'Mistral Large (Bedrock)' },
]

export interface RefinementMessage {
          id: string
          role: 'user' | 'assistant'
          content: string
          timestamp: number
}
