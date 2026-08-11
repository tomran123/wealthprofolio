export type OwnerType = "individual" | "family_entity";
export type InstitutionType = "bank" | "broker" | "other";
export type AccountType = "cash" | "brokerage" | "mixed";
export type AssetClass =
  | "cash"
  | "equity"
  | "etf"
  | "bond"
  | "fund"
  | "real_estate"
  | "private_equity"
  | "company_equity"
  | "gold"
  | "crypto"
  | "custom"
  | "liability";
export type MarketRegion =
  | "US"
  | "HK"
  | "CN"
  | "CRYPTO"
  | "COMMODITY"
  | "OTHER";
export type PriceSourceType =
  | "market"
  | "manual"
  | "fx_derived"
  | "fixed_principal";
export type HoldingSource = "manual" | "import" | "agent" | "screenshot";
export type QuoteStatus = "realtime" | "delayed" | "close" | "manual" | "fixed";
export type TransactionType =
  | "buy"
  | "sell"
  | "deposit"
  | "withdraw"
  | "transfer_in"
  | "transfer_out"
  | "fx_exchange"
  | "dividend"
  | "interest"
  | "fee"
  | "manual_adjustment"
  | "valuation_update"
  | "opening_balance"
  | "reconciliation"
  | "tax"
  | "split"
  | "reverse_split"
  | "merger"
  | "stock_dividend"
  | "metadata_amended";
export type TransactionSource = "manual" | "import" | "agent" | "screenshot";
export type LLMRole = "chat" | "vision";

export interface Owner {
  id: string;
  name: string;
  owner_type: OwnerType;
  display_order: number;
}

export interface Institution {
  id: string;
  name: string;
  institution_type: InstitutionType;
  country: string | null;
}

export interface ExposureGroup {
  id: string;
  name: string;
  description: string | null;
}

export interface Instrument {
  id: string;
  symbol: string | null;
  name: string;
  asset_class: AssetClass;
  currency: string;
  country: string | null;
  market: MarketRegion;
  exposure_group_id: string | null;
  price_source_type: PriceSourceType;
}

export interface MarketInstrumentSearchItem {
  selection_token: string;
  symbol: string;
  name: string;
  asset_class: AssetClass;
  currency: string;
  market: MarketRegion;
  exchange: string | null;
  source: "local" | "yahoo" | "akshare" | "coingecko" | string;
  is_local: boolean;
}

export interface MarketInstrumentSearchResponse {
  items: MarketInstrumentSearchItem[];
  unavailable_sources: string[];
}

export interface AccountWithNames {
  id: string;
  institution_id: string;
  owner_id: string;
  name: string;
  account_type: AccountType;
  base_currency: string;
  account_number_mask: string | null;
  institution_name: string;
  owner_name: string;
}

export interface HoldingWithInstrument {
  id: string;
  account_id: string;
  instrument_id: string;
  quantity: string;
  source: HoldingSource;
  instrument_name: string;
  instrument_symbol: string | null;
  price_source_type: PriceSourceType;
  price: string | null;
  price_currency: string | null;
  market_value: string | null;
  quote_status: QuoteStatus | null;
  price_as_of: string | null;
}

export interface MarketHoldingCreateResult {
  holding: HoldingWithInstrument;
  price: string;
  currency: string;
  market_value: string;
  quote_status: QuoteStatus;
  price_as_of: string;
  source_provider: string;
}

export interface HoldingDetail {
  account_id: string;
  account_name: string;
  institution_name: string;
  owner_name: string;
  instrument_id: string;
  instrument_name: string;
  instrument_symbol: string | null;
  quantity: string;
  price: string | null;
  price_currency: string | null;
  value_base: string;
  quote_status: string | null;
  price_as_of: string | null;
}

export interface AggregateGroup {
  key: string;
  label: string;
  value_base: string;
  percentage: number;
  holdings_count: number;
  details: HoldingDetail[];
}

export interface AggregateResponse {
  dimension: string;
  base_currency: string;
  total_value: string;
  groups: AggregateGroup[];
  total_liabilities: string;
  liability_groups: AggregateGroup[];
  generated_at: string;
}

export interface PortfolioSummary {
  base_currency: string;
  total_assets: string;
  total_liabilities: string;
  net_worth: string;
  generated_at: string;
  holdings_count: number;
  missing_price_count: number;
  missing_fx_count: number;
}

export interface ImportPreviewRow {
  row_index: number;
  owner_name: string;
  owner_id: string | null;
  institution_name: string;
  institution_id: string | null;
  account_name: string;
  account_id: string | null;
  instrument_name: string;
  ticker: string | null;
  instrument_id: string | null;
  asset_type: string;
  quantity: string | null;
  currency: string | null;
  cost_price: string | null;
  current_price: string | null;
  valuation_date: string | null;
  exposure_group: string | null;
  country: string | null;
  liquidity_type: string | null;
  errors: string[];
}

