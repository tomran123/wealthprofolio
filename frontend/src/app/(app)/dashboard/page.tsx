"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock3, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  ChartSkeleton,
  InlineLoading,
  ListSkeleton,
} from "@/components/loading-state";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatMoney, formatPercent } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { AggregateResponse, PortfolioSummary, PriceRefreshResult, ValuationSnapshotPage } from "@/lib/types";

const COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

export default function DashboardPage() {
  const { t, locale } = useI18n();
  const queryClient = useQueryClient();

  const summaryQuery = useQuery({
    queryKey: ["portfolio", "summary"],
    queryFn: () => api.get<PortfolioSummary>("/api/portfolio/summary"),
  });

  const byAssetClass = useQuery({
    queryKey: ["portfolio", "aggregate", "asset_class"],
    queryFn: () => api.get<AggregateResponse>("/api/portfolio/aggregate?dimension=asset_class"),
  });

  const byInstrument = useQuery({
    queryKey: ["portfolio", "aggregate", "instrument"],
    queryFn: () => api.get<AggregateResponse>("/api/portfolio/aggregate?dimension=instrument"),
  });

  const snapshotsQuery = useQuery({
    queryKey: ["portfolio", "snapshots"],
    queryFn: () => api.get<ValuationSnapshotPage>("/api/portfolio/snapshots?limit=180"),
  });

  const refreshMutation = useMutation({
    mutationFn: () => api.post<PriceRefreshResult>("/api/portfolio/refresh"),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      const message =
        locale === "zh"
          ? `成功更新 ${result.success_count} 项 · 保持原价 ${result.kept_count} 项 · 失败 ${result.failed_count} 项`
          : `Updated ${result.success_count} · kept ${result.kept_count} · failed ${result.failed_count}`;
      if (result.failed_count > 0 || result.fx_error) toast.warning(message);
      else toast.success(message);
    },
    onError: () => toast.error(t("common.error")),
  });

  const summary = summaryQuery.data;
  const baseCurrency = summary?.base_currency ?? "USD";
  const latestSnapshot = snapshotsQuery.data?.items[0];
  const historyData = [...(snapshotsQuery.data?.items ?? [])].reverse().map((snapshot) => ({
    at: snapshot.created_at,
    netWorth: Number(snapshot.net_worth),
  }));
  const portfolioIsRefreshing =
    refreshMutation.isPending ||
    (refreshMutation.submittedAt > 0 &&
      [
        summaryQuery,
        byAssetClass,
        byInstrument,
        snapshotsQuery,
      ].some((query) => query.isFetching));
  const loadingLabel =
    locale === "zh" ? "正在加载资产数据" : "Loading portfolio data";

  return (
    <div
      className="space-y-6"
      aria-busy={
        summaryQuery.isLoading ||
        byAssetClass.isLoading ||
        byInstrument.isLoading ||
        snapshotsQuery.isLoading
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{locale === "zh" ? "家庭资产总览" : "Portfolio Dashboard"}</h1>
          <div className="mt-1 flex items-center gap-1 text-sm text-muted-foreground">
            <Clock3 className="h-3.5 w-3.5" />
            {t("dashboard.last_refresh")}: {latestSnapshot ? new Date(latestSnapshot.created_at).toLocaleString() : "-"}
          </div>
        </div>
        <Button
          onClick={() => refreshMutation.mutate()}
          disabled={portfolioIsRefreshing}
          aria-busy={portfolioIsRefreshing}
        >
          <RefreshCw
            aria-hidden="true"
            className={`h-4 w-4 ${portfolioIsRefreshing ? "animate-spin motion-reduce:animate-none" : ""}`}
          />
          {portfolioIsRefreshing
            ? t("dashboard.refreshing")
            : t("dashboard.refresh")}
        </Button>
      </div>

      {portfolioIsRefreshing && (
        <InlineLoading
          label={
            locale === "zh"
              ? "正在获取最新价格并更新总览…"
              : "Fetching latest prices and updating the dashboard…"
          }
          className="border-primary/20 bg-primary/5 text-foreground"
        />
      )}

      <div
        className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4"
        aria-label={summaryQuery.isLoading ? loadingLabel : undefined}
      >
        <SummaryCard label={t("dashboard.total_assets")} value={summary && formatMoney(summary.total_assets, baseCurrency)} />
        <SummaryCard
          label={t("dashboard.total_liabilities")}
          value={summary && formatMoney(summary.total_liabilities, baseCurrency)}
        />
        <SummaryCard
          label={t("dashboard.net_worth")}
          value={summary && formatMoney(summary.net_worth, baseCurrency)}
          highlight
        />
        <SummaryCard label={t("dashboard.base_currency")} value={summary?.base_currency} />
      </div>

      {summary && (summary.missing_price_count > 0 || summary.missing_fx_count > 0) && (
        <Card className="border-amber-400">
          <CardContent className="pt-6 text-sm text-amber-700">
            {t("dashboard.missing_price")}: {summary.missing_price_count} · {t("dashboard.missing_fx")}:{" "}
            {summary.missing_fx_count}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card aria-busy={byAssetClass.isLoading}>
          <CardHeader>
            <CardTitle>{t("dashboard.allocation_by_asset_class")}</CardTitle>
          </CardHeader>
          <CardContent>
            {byAssetClass.isLoading ? (
              <ChartSkeleton
                label={
                  locale === "zh"
                    ? "正在加载资产类别分布"
                    : "Loading asset allocation"
                }
              />
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie
                    data={byAssetClass.data?.groups ?? []}
                    dataKey={(entry) => Number(entry.value_base)}
                    nameKey="label"
                    innerRadius={60}
                    outerRadius={100}
                  >
                    {(byAssetClass.data?.groups ?? []).map((entry, index) => (
                      <Cell key={entry.key} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(value) =>
                      formatMoney(typeof value === "number" || typeof value === "string" ? value : 0, baseCurrency)
                    }
                  />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            )}
          </CardContent>
        </Card>

        <Card aria-busy={byInstrument.isLoading}>
          <CardHeader>
            <CardTitle>{t("dashboard.top_holdings")}</CardTitle>
          </CardHeader>
          <CardContent>
            {byInstrument.isLoading ? (
              <ListSkeleton
                rows={6}
                compact
                label={
                  locale === "zh"
                    ? "正在加载主要持仓"
                    : "Loading top holdings"
                }
              />
            ) : (
              <div className="space-y-2">
                {(byInstrument.data?.groups ?? []).slice(0, 10).map((group) => (
                  <div key={group.key} className="flex items-center justify-between border-b pb-2 text-sm last:border-0">
                    <div>
                      <div className="font-medium">{group.label}</div>
                      <div className="text-xs text-muted-foreground">
                        {group.holdings_count} {t("assets.accounts_suffix")}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-medium">{formatMoney(group.value_base, baseCurrency)}</div>
                      <div className="text-xs text-muted-foreground">{formatPercent(group.percentage)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {(byInstrument.data?.liability_groups ?? []).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t("dashboard.liability_details")}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {(byInstrument.data?.liability_groups ?? []).map((group) => (
                <div key={group.key} className="flex items-center justify-between border-b pb-2 text-sm last:border-0">
                  <div>
                    <div className="font-medium">{group.label}</div>
                    <div className="text-xs text-muted-foreground">
                      {group.holdings_count} {t("assets.accounts_suffix")}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-medium">{formatMoney(group.value_base, baseCurrency)}</div>
                    <div className="text-xs text-muted-foreground">{formatPercent(group.percentage)}</div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card aria-busy={snapshotsQuery.isLoading}>
        <CardHeader>
          <CardTitle>{t("dashboard.net_worth_history")}</CardTitle>
        </CardHeader>
        <CardContent>
          {snapshotsQuery.isLoading ? (
            <ChartSkeleton
              className="h-72"
              label={
                locale === "zh"
                  ? "正在加载净资产历史"
                  : "Loading net worth history"
              }
            />
          ) : historyData.length === 0 ? (
            <div className="flex h-72 items-center justify-center text-sm text-muted-foreground">
              {t("dashboard.no_history")}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={historyData} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
                <XAxis
                  dataKey="at"
                  tickFormatter={(value) => new Date(value).toLocaleDateString()}
                  minTickGap={28}
                  fontSize={12}
                />
                <YAxis
                  width={72}
                  tickFormatter={(value) => Intl.NumberFormat(locale === "zh" ? "zh-CN" : "en-US", { notation: "compact" }).format(value)}
                  fontSize={12}
                />
                <Tooltip
                  labelFormatter={(value) => new Date(String(value ?? "")).toLocaleString()}
                  formatter={(value) => [formatMoney(typeof value === "number" ? value : 0, baseCurrency), t("dashboard.net_worth")]}
                />
                <Line type="monotone" dataKey="netWorth" stroke="#2563eb" strokeWidth={2.5} dot={historyData.length < 20} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryCard({ label, value, highlight }: { label: string; value?: string | null; highlight?: boolean }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="text-sm text-muted-foreground">{label}</div>
        <div className={`mt-1 text-2xl font-semibold ${highlight ? "text-primary" : ""}`}>
          {value ?? <Skeleton className="h-8 w-24" />}
        </div>
      </CardContent>
    </Card>
  );
}
