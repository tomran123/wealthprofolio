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
export type MarketRegion = "US" | "HK" | "CN" | "CRYPTO" | "COMMODITY" | "OTHER";
export type PriceSourceType = "market" | "manual" | "fx_derived" | "fixed_principal";
export type HoldingSource = "manual" | "import" | "agent" | "screenshot";

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
