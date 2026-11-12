export type AgentEventType =
  | 'open'
  | 'phase'
  | 'draft'
  | 'text'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'approval_required'
  | 'done'
  | 'error';

export interface AgentEvent {
  type: AgentEventType;
  data: Record<string, unknown>;
}

export interface ProviderInfo {
  readonly provider: string;
  readonly known: boolean;
  readonly models: readonly {
    readonly id: string;
    readonly label?: string;
    readonly reasoning_efforts?: readonly string[];
    readonly default_effort?: string;
  }[];
  readonly has_catalog: boolean;
  readonly connected?: boolean;
  readonly login?: 'xai_device' | 'apikey' | 'external';
}

export interface Capability {
  enabled: boolean;
  reason: string;
}

export interface Health {
  app: string;
  version: string;
  frontend_port: number;
  sidecar_port: number;
  capabilities: Record<string, Capability | boolean> & { native_tab?: boolean };
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
}

export interface ToolActivity {
  kind: 'tool_call' | 'tool_result';
  name: string;
  result?: Record<string, unknown>;
}

export interface ApprovalRequest {
  name: string;
  call_id: string;
  pending_id: string;
  args: Record<string, unknown>;
  display?: Record<string, unknown>;
  expires_at?: number;
}
