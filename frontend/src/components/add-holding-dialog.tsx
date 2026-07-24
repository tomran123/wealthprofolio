"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, Loader2, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  ListSkeleton,
  LoadingSpinner,
} from "@/components/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api, ApiError } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type {
  AssetClass,
  Instrument,
  MarketHoldingCreateResult,
  MarketInstrumentSearchItem,
  MarketInstrumentSearchResponse,
} from "@/lib/types";

const MANUAL_ASSET_CLASSES: AssetClass[] = [
  "real_estate",
  "private_equity",
  "company_equity",
  "custom",
  "liability",
];

type AddMode = "market" | "manual";

const initialManualInstrument = {
  name: "",
  asset_class: "real_estate" as AssetClass,
  currency: "USD",
};

export function AddHoldingDialog({ accountId }: { accountId: string }) {
  const { t, locale } = useI18n();
  const zh = locale === "zh";
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<AddMode>("market");
  const [searchText, setSearchText] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selected, setSelected] = useState<MarketInstrumentSearchItem | null>(
    null,
  );
  const [quantity, setQuantity] = useState("");
  const [manualInstrument, setManualInstrument] = useState(
    initialManualInstrument,
  );

  useEffect(() => {
    const timeout = window.setTimeout(
      () => setDebouncedSearch(searchText.trim()),
      400,
    );
    return () => window.clearTimeout(timeout);
  }, [searchText]);

  const searchQuery = useQuery({
    queryKey: ["market-instruments", "search", debouncedSearch],
    queryFn: () =>
      api.get<MarketInstrumentSearchResponse>(
        `/api/instruments/market-search?q=${encodeURIComponent(debouncedSearch)}`,
      ),
    enabled: open && mode === "market" && debouncedSearch.length > 0,
    staleTime: 5 * 60 * 1000,
    retry: 0,
  });

  const reset = () => {
    setMode("market");
    setSearchText("");
    setDebouncedSearch("");
    setSelected(null);
    setQuantity("");
    setManualInstrument(initialManualInstrument);
  };

  const mutation = useMutation({
    mutationFn: async (): Promise<MarketHoldingCreateResult | null> => {
      if (mode === "market") {
        if (!selected) throw new Error("market_instrument_required");
        return api.post<MarketHoldingCreateResult>(
          "/api/holdings/from-market-search",
          {
            account_id: accountId,
            selection_token: selected.selection_token,
            quantity,
          },
        );
      }

      const created = await api.post<Instrument>("/api/instruments", {
        name: manualInstrument.name.trim(),
        symbol: null,
        asset_class: manualInstrument.asset_class,
        currency: manualInstrument.currency.toUpperCase(),
        price_source_type: "manual",
      });
      await api.put("/api/holdings", {
        account_id: accountId,
        instrument_id: created.id,
        quantity,
      });
      return null;
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({
        queryKey: ["accounts", accountId, "holdings"],
      });
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["instruments"] });
      if (result) {
        const symbol =
          result.holding.instrument_symbol ?? result.holding.instrument_name;
        toast.success(
          zh
            ? `${symbol} 已添加 · 最新价 ${formatMoney(result.price, result.currency)} · 市值 ${formatMoney(result.market_value, result.currency)}`
            : `${symbol} added · latest ${formatMoney(result.price, result.currency)} · value ${formatMoney(result.market_value, result.currency)}`,
        );
      } else {
        toast.success(t("common.saved"));
      }
      setOpen(false);
      reset();
    },
    onError: (error) =>
      toast.error(marketErrorMessage(error, zh, t("common.error"))),
  });

  const validQuantity = quantity.trim() !== "" && Number(quantity) > 0;
  const canSubmit =
    validQuantity &&
    (mode === "market"
      ? selected !== null
      : manualInstrument.name.trim() !== "" &&
        manualInstrument.currency.trim().length === 3);
  const searchIsDebouncing = searchText.trim() !== debouncedSearch;
  const visibleSearchResponse = searchIsDebouncing
    ? undefined
    : searchQuery.data;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger
        render={
          <Button size="sm" variant="outline">
            {t("accounts.add_holding")}
          </Button>
        }
      />
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("accounts.add_holding")}</DialogTitle>
          <DialogDescription>
            {mode === "market"
              ? t("accounts.market_search_description")
              : t("accounts.manual_description")}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {mode === "market" ? (
            <MarketInstrumentSearch
              searchText={searchText}
              setSearchText={(value) => {
                setSearchText(value);
                setSelected(null);
              }}
              selected={selected}
              setSelected={setSelected}
              response={visibleSearchResponse}
              isLoading={searchIsDebouncing || searchQuery.isFetching}
              isError={!searchIsDebouncing && searchQuery.isError}
              zh={zh}
              t={t}
            />
          ) : (
            <div className="space-y-3 rounded-lg border p-4">
              <div className="space-y-1.5">
                <Label>{t("accounts.name")}</Label>
                <Input
                  value={manualInstrument.name}
                  onChange={(event) =>
                    setManualInstrument((old) => ({
                      ...old,
                      name: event.target.value,
                    }))
                  }
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label>{t("accounts.currency")}</Label>
                  <Input
                    maxLength={3}
                    value={manualInstrument.currency}
                    onChange={(event) =>
                      setManualInstrument((old) => ({
                        ...old,
                        currency: event.target.value.toUpperCase(),
                      }))
                    }
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>{t("accounts.asset_class")}</Label>
                  <Select
                    value={manualInstrument.asset_class}
                    onValueChange={(value) => {
                      if (value)
                        setManualInstrument((old) => ({
                          ...old,
                          asset_class: value as AssetClass,
                        }));
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {MANUAL_ASSET_CLASSES.map((assetClass) => (
                        <SelectItem key={assetClass} value={assetClass}>
                          {assetClass}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <Label>
              {mode === "market"
                ? t("accounts.market_quantity")
                : t("accounts.quantity")}
            </Label>
            <Input
              type="number"
              min="0"
              step="any"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              inputMode="decimal"
            />
          </div>

          {mode === "market" && (
            <div className="flex items-start gap-2 rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-600" />
              <span>{t("accounts.auto_price_notice")}</span>
            </div>
          )}

          <button
            type="button"
            className="text-xs text-muted-foreground underline underline-offset-4"
            onClick={() => {
              setMode(mode === "market" ? "manual" : "market");
              setSelected(null);
            }}
          >
            {mode === "market"
              ? t("accounts.add_manual_asset")
              : t("accounts.back_to_market_search")}
          </button>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            disabled={!canSubmit || mutation.isPending}
            aria-busy={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {mutation.isPending && (
              <LoadingSpinner
                label={
                  mode === "market"
                    ? t("accounts.fetching_price")
                    : t("common.loading")
                }
              />
            )}
            {mutation.isPending
              ? mode === "market"
                ? t("accounts.fetching_price")
                : t("common.loading")
              : t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MarketInstrumentSearch({
  searchText,
  setSearchText,
  selected,
  setSelected,
  response,
  isLoading,
  isError,
  zh,
  t,
}: {
  searchText: string;
  setSearchText: (value: string) => void;
  selected: MarketInstrumentSearchItem | null;
  setSelected: (value: MarketInstrumentSearchItem) => void;
  response?: MarketInstrumentSearchResponse;
  isLoading: boolean;
  isError: boolean;
  zh: boolean;
  t: (key: string) => string;
}) {
  return (
    <div className="space-y-2" aria-busy={isLoading}>
      <Label htmlFor="market-instrument-search">
        {t("accounts.search_market_instrument")}
      </Label>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          id="market-instrument-search"
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          placeholder={t("accounts.market_search_placeholder")}
          className="pl-9 pr-9"
          autoComplete="off"
        />
        {isLoading && (
          <Loader2
            aria-hidden="true"
            className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground motion-reduce:animate-none"
          />
        )}
      </div>

      {selected ? (
        <div className="flex w-full items-center justify-between gap-3 rounded-lg border border-primary bg-primary/5 p-3">
          <InstrumentIdentity item={selected} zh={zh} />
          <Check className="h-5 w-5 shrink-0 text-primary" />
        </div>
      ) : (
        <SearchResults
          searchText={searchText}
          response={response}
          isLoading={isLoading}
          isError={isError}
          zh={zh}
          t={t}
          setSelected={setSelected}
        />
      )}

      {(response?.unavailable_sources.length ?? 0) > 0 && (
        <div className="flex items-start gap-1.5 text-xs text-amber-700">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            {t("accounts.search_partial_unavailable")} (
            {response?.unavailable_sources.join(", ")})
          </span>
        </div>
      )}
    </div>
  );
}

function SearchResults({
  searchText,
  response,
  isLoading,
  isError,
  zh,
  t,
  setSelected,
}: {
  searchText: string;
  response?: MarketInstrumentSearchResponse;
  isLoading: boolean;
  isError: boolean;
  zh: boolean;
  t: (key: string) => string;
  setSelected: (value: MarketInstrumentSearchItem) => void;
}) {
  if (!searchText.trim()) {
    return (
      <p className="px-1 text-xs text-muted-foreground">
        {t("accounts.market_search_examples")}
      </p>
    );
  }
  if (isError) {
    return (
      <p className="px-1 text-sm text-destructive">
        {t("accounts.search_failed")}
      </p>
    );
  }
  if (isLoading && !response) {
    return (
      <ListSkeleton
        compact
        rows={3}
        label={t("accounts.searching")}
        className="pt-1"
      />
    );
  }
  if (response && response.items.length === 0) {
    return (
      <p className="px-1 text-sm text-muted-foreground">
        {t("accounts.no_market_results")}
      </p>
    );
  }
  if (!response) return null;

  return (
    <div className="max-h-72 overflow-y-auto rounded-lg border p-1">
      {response.items.map((item) => (
        <button
          key={item.selection_token}
          type="button"
          className="flex w-full items-center rounded-md px-3 py-2.5 text-left transition-colors hover:bg-muted"
          onClick={() => setSelected(item)}
        >
          <InstrumentIdentity item={item} zh={zh} />
        </button>
      ))}
    </div>
  );
}

function InstrumentIdentity({
  item,
  zh,
}: {
  item: MarketInstrumentSearchItem;
  zh: boolean;
}) {
  const sourceLabels: Record<string, string> = {
    local: zh ? "已录入" : "Saved",
    yahoo: "Yahoo",
    akshare: zh ? "中国市场" : "China market",
    coingecko: "CoinGecko",
  };
  return (
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{item.symbol}</span>
        <span className="truncate text-sm">{item.name}</span>
        <Badge variant="outline" className="text-[10px]">
          {sourceLabels[item.source] ?? item.source}
        </Badge>
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">
        {item.market} · {item.asset_class} · {item.currency}
        {item.exchange ? ` · ${item.exchange}` : ""}
      </div>
    </div>
  );
}

function marketErrorMessage(error: unknown, zh: boolean, fallback: string) {
  const detail =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "";
  const messages: Record<string, [string, string]> = {
    market_quote_unavailable: [
      "暂时无法取得该产品的有效价格，持仓没有保存，请稍后重试",
      "No valid quote is currently available. The holding was not saved; please try again later.",
    ],
    market_selection_expired: [
      "搜索结果已过期，请重新搜索并选择",
      "The search result expired. Search and select it again.",
    ],
    invalid_market_selection: [
      "产品选择无效，请重新搜索",
      "Invalid product selection. Please search again.",
    ],
    account_not_found: ["账户不存在", "Account not found"],
    instrument_not_found: [
      "产品已不存在，请重新搜索",
      "The instrument no longer exists. Please search again.",
    ],
  };
  return messages[detail]?.[zh ? 0 : 1] ?? fallback;
}