export interface ImportBatch {
  id: string;
  filename: string;
  status: "pending" | "committed" | "failed";
  row_count: number;
  matched_count: number;
  created_count: number;
  error_count: number;
  rows: ImportPreviewRow[];
}

export interface UserInfo {
  username: string;
  display_name: string;
}

export interface AppSettings {
  base_currency: string;
}

export interface PriceRefreshResult {
  success_count: number;
  kept_count: number;
  failed_count: number;
  failed_symbols: string[];
  errors: Array<{ symbol: string; error: string }>;
  fx_error: string | null;
  refreshed_at: string;
  snapshot_id: string;
}

export interface ValuationSnapshot {
  id: string;
  created_at: string;
  base_currency: string;
  total_assets: string;
  total_liabilities: string;
  net_worth: string;
  allocation_json: Record<string, unknown>;
  refresh_result_json: Record<string, unknown>;
}

export interface ValuationSnapshotPage {
  items: ValuationSnapshot[];
  total: number;
  offset: number;
  limit: number;
}

export interface Transaction {
  id: string;
  created_at: string;
  updated_at: string;
  account_id: string;
  account_name: string;
  instrument_id: string | null;
  instrument_name: string | null;
  instrument_symbol: string | null;
  transaction_type: TransactionType;
  quantity: string;
  price: string | null;
  currency: string;
  amount: string;
  fee: string;
  fee_currency: string;
  trade_date: string;
  executed_at: string | null;
  settlement_date: string | null;
  external_ref: string | null;
  linked_transaction_id: string | null;
  note: string | null;
  source: TransactionSource;
  is_reversed: boolean;
  reversed_by_id: string | null;
}

export interface TransactionPage {
  items: Transaction[];
  total: number;
  offset: number;
  limit: number;
  summary: {
    by_currency: Array<{
      currency: string;
      total_buy: string;
      total_sell: string;
      net_cash_flow: string;
    }>;
  };
}

export interface TransactionMutationResult {
  transactions: Transaction[];
}

export interface TransactionMetadataUpdate {
  trade_date?: string;
  executed_at?: string | null;
  settlement_date?: string | null;
  external_ref?: string | null;
  note?: string | null;
}

