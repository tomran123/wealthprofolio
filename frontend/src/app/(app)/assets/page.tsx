"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";

import { LoadingSpinner, TableSkeleton } from "@/components/loading-state";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { formatMoney, formatNumber, formatPercent } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import type { AggregateResponse } from "@/lib/types";

const DIMENSIONS = [
  "instrument",
  "account",
  "institution",
  "owner",
  "asset_class",
  "currency",
  "country",
  "exposure_group",
] as const;

type Dimension = (typeof DIMENSIONS)[number];
type PortfolioView = "assets" | "liabilities";

export default function AssetsPage() {
  const { t } = useI18n();
  const [view, setView] = useState<PortfolioView>("assets");
  const [dimension, setDimension] = useState<Dimension>("instrument");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const query = useQuery({
    queryKey: ["portfolio", "aggregate", dimension],
    queryFn: () => api.get<AggregateResponse>(`/api/portfolio/aggregate?dimension=${dimension}`),
  });

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const baseCurrency = query.data?.base_currency ?? "USD";
  const groups =
    view === "assets"
      ? (query.data?.groups ?? [])
      : (query.data?.liability_groups ?? []);
  const totalValue =
    view === "assets"
      ? query.data?.total_value
      : query.data?.total_liabilities;

  return (
    <div className="space-y-4" aria-busy={query.isLoading}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          value={view}
          onValueChange={(value) => {
            setView(value as PortfolioView);
            setExpanded(new Set());
          }}
        >
          <TabsList>
            <TabsTrigger value="assets">
              {t("assets.view.assets")}
            </TabsTrigger>
            <TabsTrigger value="liabilities">
              {t("assets.view.liabilities")}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-3">
          {totalValue !== undefined && (
            <div className="text-sm text-muted-foreground">
              {view === "assets"
                ? t("dashboard.total_assets")
                : t("dashboard.total_liabilities")}
              <span className="ml-2 font-semibold text-foreground">
                {formatMoney(totalValue, baseCurrency)}
              </span>
            </div>
          )}
          {query.isFetching && query.data && (
            <LoadingSpinner
              label={t("common.loading")}
              showLabel
              className="text-xs text-muted-foreground"
            />
          )}
        </div>
      </div>

      <Tabs
        value={dimension}
        onValueChange={(value) => {
          setDimension(value as Dimension);
          setExpanded(new Set());
        }}
      >
          <TabsList className="h-auto flex-wrap">
            {DIMENSIONS.map((dim) => (
              <TabsTrigger key={dim} value={dim}>
                {t(`assets.dimension.${dim}`)}
              </TabsTrigger>
            ))}
          </TabsList>
      </Tabs>

      <Card aria-busy={query.isLoading}>
        <CardContent className="pt-6">
          {query.isLoading ? (
            <TableSkeleton
              columns={5}
              rows={7}
              label={t("common.loading")}
            />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>{t(`assets.dimension.${dimension}`)}</TableHead>
                  <TableHead className="text-right">
                    {view === "assets"
                      ? t("assets.total_value")
                      : t("assets.liability_value")}
                  </TableHead>
                  <TableHead className="text-right">{t("assets.percentage")}</TableHead>
                  <TableHead className="text-right">{t("assets.holdings_count")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.map((group) => (
                  <Fragment key={group.key}>
                    <TableRow className="cursor-pointer hover:bg-muted/50" onClick={() => toggle(group.key)}>
                      <TableCell>
                        {expanded.has(group.key) ? (
                          <ChevronDown className="h-4 w-4" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </TableCell>
                      <TableCell className="font-medium">{group.label}</TableCell>
                      <TableCell className="text-right">{formatMoney(group.value_base, baseCurrency)}</TableCell>
                      <TableCell className="text-right">{formatPercent(group.percentage)}</TableCell>
                      <TableCell className="text-right">{group.holdings_count}</TableCell>
                    </TableRow>
                    {expanded.has(group.key) &&
                      group.details.map((detail, i) => {
                        const stale = detail.price_as_of
                          ? Date.now() - new Date(detail.price_as_of).getTime() > 24 * 60 * 60 * 1000
                          : false;
                        return (
                          <TableRow key={`${group.key}-${i}`} className="bg-muted/30 text-sm">
                            <TableCell />
                            <TableCell className="text-muted-foreground">
                              {detail.institution_name} · {detail.account_name} ({detail.owner_name})
                            </TableCell>
                            <TableCell className="text-right">{formatMoney(detail.value_base, baseCurrency)}</TableCell>
                            <TableCell className="text-right text-muted-foreground" colSpan={2}>
                              <div className="flex flex-wrap items-center justify-end gap-2">
                                <span>
                                  {formatNumber(
                                    view === "liabilities"
                                      ? Math.abs(Number(detail.quantity))
                                      : detail.quantity,
                                  )}{" "}
                                  {detail.instrument_symbol ?? ""}
                                </span>
                                {detail.quote_status && (
                                  <QuoteBadge status={detail.quote_status} label={t(`assets.quote.${detail.quote_status}`)} />
                                )}
                                {detail.price_as_of && <span>{new Date(detail.price_as_of).toLocaleString()}</span>}
                                {stale && (
                                  <span className="inline-flex items-center gap-1 text-amber-600" title={t("assets.stale")}>
                                    <AlertTriangle className="h-3.5 w-3.5" />
                                    {t("assets.stale")}
                                  </span>
                                )}
                              </div>
                            </TableCell>
                          </TableRow>
                        );
                      })}
                  </Fragment>
                ))}
                {groups.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                      {view === "assets"
                        ? t("assets.empty_assets")
                        : t("assets.empty_liabilities")}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function QuoteBadge({ status, label }: { status: string; label: string }) {
  const className =
    status === "realtime"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : status === "delayed"
        ? "border-amber-200 bg-amber-50 text-amber-700"
        : status === "manual"
          ? "border-orange-200 bg-orange-50 text-orange-700"
          : "";
  return (
    <Badge variant={status === "close" || status === "fixed" ? "secondary" : "outline"} className={className}>
      {label}
    </Badge>
  );
}
