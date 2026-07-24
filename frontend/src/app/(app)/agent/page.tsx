"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Bot,
  Check,
  CheckCircle2,
  Database,
  FileImage,
  Paperclip,
  Plus,
  Send,
  Settings2,
  ShieldCheck,
  Trash2,
  User,
  X,
  XCircle,
} from "lucide-react";
import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";

import {
  InlineLoading,
  ListSkeleton,
  LoadingSpinner,
} from "@/components/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  AgentSession,
  AgentSessionDetail,
  AgentPendingAction,
  AgentPendingToolCall,
  AgentToolTrace,
  AgentTurnResult,
  LLMProvider,
} from "@/lib/types";

interface LocalMessage {
  role: "user" | "assistant";
  content: string;
  trace?: AgentToolTrace[];
  files?: string[];
  pendingAction?: AgentPendingAction | null;
}

const PROVIDER_PRESETS = {
  openai: {
    label: "OpenAI",
    baseUrl: "https://api.openai.com/v1",
    chatModels: ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"],
    visionModels: ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"],
  },
  deepseek: {
    label: "DeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    chatModels: ["deepseek-v4-flash", "deepseek-v4-pro"],
    visionModels: [],
  },
  minimax: {
    label: "MiniMax",
    baseUrl: "https://api.minimax.chat/v1",
    chatModels: ["MiniMax-Text-01"],
    visionModels: ["MiniMax-VL-01"],
  },
  seed: {
    label: "Seed / Doubao",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    chatModels: ["doubao-seed-1-6-250615", "doubao-1-5-pro-32k-250115"],
    visionModels: ["doubao-seed-1-6-250615", "doubao-1-5-vision-pro-250328"],
  },
};

type ProviderKey = keyof typeof PROVIDER_PRESETS;

interface ProviderSetupForm {
  providerKey: ProviderKey;
  apiKey: string;
  chatModel: string;
  visionModel: string;
}

function createProviderSetup(providerKey: ProviderKey = "openai"): ProviderSetupForm {
  const preset = PROVIDER_PRESETS[providerKey];
  return {
    providerKey,
    apiKey: "",
    chatModel: preset.chatModels[0],
    visionModel: preset.visionModels[0] ?? "",
  };
}

