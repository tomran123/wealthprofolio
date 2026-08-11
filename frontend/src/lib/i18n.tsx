"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
} from "react";

export type Locale = "zh" | "en";

const STORAGE_KEY = "wp_locale";
const listeners = new Set<() => void>();

function getSnapshot(): Locale {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return stored === "en" ? "en" : "zh";
}

function getServerSnapshot(): Locale {
  return "zh";
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function setStoredLocale(next: Locale) {
  window.localStorage.setItem(STORAGE_KEY, next);
  listeners.forEach((listener) => listener());
}

const dictionaries: Record<Locale, Record<string, string>> = {
  zh: {
    "nav.dashboard": "总览",
    "nav.assets": "资产",
    "nav.accounts": "账户",
    "nav.transactions": "交易",
    "nav.documents": "文档",
    "nav.agent": "AI Agent",
    "nav.data": "数据管理",
    "nav.logout": "退出登录",

    "login.title": "家庭资产管理",
    "login.subtitle": "请登录以继续",
    "login.username": "用户名",
    "login.password": "密码",
    "login.submit": "登录",
    "login.required": "此项为必填",
    "login.error": "用户名或密码错误",
    "login.rate_limited": "尝试次数过多，请稍后再试",

    "common.loading": "加载中…",
    "common.save": "保存",
    "common.cancel": "取消",
    "common.delete": "删除",
    "common.edit": "编辑",
    "common.confirm": "确认",
    "common.saved": "已保存",
    "common.error": "操作失败",
    "common.close": "关闭",

    "dashboard.total_assets": "总资产",
    "dashboard.total_liabilities": "总负债",
    "dashboard.net_worth": "净资产",
    "dashboard.base_currency": "基准币种",
    "dashboard.holdings_count": "持仓数",
    "dashboard.missing_price": "缺少价格",
    "dashboard.missing_fx": "缺少汇率",
    "dashboard.allocation_by_asset_class": "按资产类别占比",
    "dashboard.top_holdings": "重点持仓（按产品）",
    "dashboard.liability_details": "负债明细",
    "dashboard.refresh": "刷新全部价格",
    "dashboard.refreshing": "刷新中…",
    "dashboard.last_refresh": "最后刷新",
    "dashboard.net_worth_history": "净资产历史",
    "dashboard.no_history": "刷新价格后将开始积累净资产历史",

    "assets.dimension.instrument": "产品",
    "assets.dimension.account": "账户",
    "assets.dimension.institution": "机构",
    "assets.dimension.owner": "持有人",
    "assets.dimension.asset_class": "资产类别",
    "assets.dimension.currency": "币种",
    "assets.dimension.country": "国家",
    "assets.dimension.exposure_group": "底层敞口",
    "assets.view.assets": "资产",
    "assets.view.liabilities": "负债",
    "assets.total_value": "总市值",
    "assets.liability_value": "负债金额",
    "assets.percentage": "占比",
    "assets.holdings_count": "分布账户数",
    "assets.empty_assets": "暂无资产",
    "assets.empty_liabilities": "暂无负债",
    "assets.accounts_suffix": "个账户",
    "assets.quote.realtime": "实时",
    "assets.quote.delayed": "延迟",
    "assets.quote.close": "收盘价",
    "assets.quote.manual": "人工估值",
    "assets.quote.fixed": "固定",
    "assets.stale": "价格已超过 24 小时",

    "accounts.tab_accounts": "账户",
    "accounts.tab_institutions": "机构",
    "accounts.tab_owners": "持有人",
    "accounts.add_account": "新增账户",
    "accounts.add_institution": "新增机构",
    "accounts.add_owner": "新增持有人",
    "accounts.name": "名称",
    "accounts.institution": "机构",
    "accounts.owner": "持有人",
    "accounts.type": "类型",
    "accounts.country": "国家/地区",
    "accounts.base_currency": "账户币种",
    "accounts.select_institution": "选择机构",
    "accounts.select_owner": "选择持有人",
    "accounts.no_holdings": "该账户暂无持仓",
    "accounts.add_holding": "添加持仓",
    "accounts.instrument": "产品",
    "accounts.select_instrument": "选择产品",
    "accounts.create_new_instrument": "找不到？新建产品",
    "accounts.quantity": "数量",
    "accounts.currency": "币种",
    "accounts.asset_class": "资产类别",
    "accounts.symbol": "代码（可选）",
    "accounts.set_price": "设置价格",
    "accounts.price": "价格",
    "accounts.market_value": "市值",
    "accounts.price_unavailable": "暂无有效价格",
    "accounts.note": "备注（可选）",
    "accounts.market_search_description":
      "搜索并选择公开交易产品；名称、代码、市场、币种和类别由行情源自动识别。",
    "accounts.manual_description":
      "仅用于房产、私募股权等无法从公开市场检索的资产。",
    "accounts.search_market_instrument": "搜索产品",
    "accounts.market_search_placeholder":
      "输入代码或名称，例如 AAPL、腾讯、沪深300、BTC",
    "accounts.market_search_examples":
      "支持全球股票、ETF、基金、债券、期货和加密资产。",
    "accounts.searching": "正在搜索多个市场…",
    "accounts.search_failed": "搜索服务暂时不可用，请稍后重试。",
    "accounts.no_market_results": "没有找到匹配产品，请检查名称或代码。",
    "accounts.search_partial_unavailable":
      "部分行情源暂时不可用，以下结果可能不完整",
    "accounts.market_quantity": "持有数量（股 / 份 / 枚）",
    "accounts.auto_price_notice":
      "保存时会再次验证产品并获取有效价格，然后自动计算市值；取价失败不会创建 0 价格持仓。",
    "accounts.add_manual_asset": "添加无法公开检索的非上市资产",
    "accounts.back_to_market_search": "返回公开市场产品搜索",
    "accounts.fetching_price": "正在验证并取价…",

    "data.import_title": "Excel / CSV 导入",
    "data.download_template": "下载模板",
    "data.upload_file": "上传文件",
    "data.uploading": "解析中…",
    "data.preview_summary": "预览结果",
    "data.rows": "总行数",
    "data.matched": "已匹配",
    "data.created": "将新建",
    "data.errors": "错误行",
    "data.commit": "确认导入",
    "data.committed": "导入完成",
    "data.commit_error": "导入失败",
    "data.row_index": "行号",
    "data.instrument": "产品",
    "data.account": "账户",
  },
  en: {
    "nav.dashboard": "Dashboard",
    "nav.assets": "Assets",
    "nav.accounts": "Accounts",
    "nav.transactions": "Transactions",
    "nav.documents": "Documents",
    "nav.agent": "AI Agent",
    "nav.data": "Data Management",
    "nav.logout": "Log out",

    "login.title": "Family Wealth Manager",
    "login.subtitle": "Sign in to continue",
    "login.username": "Username",
    "login.password": "Password",
    "login.submit": "Sign in",
    "login.required": "This field is required",
    "login.error": "Invalid username or password",
    "login.rate_limited": "Too many attempts, please try again later",

    "common.loading": "Loading…",
    "common.save": "Save",
    "common.cancel": "Cancel",
    "common.delete": "Delete",
    "common.edit": "Edit",
    "common.confirm": "Confirm",
    "common.saved": "Saved",
    "common.error": "Something went wrong",
    "common.close": "Close",

    "dashboard.total_assets": "Total Assets",
    "dashboard.total_liabilities": "Total Liabilities",
    "dashboard.net_worth": "Net Worth",
    "dashboard.base_currency": "Base Currency",
    "dashboard.holdings_count": "Holdings",
    "dashboard.missing_price": "Missing price",
    "dashboard.missing_fx": "Missing FX rate",
    "dashboard.allocation_by_asset_class": "Allocation by Asset Class",
    "dashboard.top_holdings": "Top Holdings (by product)",
    "dashboard.liability_details": "Liability Details",
    "dashboard.refresh": "Refresh All Prices",
    "dashboard.refreshing": "Refreshing…",
    "dashboard.last_refresh": "Last refresh",
    "dashboard.net_worth_history": "Net Worth History",
    "dashboard.no_history":
      "Refresh prices to begin building net worth history",

    "assets.dimension.instrument": "Product",
    "assets.dimension.account": "Account",
    "assets.dimension.institution": "Institution",
    "assets.dimension.owner": "Owner",
    "assets.dimension.asset_class": "Asset Class",
    "assets.dimension.currency": "Currency",
    "assets.dimension.country": "Country",
    "assets.dimension.exposure_group": "Underlying Exposure",
    "assets.view.assets": "Assets",
    "assets.view.liabilities": "Liabilities",
    "assets.total_value": "Total Value",
    "assets.liability_value": "Liability Amount",
    "assets.percentage": "% of Total",
    "assets.holdings_count": "# Accounts",
    "assets.empty_assets": "No assets",
    "assets.empty_liabilities": "No liabilities",
    "assets.accounts_suffix": "accounts",
    "assets.quote.realtime": "Real-time",
    "assets.quote.delayed": "Delayed",
    "assets.quote.close": "Close",
    "assets.quote.manual": "Manual",
    "assets.quote.fixed": "Fixed",
    "assets.stale": "Price is older than 24 hours",

    "accounts.tab_accounts": "Accounts",
    "accounts.tab_institutions": "Institutions",
    "accounts.tab_owners": "Owners",
    "accounts.add_account": "Add Account",
    "accounts.add_institution": "Add Institution",
    "accounts.add_owner": "Add Owner",
    "accounts.name": "Name",
    "accounts.institution": "Institution",
    "accounts.owner": "Owner",
    "accounts.type": "Type",
    "accounts.country": "Country",
    "accounts.base_currency": "Account Currency",
    "accounts.select_institution": "Select institution",
    "accounts.select_owner": "Select owner",
    "accounts.no_holdings": "No holdings in this account yet",
    "accounts.add_holding": "Add Holding",
    "accounts.instrument": "Instrument",
    "accounts.select_instrument": "Select instrument",
    "accounts.create_new_instrument": "Can't find it? Create new",
    "accounts.quantity": "Quantity",
    "accounts.currency": "Currency",
    "accounts.asset_class": "Asset Class",
    "accounts.symbol": "Symbol (optional)",
    "accounts.set_price": "Set Price",
    "accounts.price": "Price",
    "accounts.market_value": "Market value",
    "accounts.price_unavailable": "No valid price yet",
    "accounts.note": "Note (optional)",
    "accounts.market_search_description":
      "Search and select a publicly traded product. Name, symbol, market, currency, and type come from market data.",
    "accounts.manual_description":
      "Use this only for property, private equity, and other assets unavailable on public markets.",
    "accounts.search_market_instrument": "Search instruments",
    "accounts.market_search_placeholder":
      "Enter a symbol or name, e.g. AAPL, Tencent, CSI 300, BTC",
    "accounts.market_search_examples":
      "Search global stocks, ETFs, funds, bonds, futures, and crypto assets.",
    "accounts.searching": "Searching multiple markets…",
    "accounts.search_failed":
      "Search is temporarily unavailable. Please try again later.",
    "accounts.no_market_results":
      "No matching product found. Check its name or symbol.",
    "accounts.search_partial_unavailable":
      "Some market sources are unavailable, so results may be incomplete",
    "accounts.market_quantity": "Quantity (shares / units / coins)",
    "accounts.auto_price_notice":
      "On save, the product is verified and a valid quote is fetched to calculate market value. A zero-price holding is never created.",
    "accounts.add_manual_asset": "Add a non-listed asset unavailable in search",
    "accounts.back_to_market_search": "Back to public market search",
    "accounts.fetching_price": "Verifying and fetching price…",

    "data.import_title": "Excel / CSV Import",
    "data.download_template": "Download Template",
    "data.upload_file": "Upload File",
    "data.uploading": "Parsing…",
    "data.preview_summary": "Preview Summary",
    "data.rows": "Total Rows",
    "data.matched": "Matched",
    "data.created": "To Create",
    "data.errors": "Error Rows",
    "data.commit": "Confirm Import",
    "data.committed": "Import complete",
    "data.commit_error": "Import failed",
    "data.row_index": "Row",
    "data.instrument": "Instrument",
    "data.account": "Account",
  },
};

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const locale = useSyncExternalStore(
    subscribe,
    getSnapshot,
    getServerSnapshot,
  );

  const setLocale = useCallback((next: Locale) => {
    setStoredLocale(next);
  }, []);

  const t = useMemo(() => {
    const dict = dictionaries[locale];
    return (key: string) => dict[key] ?? key;
  }, [locale]);

  const value = useMemo(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return ctx;
}