export interface LLMProvider {
  id: string;
  name: string;
  provider_key: string;
  role: LLMRole;
  base_url: string;
  model_name: string;
  is_active: boolean;
  has_api_key: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentToolTrace {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  result: unknown;
  error: string | null;
  status?: "completed" | "pending_confirmation" | "failed";
  requires_confirmation?: boolean;
  changes: { created: number; updated: number; deleted: number };
}

export type AgentPendingActionStatus =
  | "pending"
  | "executing"
  | "confirmed"
  | "cancelled"
  | "failed"
  | "stale";

export interface AgentPendingToolCall {
  id: string;
  tool: string;
  effect: "create" | "update" | "delete";
  resource: string;
  args: Record<string, unknown>;
}

export interface AgentPendingAction {
  id: string;
  created_at: string;
  status: AgentPendingActionStatus;
  tool_calls: AgentPendingToolCall[];
  result_trace: AgentToolTrace[];
  error: string | null;
  resolved_at: string | null;
}

export interface AgentTurnResult {
  session_id: string;
  assistant_message: string;
  tool_call_trace: AgentToolTrace[];
  extracted_documents: Array<Record<string, unknown>>;
  pending_action: AgentPendingAction | null;
}

export interface AgentMessage {
  id: string;
  created_at: string;
  role: "user" | "assistant";
  content: string;
  attachments: Array<Record<string, unknown>>;
  tool_trace: AgentToolTrace[];
  pending_action: AgentPendingAction | null;
}

export interface AgentSession {
  id: string;
  created_at: string;
  updated_at: string;
  title: string;
  message_count: number;
}

export interface AgentSessionDetail extends AgentSession {
  messages: AgentMessage[];
}

export interface AgentOperationLogToolCall {
  id?: string;
  tool?: string;
  effect?: "create" | "update" | "delete";
  resource?: string;
  status?: string;
  event_ids?: string[];
}

export interface AgentOperationSummary {
  operation_count?: number;
  effects?: Record<string, number>;
  resources?: string[];
  event_count?: number;
  compensates_log_id?: string;
  [key: string]: unknown;
}

export interface AgentOperationLog {
  id: string;
  created_at: string;
  session_id: string;
  turn_index: number;
  operation_type: string;
  user_message: string;
  description: string;
  tool_calls: AgentOperationLogToolCall[];
  change_summary: { created: number; updated: number; deleted: number };
  event_ids: string[];
  summary: AgentOperationSummary;
  is_undoable: boolean;
  is_undone: boolean;
  undone_at: string | null;
  linked_to_id: string | null;
}

export interface AgentOperationLogPage {
  items: AgentOperationLog[];
  total: number;
  offset: number;
  limit: number;
}

export interface AgentUndoResult {
  ok: boolean;
  log_id: string;
  undone_at: string;
}

export type DocumentStatus =
  | "pending_upload"
  | "uploading"
  | "uploaded"
  | "queued"
  | "processing"
  | "ready"
  | "failed"
  | "archived";

export type DocumentPageStatus =
  | "pending"
  | "processing"
  | "ready"
  | "failed";

export type BackgroundJobStatus =
  | "pending"
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface BackgroundJob<
  TResult = Record<string, unknown>,
> {
  id: string;
  job_type: string;
  status: BackgroundJobStatus;
  stage: string | null;
  progress: number;
  message: string | null;
  error: string | null;
  result: TResult | null;
  resource_type: string | null;
  resource_id: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface JobSnapshotEvent<
  TResult = Record<string, unknown>,
> {
  type: "job.snapshot";
  job: BackgroundJob<TResult>;
}

export interface DocumentUploadIntentInput {
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256?: string;
  document_type?: string;
  owner_id?: string;
  institution_id?: string;
  account_id?: string;
  document_date?: string;
  metadata?: Record<string, unknown>;
}

export interface DocumentUploadTarget {
  method: "PUT";
  url: string;
  headers: Record<string, string>;
  expires_at: string;
}

export interface DocumentUploadIntent {
  document_id: string;
  version_id: string;
  status: DocumentStatus;
  duplicate: boolean;
  upload: DocumentUploadTarget | null;
  upload_token: string | null;
}

export interface DocumentContentReceipt {
  document_id: string;
  version_id: string;
  received_bytes: number;
  sha256: string;
}

export interface DocumentPage {
  id: string;
  page_number: number;
  status: DocumentPageStatus;
  text_preview: string | null;
  ocr_confidence: number | null;
  preview_url: string | null;
  width: number | null;
  height: number | null;
}

export interface DocumentCitation {
  document_id: string;
  filename: string;
  page_number: number;
  citation: string;
  bounding_boxes: number[][];
  content: string | null;
}

export interface DocumentExtractedField {
  name: string;
  label: string | null;
  value: unknown;
  confidence: number | null;
  page_number: number | null;
  citation: string | null;
  bounding_box: number[] | null;
}

export interface DocumentExtraction {
  id: string;
  extraction_type: string;
  status: string;
  summary: string | null;
  confidence: number | null;
  fields: DocumentExtractedField[];
  created_at: string;
  updated_at: string;
}

export interface DocumentSummary {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  document_type: string | null;
  document_date: string | null;
  status: DocumentStatus;
  page_count: number;
  owner_id: string | null;
  institution_id: string | null;
  account_id: string | null;
  latest_job_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentDetail extends DocumentSummary {
  sha256: string;
  metadata: Record<string, unknown>;
  pages: DocumentPage[];
  extractions: DocumentExtraction[];
}

export interface DocumentPageResult {
  items: DocumentSummary[];
  total: number;
  offset: number;
  limit: number;
}

export interface DocumentCompleteResult {
  document: DocumentSummary;
  job: BackgroundJob;
}

export interface KnowledgeFilters {
  limit?: number;
  document_ids?: string[];
  document_types?: string[];
  date_from?: string;
  date_to?: string;
  institution_id?: string;
  account_id?: string;
}

export interface KnowledgeSearchInput extends KnowledgeFilters {
  query: string;
}

export interface KnowledgeSearchItem {
  chunk_id: string;
  document_id: string;
  filename: string;
  page_number: number;
  content: string;
  score: number;
  citation: string;
  bounding_boxes: number[][];
}

export interface KnowledgeSearchResult {
  items: KnowledgeSearchItem[];
  retrieval_mode: string;
  degraded: boolean;
}

export interface KnowledgeQueryInput extends KnowledgeFilters {
  question: string;
}

export interface KnowledgeQueryResult {
  answer: string;
  citations: DocumentCitation[];
  retrieval_mode: string;
  degraded: boolean;
  warnings: string[];
}

export type TransactionDraftStatus =
  | "pending_review"
  | "confirmed"
  | "cancelled"
  | "failed";

export interface DocumentTransactionDraftItem {
  id: string | null;
  transaction_type: string;
  account_id: string | null;
  account_name: string | null;
  instrument_id: string | null;
  instrument_name: string | null;
  instrument_symbol: string | null;
  quantity: string | null;
  price: string | null;
  amount: string | null;
  currency: string;
  fee: string | null;
  trade_date: string | null;
  note: string | null;
  confidence: number | null;
  page_number: number | null;
  citation: string | null;
}

export interface DocumentTransactionDraft {
  id: string;
  document_id: string;
  extraction_id: string;
  status: TransactionDraftStatus;
  items: DocumentTransactionDraftItem[];
  warnings: string[];
  created_at: string;
  resolved_at: string | null;
}