export default function AgentPage() {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [input, setInput] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [openingSessionId, setOpeningSessionId] = useState<string | null>(null);

  const sessionsQuery = useQuery({
    queryKey: ["agent", "sessions"],
    queryFn: () => api.get<AgentSession[]>("/api/agent/sessions"),
  });
  const providersQuery = useQuery({
    queryKey: ["llm-providers"],
    queryFn: () => api.get<LLMProvider[]>("/api/settings/llm-providers"),
  });
  const chatProviders = (providersQuery.data ?? []).filter((provider) => provider.role === "chat");
  const activeChatProvider = chatProviders.find((provider) => provider.is_active);
  const activateModelMutation = useMutation({
    mutationFn: (id: string) => api.patch<LLMProvider>(`/api/settings/llm-providers/${id}`, { is_active: true }),
    onSuccess: (provider) => {
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
      toast.success(zh ? `已切换到 ${provider.model_name}` : `Switched to ${provider.model_name}`);
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : (zh ? "模型切换失败" : "Failed to switch model")),
  });
  const openSession = async (nextSessionId: string) => {
    setOpeningSessionId(nextSessionId);
    try {
      const detail = await queryClient.fetchQuery({
        queryKey: ["agent", "session", nextSessionId],
        queryFn: () =>
          api.get<AgentSessionDetail>(
            `/api/agent/sessions/${nextSessionId}`,
          ),
      });
      setSessionId(nextSessionId);
      setMessages(
        detail.messages.map((message) => ({
          role: message.role,
          content: message.content,
          trace: message.tool_trace,
          files: message.attachments.map((attachment) =>
            String(attachment.filename ?? "file"),
          ),
          pendingAction: message.pending_action,
        })),
      );
    } catch (error) {
      const detail = error instanceof ApiError ? error.message : "";
      toast.error(
        detail || (zh ? "加载历史对话失败" : "Failed to load conversation"),
      );
    } finally {
      setOpeningSessionId(null);
    }
  };

  const sendMutation = useMutation({
    mutationFn: async ({ text, attached }: { text: string; attached: File[] }) => {
      const payloadMessages = [...messages, { role: "user" as const, content: text }].map(({ role, content }) => ({ role, content }));
      if (attached.length === 0) {
        return api.post<AgentTurnResult>("/api/agent/chat", { messages: payloadMessages, session_id: sessionId });
      }
      const formData = new FormData();
      formData.append("messages", JSON.stringify(payloadMessages));
      if (sessionId) formData.append("session_id", sessionId);
      attached.forEach((file) => formData.append("files", file));
      return api.post<AgentTurnResult>("/api/agent/chat-with-files", formData);
    },
    onSuccess: (result) => {
      setMessages((old) => [...old, {
        role: "assistant",
        content: result.assistant_message,
        trace: result.tool_call_trace,
        pendingAction: result.pending_action,
      }]);
      setSessionId(result.session_id);
      setFiles([]);
      queryClient.invalidateQueries({ queryKey: ["agent", "sessions"] });
    },
    onError: (error) => {
      const detail = error instanceof ApiError ? error.message : "";
      toast.error(detail || (zh ? "Agent 请求失败" : "Agent request failed"));
    },
  });

  const resolvePendingMutation = useMutation({
    mutationFn: ({ actionId, decision }: { actionId: string; decision: "confirm" | "cancel" }) =>
      api.post<AgentTurnResult>(`/api/agent/pending-actions/${actionId}/${decision}`),
    onSuccess: (result, variables) => {
      setMessages((old) => [
        ...old.map((message) =>
          message.pendingAction?.id === variables.actionId
            ? { ...message, pendingAction: result.pending_action }
            : message,
        ),
        {
          role: "assistant",
          content: result.assistant_message,
          trace: result.tool_call_trace,
        },
      ]);
      queryClient.invalidateQueries({ queryKey: ["agent", "sessions"] });
      if (variables.decision === "confirm" && result.pending_action?.status === "confirmed") {
        ["portfolio", "transactions", "accounts", "instruments", "owners", "institutions"].forEach((key) =>
          queryClient.invalidateQueries({ queryKey: [key] }),
        );
      }
    },
    onError: (error) => {
      const detail = error instanceof ApiError ? error.message : "";
      toast.error(detail || (zh ? "确认操作失败" : "Failed to resolve the pending action"));
    },
  });

  const send = () => {
    const text = input.trim();
    if (!text || sendMutation.isPending) return;
    const attached = [...files];
    setMessages((old) => [
      ...old.map((message) =>
        message.pendingAction?.status === "pending"
          ? { ...message, pendingAction: { ...message.pendingAction, status: "cancelled" as const } }
          : message,
      ),
      { role: "user", content: text, files: attached.map((file) => file.name) },
    ]);
    setInput("");
    sendMutation.mutate({ text, attached });
  };

  const newConversation = () => {
    setOpeningSessionId(null);
    setSessionId(null);
    setMessages([]);
    setFiles([]);
    setInput("");
  };

  const historyLoadingLabel = zh
    ? "正在加载历史对话"
    : "Loading conversations";
  const conversationLoadingLabel = zh
    ? "正在加载对话内容…"
    : "Loading conversation…";

  return (
    <div
      className="space-y-4"
      aria-busy={sendMutation.isPending || openingSessionId !== null}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">AI Agent</h1>
          <p className="text-sm text-muted-foreground">
            {zh
              ? "用中文、截图或 PDF 管理资产和交易"
              : "Manage assets and transactions with chat, images, or PDFs"}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {providersQuery.isLoading ? (
            <Skeleton
              className="h-9 w-52 rounded-lg"
              aria-label={zh ? "正在加载模型" : "Loading models"}
            />
          ) : chatProviders.length > 0 ? (
            <div className="flex items-center gap-2">
              <select
                value={activeChatProvider?.id ?? ""}
                onChange={(event) => {
                  if (event.target.value) {
                    activateModelMutation.mutate(event.target.value);
                  }
                }}
                disabled={activateModelMutation.isPending}
                aria-label={zh ? "选择聊天模型" : "Choose chat model"}
                aria-busy={activateModelMutation.isPending}
                className="h-9 max-w-56 rounded-lg border bg-background px-3 text-sm font-medium"
              >
                {!activeChatProvider && (
                  <option value="" disabled>
                    {zh ? "选择聊天模型" : "Choose chat model"}
                  </option>
                )}
                {chatProviders.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.model_name} ·{" "}
                    {PROVIDER_PRESETS[
                      provider.provider_key as ProviderKey
                    ]?.label ?? provider.provider_key}
                  </option>
                ))}
              </select>
              {activateModelMutation.isPending && (
                <LoadingSpinner
                  label={zh ? "正在切换模型" : "Switching model"}
                />
              )}
            </div>
          ) : (
            <Button variant="outline" onClick={() => setSettingsOpen(true)}>
              <Bot className="h-4 w-4" />
              {zh ? "选择模型" : "Choose model"}
            </Button>
          )}
          <Button variant="outline" onClick={newConversation}>
            <Plus className="h-4 w-4" />
            {zh ? "新对话" : "New chat"}
          </Button>
          <Button variant="outline" onClick={() => setSettingsOpen(true)}>
            <Settings2 className="h-4 w-4" />
            {zh ? "LLM 设置" : "LLM settings"}
          </Button>
        </div>
      </div>

      <div className="grid min-h-[680px] gap-4 lg:grid-cols-[240px_1fr]">
        <Card className="hidden lg:block" aria-busy={sessionsQuery.isLoading}>
          <CardHeader>
            <CardTitle className="text-base">
              {zh ? "历史对话" : "Conversations"}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {sessionsQuery.isLoading ? (
              <ListSkeleton
                compact
                rows={6}
                label={historyLoadingLabel}
                className="border-0"
              />
            ) : (
              (sessionsQuery.data ?? []).map((session) => {
                const isOpening = openingSessionId === session.id;
                const isActive = sessionId === session.id;
                return (
                  <button
                    key={session.id}
                    type="button"
                    onClick={() => void openSession(session.id)}
                    disabled={openingSessionId !== null}
                    aria-busy={isOpening}
                    className={`w-full rounded-lg px-3 py-2 text-left text-sm transition-colors disabled:cursor-wait disabled:opacity-70 ${
                      isActive
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-muted"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium">
                          {session.title}
                        </div>
                        <div
                          className={`text-xs ${
                            isActive
                              ? "text-primary-foreground/70"
                              : "text-muted-foreground"
                          }`}
                        >
                          {session.message_count}{" "}
                          {zh ? "条消息" : "messages"}
                        </div>
                      </div>
                      {isOpening && (
                        <LoadingSpinner label={conversationLoadingLabel} />
                      )}
                    </div>
                  </button>
                );
              })
            )}
            {!sessionsQuery.isLoading &&
              (sessionsQuery.data ?? []).length === 0 && (
                <div className="py-8 text-center text-sm text-muted-foreground">
                  {zh ? "暂无对话" : "No conversations"}
                </div>
              )}
          </CardContent>
        </Card>

        <Card className="flex min-h-[680px] flex-col">
          <CardContent className="flex flex-1 flex-col gap-4 pt-6">
            <div
              className="flex-1 space-y-5 overflow-y-auto rounded-lg border bg-muted/20 p-4 sm:p-5"
              aria-busy={
                sendMutation.isPending || openingSessionId !== null
              }
            >
              {openingSessionId && (
                <InlineLoading
                  label={conversationLoadingLabel}
                  className="border-primary/20 bg-primary/5 text-foreground"
                />
              )}
              {messages.length === 0 && !openingSessionId && (
                <div className="flex h-full min-h-80 flex-col items-center justify-center gap-3 text-center text-muted-foreground">
                  <div className="rounded-2xl bg-primary/10 p-3 text-primary">
                    <Bot className="h-8 w-8" />
                  </div>
                  <div>
                    <div className="font-medium text-foreground">
                      {zh
                        ? "告诉我你想更新什么"
                        : "Tell me what to update"}
                    </div>
                    <div className="mt-1 max-w-lg text-sm">
                      {zh
                        ? "例如：7 月 21 日上午 11 点，在 Morgan Stanley 以每股 $685 买入 800 股 SPY，owner 是王晓丽，无手续费；或上传券商持仓截图。"
                        : "For example: At 11:00 on July 21, I bought 800 SPY at $685 per share at Morgan Stanley for owner Wang Xiaoli, with no fee."}
                    </div>
                  </div>
                </div>
              )}
              {messages.map((message, index) => (
                <MessageBubble
                  key={`${message.role}-${index}`}
                  message={message}
                  zh={zh}
                  resolving={
                    resolvePendingMutation.isPending &&
                    resolvePendingMutation.variables?.actionId ===
                      message.pendingAction?.id
                  }
                  onResolve={(actionId, decision) =>
                    resolvePendingMutation.mutate({ actionId, decision })
                  }
                />
              ))}
              {sendMutation.isPending && <AgentThinking zh={zh} />}
            </div>

            {files.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {files.map((file, index) => (
                  <Badge
                    key={`${file.name}-${index}`}
                    variant="secondary"
                    className="gap-1"
                  >
                    <FileImage className="h-3 w-3" />
                    {file.name}
                    <button
                      type="button"
                      onClick={() =>
                        setFiles((old) =>
                          old.filter(
                            (_, itemIndex) => itemIndex !== index,
                          ),
                        )
                      }
                      aria-label={zh ? "移除文件" : "Remove file"}
                    >
                      ×
                    </button>
                  </Badge>
                ))}
              </div>
            )}
            <div className="flex items-end gap-2">
              <Button
                variant="outline"
                size="icon"
                onClick={() => fileInputRef.current?.click()}
                title={zh ? "上传图片或 PDF" : "Upload image or PDF"}
                disabled={sendMutation.isPending}
              >
                <Paperclip className="h-4 w-4" />
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/jpeg,image/png,image/webp,application/pdf"
                className="hidden"
                onChange={(event) => {
                  const selected = Array.from(event.target.files ?? []);
                  setFiles((old) => [...old, ...selected].slice(0, 10));
                  event.target.value = "";
                }}
              />
              <Textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    send();
                  }
                }}
                placeholder={
                  zh
                    ? "输入消息，Enter 发送，Shift+Enter 换行"
                    : "Type a message. Enter to send, Shift+Enter for a new line"
                }
                className="min-h-20 flex-1"
                disabled={sendMutation.isPending}
              />
              <Button
                size="icon"
                onClick={send}
                disabled={!input.trim() || sendMutation.isPending}
                aria-busy={sendMutation.isPending}
                aria-label={zh ? "发送消息" : "Send message"}
              >
                {sendMutation.isPending ? (
                  <LoadingSpinner
                    label={zh ? "正在发送" : "Sending message"}
                  />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <ProviderSettings
        open={settingsOpen}
        setOpen={setSettingsOpen}
        zh={zh}
      />
    </div>
  );
}

const ZH_TOOL_LABELS: Record<string, string> = {
  create_owner: "创建 owner",
  update_owner: "修改 owner",
  delete_owner: "删除 owner",
  create_institution: "创建机构",
  update_institution: "修改机构",
  delete_institution: "删除机构",
  create_account: "创建账户",
  update_account: "修改账户",
  delete_account: "删除账户",
  create_instrument: "创建资产",
  update_instrument: "修改资产",
  delete_instrument: "删除资产",
  create_exposure_group: "创建敞口组",
  update_exposure_group: "修改敞口组",
  delete_exposure_group: "删除敞口组",
  set_holding_snapshot: "设置持仓",
  adjust_holding: "调整持仓",
  delete_holding: "删除持仓",
  create_buy_transaction: "录入买入",
  create_sell_transaction: "录入卖出",
  create_transfer: "录入转仓",
  create_currency_exchange: "录入换汇",
  create_income_transaction: "录入收入",
  create_fee_transaction: "录入费用",
  create_cash_transaction: "录入现金交易",
  create_manual_adjustment: "录入手工调整",
  update_transaction_metadata: "修改交易信息",
  delete_transaction: "删除交易",
  reverse_transaction: "冲销交易",
  set_cash_balance: "设置现金余额",
  set_manual_valuation: "设置手工估值",
  set_fx_rate: "设置汇率",
  update_app_settings: "修改系统基准币种",
  refresh_market_prices: "刷新市场价格",
  recalculate_portfolio: "重算投资组合",
  create_valuation_snapshot: "保存估值快照",
};

function toolLabel(tool: string, zh: boolean) {
  return zh ? (ZH_TOOL_LABELS[tool] ?? tool) : tool.replaceAll("_", " ");
}

const ZH_ARGUMENT_LABELS: Record<string, string> = {
  account_id: "账户",
  account_name: "账户名称",
  account_type: "账户类型",
  amount: "金额",
  asset_class: "资产类别",
  base_currency: "基础币种",
  country: "国家 / 地区",
  currency: "币种",
  executed_at: "成交时间",
  fee: "手续费",
  fee_currency: "手续费币种",
  from_account_id: "转出账户",
  from_currency: "卖出币种",
  group_id: "敞口组",
  institution_id: "机构",
  institution_name: "机构名称",
  institution_type: "机构类型",
  instrument_id: "资产",
  market: "市场",
  name: "名称",
  note: "备注",
  owner_id: "Owner",
  owner_name: "Owner 姓名",
  owner_type: "Owner 类型",
  price: "成交价",
  quantity: "数量",
  rate: "汇率",
  symbol: "代码",
  to_account_id: "转入账户",
  to_currency: "买入币种",
  transaction_id: "交易",
  transaction_type: "交易类型",
};

function argumentLabel(key: string, zh: boolean) {
  if (zh) return ZH_ARGUMENT_LABELS[key] ?? key.replaceAll("_", " ");
  return key.replaceAll("_", " ");
}

function formatArgumentValue(value: unknown, key: string, zh: boolean) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") {
    return value ? (zh ? "是" : "Yes") : zh ? "否" : "No";
  }
  if (typeof value === "number") {
    return new Intl.NumberFormat(zh ? "zh-CN" : "en-US", {
      maximumFractionDigits: 8,
    }).format(value);
  }
  if (Array.isArray(value)) {
    return value
      .map((item) =>
        typeof item === "object" ? JSON.stringify(item) : String(item),
      )
      .join(", ");
  }
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value);
  if (
    key.endsWith("_id") &&
    /^[0-9a-f]{8}-[0-9a-f-]{23,}$/i.test(text)
  ) {
    return `${text.slice(0, 8)}…${text.slice(-4)}`;
  }
  return text;
}

function pendingErrorMessage(error: string, zh: boolean) {
  if (error.includes("MissingGreenlet")) {
    return zh
      ? "数据库更新会话曾意外中断；该问题已修复，可重新执行此计划。"
      : "The database update session was interrupted. The issue is fixed and this plan can be retried.";
  }
  if (error.includes("portfolio_state_changed")) {
    return zh
      ? "确认期间投资组合数据已发生变化。为避免覆盖新数据，此计划已失效。"
      : "Portfolio data changed before confirmation, so this plan was invalidated to protect newer data.";
  }
  return zh
    ? "执行未完成，整组变更已回滚。请查看技术详情或重新提交请求。"
    : "Execution did not complete and the full plan was rolled back. Review the technical details or submit it again.";
}

function AgentMarkdown({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      components={{
        h1: ({ children }) => (
          <h1 className="mb-3 mt-4 text-xl font-semibold first:mt-0">
            {children}
          </h1>
        ),
        h2: ({ children }) => (
          <h2 className="mb-2 mt-4 text-lg font-semibold first:mt-0">
            {children}
          </h2>
        ),
        h3: ({ children }) => (
          <h3 className="mb-2 mt-3 font-semibold first:mt-0">{children}</h3>
        ),
        p: ({ children }) => (
          <p className="my-2 leading-6 first:mt-0 last:mb-0">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>
        ),
        li: ({ children }) => <li className="pl-0.5">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="my-3 border-l-2 border-primary/40 pl-3 text-muted-foreground">
            {children}
          </blockquote>
        ),
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="font-medium text-primary underline underline-offset-4"
          >
            {children}
          </a>
        ),
        table: ({ children }) => (
          <div className="my-3 max-w-full overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[420px] border-collapse text-left text-sm">
              {children}
            </table>
          </div>
        ),
        th: ({ children }) => (
          <th className="border-b bg-muted/70 px-3 py-2 font-semibold">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="border-b px-3 py-2 align-top last:border-b">
            {children}
          </td>
        ),
        pre: ({ children }) => (
          <pre className="my-3 max-w-full overflow-x-auto rounded-lg bg-muted p-3 text-xs leading-5">
            {children}
          </pre>
        ),
        code: ({ children }) => (
          <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.9em]">
            {children}
          </code>
        ),
        hr: () => <hr className="my-4 border-border" />,
        img: ({ alt }) => (
          <span className="text-sm text-muted-foreground">
            [{alt || "image"}]
          </span>
        ),
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

function AgentThinking({ zh }: { zh: boolean }) {
  const label = zh
    ? "正在查询并准备变更清单…"
    : "Querying data and preparing a change plan…";
  return (
    <div className="flex items-start gap-3">
      <div className="mt-1 rounded-full bg-primary p-2 text-primary-foreground shadow-sm">
        <Bot className="h-4 w-4" />
      </div>
      <div
        role="status"
        aria-live="polite"
        className="w-full max-w-xl space-y-3 rounded-2xl border bg-card px-4 py-3 shadow-sm"
      >
        <div className="flex items-center gap-2 text-sm font-medium">
          <LoadingSpinner label={label} />
          <span>{label}</span>
        </div>
        <div aria-hidden="true" className="space-y-2">
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="h-3 w-2/3" />
        </div>
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  zh,
  resolving,
  onResolve,
}: {
  message: LocalMessage;
  zh: boolean;
  resolving: boolean;
  onResolve: (actionId: string, decision: "confirm" | "cancel") => void;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <div className="mt-1 rounded-full bg-primary p-2 text-primary-foreground shadow-sm">
          <Bot className="h-4 w-4" />
        </div>
      )}
      <div
        className={`space-y-3 rounded-2xl px-4 py-3 text-sm ${
          isUser
            ? "max-w-[85%] bg-primary text-primary-foreground"
            : "max-w-[92%] bg-card shadow-sm ring-1 ring-border lg:max-w-[88%]"
        }`}
      >
        {isUser ? (
          <div className="whitespace-pre-wrap leading-6">
            {message.content}
          </div>
        ) : (
          <AgentMarkdown content={message.content} />
        )}
        {(message.files ?? []).length > 0 && (
          <div className="flex flex-wrap gap-1">
            {message.files?.map((file) => (
              <Badge key={file} variant="secondary">
                {file}
              </Badge>
            ))}
          </div>
        )}
        {message.pendingAction && (
          <PendingActionCard
            pending={message.pendingAction}
            zh={zh}
            resolving={resolving}
            onResolve={onResolve}
          />
        )}
        {(message.trace ?? []).length > 0 && (
          <ToolTraceDetails trace={message.trace ?? []} zh={zh} />
        )}
      </div>
      {isUser && (
        <div className="mt-1 rounded-full bg-muted p-2">
          <User className="h-4 w-4" />
        </div>
      )}
    </div>
  );
}

function PendingActionCard({
  pending,
  zh,
  resolving,
  onResolve,
}: {
  pending: AgentPendingAction;
  zh: boolean;
  resolving: boolean;
  onResolve: (actionId: string, decision: "confirm" | "cancel") => void;
}) {
  const destructive = pending.tool_calls.some(
    (call) => call.effect === "delete",
  );
  const retryable = pending.status === "failed";
  const resultChanges = pending.result_trace.reduce(
    (total, trace) => ({
      created: total.created + trace.changes.created,
      updated: total.updated + trace.changes.updated,
      deleted: total.deleted + trace.changes.deleted,
    }),
    { created: 0, updated: 0, deleted: 0 },
  );
  const status = pendingStatusPresentation(pending.status, zh);
  const StatusIcon = status.icon;

  return (
    <section
      aria-label={zh ? "数据库变更确认" : "Database change confirmation"}
      aria-busy={resolving}
      className={`overflow-hidden rounded-xl border ${
        destructive || pending.status === "failed"
          ? "border-destructive/45 bg-destructive/[0.035]"
          : pending.status === "confirmed"
            ? "border-emerald-500/35 bg-emerald-500/[0.04]"
            : "border-amber-400/55 bg-amber-500/[0.045]"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b bg-background/65 px-4 py-3">
        <div className="flex min-w-0 items-start gap-3">
          <div
            className={`mt-0.5 rounded-lg p-2 ${
              destructive || pending.status === "failed"
                ? "bg-destructive/10 text-destructive"
                : pending.status === "confirmed"
                  ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                  : "bg-amber-500/10 text-amber-700 dark:text-amber-400"
            }`}
          >
            {destructive ? (
              <AlertTriangle className="h-4 w-4" />
            ) : (
              <ShieldCheck className="h-4 w-4" />
            )}
          </div>
          <div>
            <div className="font-semibold">
              {pending.status === "confirmed"
                ? zh
                  ? "数据库变更已完成"
                  : "Database changes completed"
                : pending.status === "failed"
                  ? zh
                    ? "数据库变更执行失败"
                    : "Database changes failed"
                  : zh
                    ? `数据库变更确认（${pending.tool_calls.length} 项）`
                    : `Confirm database changes (${pending.tool_calls.length})`}
            </div>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {pending.status === "pending"
                ? zh
                  ? "确认后才会写入数据库，请核对以下内容。"
                  : "Nothing is written until you confirm. Review the details below."
                : pending.status === "failed"
                  ? zh
                    ? "数据尚未完整写入；修正问题后可安全重试。"
                    : "The changes were not fully written. You can retry after addressing the error."
                  : zh
                    ? "以下为本次操作记录。"
                    : "This is the operation record."}
            </p>
          </div>
        </div>
        <Badge variant={pending.status === "confirmed" ? "default" : "outline"}>
          <StatusIcon className="h-3.5 w-3.5" />
          {status.label}
        </Badge>
      </div>

      <div className="space-y-3 p-3">
        {pending.tool_calls.map((call, index) => (
          <PendingToolCallCard
            key={call.id}
            call={call}
            index={index}
            zh={zh}
          />
        ))}

        {pending.result_trace.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-500/25 bg-emerald-500/[0.045] px-3 py-2 text-xs">
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            <span className="font-medium">
              {zh ? "执行结果" : "Execution result"}
            </span>
            <Badge variant="outline">+{resultChanges.created}</Badge>
            <Badge variant="outline">~{resultChanges.updated}</Badge>
            <Badge variant="outline">−{resultChanges.deleted}</Badge>
          </div>
        )}

        {pending.error && (
          <div
            role="alert"
            className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive"
          >
            <div className="flex items-start gap-2">
              <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{pendingErrorMessage(pending.error, zh)}</span>
            </div>
            <details className="mt-2 border-t border-destructive/20 pt-2 text-[11px]">
              <summary className="cursor-pointer select-none">
                {zh ? "查看技术详情" : "View technical details"}
              </summary>
              <div className="mt-1 break-all font-mono">{pending.error}</div>
            </details>
          </div>
        )}

        {resolving && (
          <InlineLoading
            label={
              zh ? "正在校验并执行数据库变更…" : "Validating and applying changes…"
            }
            className="border-primary/20 bg-primary/5 text-foreground"
          />
        )}

        {pending.status === "pending" && (
          <div className="flex flex-wrap justify-end gap-2 border-t pt-3">
            <Button
              size="sm"
              variant="outline"
              disabled={resolving}
              onClick={() => onResolve(pending.id, "cancel")}
            >
              <X className="h-3.5 w-3.5" />
              {zh ? "取消" : "Cancel"}
            </Button>
            <Button
              size="sm"
              variant={destructive ? "destructive" : "default"}
              disabled={resolving}
              aria-busy={resolving}
              onClick={() => onResolve(pending.id, "confirm")}
            >
              {resolving ? (
                <LoadingSpinner
                  label={zh ? "正在执行" : "Applying changes"}
                />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              {resolving
                ? zh
                  ? "执行中…"
                  : "Running…"
                : zh
                  ? "确认执行"
                  : "Confirm"}
            </Button>
          </div>
        )}

        {retryable && (
          <div className="flex justify-end border-t pt-3">
            <Button
              size="sm"
              variant={destructive ? "destructive" : "default"}
              disabled={resolving}
              aria-busy={resolving}
              onClick={() => onResolve(pending.id, "confirm")}
            >
              {resolving ? (
                <LoadingSpinner
                  label={zh ? "正在重试" : "Retrying changes"}
                />
              ) : (
                <Database className="h-3.5 w-3.5" />
              )}
              {resolving
                ? zh
                  ? "重试中…"
                  : "Retrying…"
                : zh
                  ? "重试执行"
                  : "Retry changes"}
            </Button>
          </div>
        )}
      </div>
    </section>
  );
}

function PendingToolCallCard({
  call,
  index,
  zh,
}: {
  call: AgentPendingToolCall;
  index: number;
  zh: boolean;
}) {
  const entries = Object.entries(call.args);
  const effectLabel = {
    create: zh ? "新增" : "Create",
    update: zh ? "修改" : "Update",
    delete: zh ? "删除" : "Delete",
  }[call.effect];

  return (
    <article className="rounded-lg border bg-background/85 p-3 shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2 font-medium">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px]">
            {index + 1}
          </span>
          <span>{toolLabel(call.tool, zh)}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge
            variant={call.effect === "delete" ? "destructive" : "secondary"}
          >
            {effectLabel}
          </Badge>
          <Badge variant="outline">{call.resource}</Badge>
        </div>
      </div>

      {entries.length > 0 ? (
        <dl className="mt-3 grid gap-x-5 gap-y-2 sm:grid-cols-2">
          {entries.map(([key, value]) => (
            <div
              key={key}
              className="grid min-w-0 grid-cols-[minmax(5.5rem,auto)_1fr] gap-2 border-t border-border/60 pt-2"
            >
              <dt className="text-xs text-muted-foreground">
                {argumentLabel(key, zh)}
              </dt>
              <dd
                className={`min-w-0 break-words text-right text-xs font-medium ${
                  key.endsWith("_id") ? "font-mono" : ""
                }`}
                title={String(value ?? "")}
              >
                {formatArgumentValue(value, key, zh)}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-2 text-xs text-muted-foreground">
          {zh ? "无额外参数" : "No additional parameters"}
        </p>
      )}

      <details className="mt-3 border-t pt-2 text-xs">
        <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
          {zh ? "查看原始 JSON" : "View raw JSON"}
        </summary>
        <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap rounded-md bg-muted/70 p-2 font-mono text-[11px] leading-4">
          {JSON.stringify(call.args, null, 2)}
        </pre>
      </details>
    </article>
  );
}

function pendingStatusPresentation(
  status: AgentPendingAction["status"],
  zh: boolean,
) {
  switch (status) {
    case "pending":
      return {
        label: zh ? "尚未写入" : "Not written",
        icon: ShieldCheck,
      };
    case "executing":
      return { label: zh ? "执行中" : "Running", icon: Database };
    case "confirmed":
      return { label: zh ? "已执行" : "Completed", icon: CheckCircle2 };
    case "cancelled":
      return { label: zh ? "已取消" : "Cancelled", icon: XCircle };
    case "failed":
      return { label: zh ? "执行失败" : "Failed", icon: AlertTriangle };
    case "stale":
      return { label: zh ? "已失效" : "Stale", icon: XCircle };
  }
}

function ToolTraceDetails({
  trace,
  zh,
}: {
  trace: AgentToolTrace[];
  zh: boolean;
}) {
  return (
    <details className="rounded-lg border border-border/70 bg-muted/20 p-2.5">
      <summary className="cursor-pointer select-none font-medium">
        {zh ? `工具调用详情（${trace.length}）` : `Tool calls (${trace.length})`}
      </summary>
      <div className="mt-2 space-y-2">
        {trace.map((item) => (
          <div
            key={item.id}
            className="rounded-md border bg-background/80 p-2.5 text-xs text-foreground"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono font-medium">{item.tool}</span>
              {item.status === "pending_confirmation" && (
                <Badge variant="outline">
                  {zh ? "待确认" : "Pending"}
                </Badge>
              )}
            </div>
            <details className="mt-2">
              <summary className="cursor-pointer text-muted-foreground">
                {zh ? "查看参数" : "View arguments"}
              </summary>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-muted/60 p-2">
                {JSON.stringify(item.args, null, 2)}
              </pre>
            </details>
            {item.error ? (
              <div className="mt-1 text-destructive">{item.error}</div>
            ) : (
              <div className="mt-1 text-muted-foreground">
                +{item.changes.created} / ~{item.changes.updated} / −
                {item.changes.deleted}
              </div>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

function ProviderSettings({
  open,
  setOpen,
  zh,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
  zh: boolean;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ProviderSetupForm>(() =>
    createProviderSetup(),
  );
  const preset = PROVIDER_PRESETS[form.providerKey];
  const providersQuery = useQuery({
    queryKey: ["llm-providers"],
    queryFn: () =>
      api.get<LLMProvider[]>("/api/settings/llm-providers"),
    enabled: open,
  });
  const createMutation = useMutation({
    mutationFn: async () => {
      const configurations = [
        { role: "chat", modelName: form.chatModel },
        ...(form.visionModel
          ? [{ role: "vision", modelName: form.visionModel }]
          : []),
      ];
      return Promise.all(
        configurations.map(({ role, modelName }) => {
          const existing = providersQuery.data?.find(
            (provider) =>
              provider.provider_key === form.providerKey &&
              provider.role === role &&
              provider.model_name === modelName,
          );
          if (existing) {
            return api.patch<LLMProvider>(
              `/api/settings/llm-providers/${existing.id}`,
              {
                api_key: form.apiKey.trim(),
                is_active: true,
              },
            );
          }
          return api.post<LLMProvider>("/api/settings/llm-providers", {
            name: `${preset.label} · ${modelName}`,
            provider_key: form.providerKey,
            role,
            base_url: preset.baseUrl,
            api_key: form.apiKey.trim(),
            model_name: modelName,
            is_active: true,
          });
        }),
      );
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] });
      setForm((old) => ({ ...old, apiKey: "" }));
      toast.success(
        zh
          ? "API Key 与模型已保存并激活"
          : "API key and models saved and activated",
      );
    },
    onError: (error) =>
      toast.error(
        error instanceof ApiError
          ? error.message
          : zh
            ? "保存失败"
            : "Save failed",
      ),
  });
  const activateMutation = useMutation({
    mutationFn: (id: string) =>
      api.patch<LLMProvider>(`/api/settings/llm-providers/${id}`, {
        is_active: true,
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] }),
    onError: () => toast.error(zh ? "激活失败" : "Activation failed"),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      api.delete<void>(`/api/settings/llm-providers/${id}`),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["llm-providers"] }),
    onError: () => toast.error(zh ? "删除失败" : "Delete failed"),
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{zh ? "模型设置" : "Model settings"}</DialogTitle>
          <DialogDescription>
            {zh
              ? "选择供应商和模型，只需填写 API Key。地址、名称和角色由系统自动配置；Key 加密保存且不会回显。"
              : "Choose a provider and models, then enter only your API key. Endpoints, names, and roles are configured automatically; keys are encrypted and never returned."}
          </DialogDescription>
        </DialogHeader>

        <div
          className="space-y-3"
          aria-busy={providersQuery.isLoading}
        >
          {providersQuery.isLoading ? (
            <ListSkeleton
              compact
              rows={3}
              label={zh ? "正在加载模型配置" : "Loading model settings"}
            />
          ) : (
            (providersQuery.data ?? []).map((provider) => {
              const isActivating =
                activateMutation.isPending &&
                activateMutation.variables === provider.id;
              const isDeleting =
                deleteMutation.isPending &&
                deleteMutation.variables === provider.id;
              return (
                <div
                  key={provider.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-3"
                  aria-busy={isActivating || isDeleting}
                >
                  <div>
                    <div className="flex items-center gap-2 font-medium">
                      {provider.model_name}
                      <Badge variant="outline">
                        {provider.role === "chat"
                          ? zh
                            ? "聊天"
                            : "Chat"
                          : zh
                            ? "识图"
                            : "Vision"}
                      </Badge>
                      {provider.is_active && (
                        <Badge>{zh ? "已激活" : "Active"}</Badge>
                      )}
                    </div>
                    <div className="mt-1 text-xs text-muted-foreground">
                      {PROVIDER_PRESETS[
                        provider.provider_key as ProviderKey
                      ]?.label ?? provider.provider_key}
                    </div>
                  </div>
                  <div className="flex gap-1">
                    {!provider.is_active && (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={
                          activateMutation.isPending ||
                          deleteMutation.isPending
                        }
                        onClick={() => activateMutation.mutate(provider.id)}
                      >
                        {isActivating && (
                          <LoadingSpinner
                            label={zh ? "正在激活" : "Activating"}
                          />
                        )}
                        {isActivating
                          ? zh
                            ? "激活中…"
                            : "Activating…"
                          : zh
                            ? "激活"
                            : "Activate"}
                      </Button>
                    )}
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      disabled={
                        activateMutation.isPending ||
                        deleteMutation.isPending
                      }
                      aria-label={zh ? "删除模型配置" : "Delete model setting"}
                      onClick={() => {
                        if (
                          window.confirm(
                            zh
                              ? "删除该模型配置？"
                              : "Delete this model configuration?",
                          )
                        ) {
                          deleteMutation.mutate(provider.id);
                        }
                      }}
                    >
                      {isDeleting ? (
                        <LoadingSpinner
                          label={zh ? "正在删除" : "Deleting model"}
                        />
                      ) : (
                        <Trash2 className="h-4 w-4" />
                      )}
                    </Button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="border-t pt-4">
          <div className="mb-3 font-medium">
            {zh ? "添加模型" : "Add models"}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <ProviderField label={zh ? "供应商" : "Provider"}>
              <select
                value={form.providerKey}
                onChange={(event) =>
                  setForm(
                    createProviderSetup(
                      event.target.value as ProviderKey,
                    ),
                  )
                }
                className="h-9 w-full rounded-lg border bg-transparent px-3 text-sm"
              >
                {Object.entries(PROVIDER_PRESETS).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value.label}
                  </option>
                ))}
              </select>
            </ProviderField>
            <ProviderField label={zh ? "聊天模型" : "Chat model"}>
              <select
                value={form.chatModel}
                onChange={(event) =>
                  setForm((old) => ({
                    ...old,
                    chatModel: event.target.value,
                  }))
                }
                className="h-9 w-full rounded-lg border bg-transparent px-3 text-sm"
              >
                {preset.chatModels.map((model) => (
                  <option key={model} value={model}>
                    {model}
                  </option>
                ))}
              </select>
            </ProviderField>
            <ProviderField label={zh ? "识图模型" : "Vision model"}>
              {preset.visionModels.length > 0 ? (
                <select
                  value={form.visionModel}
                  onChange={(event) =>
                    setForm((old) => ({
                      ...old,
                      visionModel: event.target.value,
                    }))
                  }
                  className="h-9 w-full rounded-lg border bg-transparent px-3 text-sm"
                >
                  {preset.visionModels.map((model) => (
                    <option key={model} value={model}>
                      {model}
                    </option>
                  ))}
                </select>
              ) : (
                <div className="flex h-9 items-center rounded-lg border bg-muted px-3 text-sm text-muted-foreground">
                  {zh
                    ? "该供应商暂不支持识图"
                    : "Vision is not supported by this provider"}
                </div>
              )}
            </ProviderField>
            <ProviderField label="API Key">
              <Input
                type="password"
                value={form.apiKey}
                onChange={(event) =>
                  setForm((old) => ({
                    ...old,
                    apiKey: event.target.value,
                  }))
                }
                placeholder={zh ? "粘贴 API Key" : "Paste API key"}
                autoComplete="new-password"
              />
            </ProviderField>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {zh ? "关闭" : "Close"}
          </Button>
          <Button
            onClick={() => createMutation.mutate()}
            disabled={!form.apiKey.trim() || createMutation.isPending}
            aria-busy={createMutation.isPending}
          >
            {createMutation.isPending && (
              <LoadingSpinner label={zh ? "正在保存" : "Saving model"} />
            )}
            {createMutation.isPending
              ? zh
                ? "正在保存…"
                : "Saving…"
              : zh
                ? "保存并激活"
                : "Save and activate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProviderField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
    </div>
  );
}
