/**
 * LLM Client - Azure OpenAI / Anthropic integration
 */

import type {SessionMessage} from '../utils/sessionManager.js';
import type {LLMMessage} from './types.js';

export interface LLMConfig {
  provider: 'azure' | 'anthropic';
  apiKey: string;
  endpoint?: string;
  model?: string;
}

export interface LLMResponse {
  content: string;
  model: string;
  tokensUsed?: number;
}

export class LLMClient {
  private config: LLMConfig | null = null;
  private available = false;

  constructor() {
    this.loadConfig();
  }

  /**
   * Load LLM configuration from .warden/config.yaml or environment
   */
  private loadConfig(): void {
    // Try to load from .warden/config.yaml first
    try {
      const {configLoader} = require('../utils/configLoader.js');
      const wardenConfig = configLoader.getLLMConfig();

      if (wardenConfig) {
        // Use config from .warden/config.yaml
        if (wardenConfig.provider === 'azure_openai' && wardenConfig.azure) {
          this.config = {
            provider: 'azure',
            apiKey: wardenConfig.azure.api_key,
            endpoint: wardenConfig.azure.endpoint,
            model: wardenConfig.model || 'gpt-4',
          };
          this.available = true;
          return;
        }
      }
    } catch {
      // Config not available, try environment
    }

    // Fallback to environment variables
    const azureKey = process.env.AZURE_OPENAI_API_KEY;
    const azureEndpoint = process.env.AZURE_OPENAI_ENDPOINT;
    const anthropicKey = process.env.ANTHROPIC_API_KEY;

    if (azureKey && azureEndpoint) {
      this.config = {
        provider: 'azure',
        apiKey: azureKey,
        endpoint: azureEndpoint,
        model: process.env.AZURE_OPENAI_MODEL || 'gpt-4',
      };
      this.available = true;
    } else if (anthropicKey) {
      this.config = {
        provider: 'anthropic',
        apiKey: anthropicKey,
        model: process.env.ANTHROPIC_MODEL || 'claude-3-5-sonnet-20241022',
      };
      this.available = true;
    }
  }

  /**
   * Check if LLM is available
   */
  isAvailable(): boolean {
    return this.available;
  }

  /**
   * Get LLM provider name
   */
  getProvider(): string | null {
    return this.config?.provider || null;
  }

  /**
   * Get LLM model name
   */
  getModel(): string | null {
    return this.config?.model || null;
  }

  /**
   * Chat with LLM
   */
  async chat(
    message: string,
    history: SessionMessage[] = [],
    systemPrompt?: string
  ): Promise<LLMResponse> {
    if (!this.available || !this.config) {
      throw new Error('LLM not available. Set AZURE_OPENAI_API_KEY or ANTHROPIC_API_KEY');
    }

    if (this.config.provider === 'azure') {
      return this.chatAzure(message, history, systemPrompt);
    } else {
      return this.chatAnthropic(message, history, systemPrompt);
    }
  }

  /**
   * Chat with Azure OpenAI
   */
  private async chatAzure(
    message: string,
    history: SessionMessage[],
    systemPrompt?: string
  ): Promise<LLMResponse> {
    if (!this.config) throw new Error('LLM not configured');

    // Build messages array
    const messages: LLMMessage[] = [];

    // Add system prompt
    if (systemPrompt) {
      messages.push({role: 'system', content: systemPrompt});
    } else {
      messages.push({
        role: 'system',
        content: 'You are Warden, an AI code analysis assistant. Help users analyze, fix, and improve their code.',
      });
    }

    // Add history (last 10 messages for context)
    const recentHistory = history.slice(-10);
    for (const msg of recentHistory) {
      messages.push({
        role: msg.type === 'user' ? 'user' : 'assistant',
        content: msg.content,
      });
    }

    // Add current message
    messages.push({role: 'user', content: message});

    // Call Azure OpenAI
    const response = await fetch(
      `${this.config.endpoint}/openai/deployments/${this.config.model}/chat/completions?api-version=2024-02-15-preview`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'api-key': this.config.apiKey,
        },
        body: JSON.stringify({
          messages,
          temperature: 0.7,
          max_tokens: 2000,
        }),
      }
    );

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Azure OpenAI error: ${error}`);
    }

    const data = await response.json();

    return {
      content: data.choices[0].message.content,
      model: this.config.model!,
      tokensUsed: data.usage?.total_tokens,
    };
  }

  /**
   * Chat with Anthropic Claude
   */
  private async chatAnthropic(
    message: string,
    history: SessionMessage[],
    systemPrompt?: string
  ): Promise<LLMResponse> {
    if (!this.config) throw new Error('LLM not configured');

    // Build messages array
    const messages: LLMMessage[] = [];

    // Add history (last 10 messages for context)
    const recentHistory = history.slice(-10);
    for (const msg of recentHistory) {
      messages.push({
        role: msg.type === 'user' ? 'user' : 'assistant',
        content: msg.content,
      });
    }

    // Add current message
    messages.push({role: 'user', content: message});

    // Call Anthropic
    const response = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': this.config.apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify({
        model: this.config.model,
        max_tokens: 2000,
        system:
          systemPrompt ||
          'You are Warden, an AI code analysis assistant. Help users analyze, fix, and improve their code.',
        messages,
      }),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Anthropic error: ${error}`);
    }

    const data = await response.json();

    return {
      content: data.content[0].text,
      model: this.config.model!,
      tokensUsed: data.usage?.input_tokens + data.usage?.output_tokens,
    };
  }

  /**
   * Stream chat (for future implementation)
   */
  async *stream(message: string, history: SessionMessage[] = []): AsyncIterator<string> {
    // TODO: Implement streaming
    const response = await this.chat(message, history);
    yield response.content;
  }
}

// Singleton instance
export const llmClient = new LLMClient();
