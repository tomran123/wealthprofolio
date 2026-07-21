"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
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

export default function AssetsPage() {
  const { t } = useI18n();
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

  return (
    <div className="space-y-4">
      <Tabs value={dimension} onValueChange={(v) => setDimension(v as Dimension)}>
        <TabsList className="h-auto flex-wrap">
          {DIMENSIONS.map((dim) => (
            <TabsTrigger key={dim} value={dim}>
              {t(`assets.dimension.${dim}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <Card>
        <CardContent className="pt-6">
          {query.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>{t(`assets.dimension.${dimension}`)}</TableHead>
                  <TableHead className="text-right">{t("assets.total_value")}</TableHead>
                  <TableHead className="text-right">{t("assets.percentage")}</TableHead>
                  <TableHead className="text-right">{t("assets.holdings_count")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(query.data?.groups ?? []).map((group) => (
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
                      group.details.map((detail, i) => (
                        <TableRow key={`${group.key}-${i}`} className="bg-muted/30 text-sm">
                          <TableCell />
                          <TableCell className="text-muted-foreground">
                            {detail.institution_name} · {detail.account_name} ({detail.owner_name})
                          </TableCell>
                          <TableCell className="text-right">{formatMoney(detail.value_base, baseCurrency)}</TableCell>
                          <TableCell className="text-right text-muted-foreground" colSpan={2}>
                            {formatNumber(detail.quantity)} {detail.instrument_symbol ?? ""}
                            {detail.quote_status ? ` · ${detail.quote_status}` : ""}
                          </TableCell>
                        </TableRow>
                      ))}
                  </Fragment>
                ))}
                {(query.data?.groups ?? []).length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                      -
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
