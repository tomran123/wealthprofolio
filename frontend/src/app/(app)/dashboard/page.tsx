"use client";

import { useQuery } from "@tanstack/react-query";
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { formatMoney, formatPercent } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { AggregateResponse, PortfolioSummary } from "@/lib/types";

const COLORS = ["#2563eb", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

export default function DashboardPage() {
  const { t } = useI18n();

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

  const summary = summaryQuery.data;
  const baseCurrency = summary?.base_currency ?? "USD";

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
        <Card>
          <CardHeader>
            <CardTitle>{t("dashboard.allocation_by_asset_class")}</CardTitle>
          </CardHeader>
          <CardContent>
            {byAssetClass.isLoading ? (
              <Skeleton className="h-64 w-full" />
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

        <Card>
          <CardHeader>
            <CardTitle>{t("dashboard.top_holdings")}</CardTitle>
          </CardHeader>
          <CardContent>
            {byInstrument.isLoading ? (
              <Skeleton className="h-64 w-full" />
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
