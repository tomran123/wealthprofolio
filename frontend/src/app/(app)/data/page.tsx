"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ImportBatch } from "@/lib/types";

export default function DataManagementPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [batch, setBatch] = useState<ImportBatch | null>(null);

  const previewMutation = useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return api.post<ImportBatch>("/api/data/import", formData);
    },
    onSuccess: (data) => setBatch(data),
    onError: () => toast.error(t("common.error")),
  });

  const commitMutation = useMutation({
    mutationFn: () => api.post<ImportBatch>(`/api/data/import/${batch?.id}/commit`),
    onSuccess: (data) => {
      setBatch(data);
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["accounts"] });
      queryClient.invalidateQueries({ queryKey: ["owners"] });
      queryClient.invalidateQueries({ queryKey: ["institutions"] });
      queryClient.invalidateQueries({ queryKey: ["instruments"] });
      toast.success(t("data.committed"));
    },
    onError: () => toast.error(t("data.commit_error")),
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) previewMutation.mutate(file);
    e.target.value = "";
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("data.import_title")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-3">
            <Button
              variant="outline"
              render={<a href="/api/data/import/template">{t("data.download_template")}</a>}
            />
            <Button onClick={() => fileInputRef.current?.click()} disabled={previewMutation.isPending}>
              {previewMutation.isPending ? t("data.uploading") : t("data.upload_file")}
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              className="hidden"
              onChange={handleFileChange}
            />
          </div>

          {batch && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label={t("data.rows")} value={batch.row_count} />
                <Stat label={t("data.matched")} value={batch.matched_count} />
                <Stat label={t("data.created")} value={batch.created_count} />
                <Stat label={t("data.errors")} value={batch.error_count} />
              </div>

              <div className="max-h-96 overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("data.row_index")}</TableHead>
                      <TableHead>{t("data.account")}</TableHead>
                      <TableHead>{t("data.instrument")}</TableHead>
                      <TableHead>{t("accounts.quantity")}</TableHead>
                      <TableHead>{t("data.errors")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {batch.rows.map((row) => (
                      <TableRow key={row.row_index} className={row.errors.length > 0 ? "bg-destructive/10" : undefined}>
                        <TableCell>{row.row_index + 1}</TableCell>
                        <TableCell>{row.account_name}</TableCell>
                        <TableCell>
                          {row.ticker ? `${row.ticker} · ` : ""}
                          {row.instrument_name}
                          {row.instrument_id ? (
                            <Badge variant="secondary" className="ml-2">
                              matched
                            </Badge>
                          ) : (
                            <Badge variant="outline" className="ml-2">
                              new
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>{row.quantity ?? "-"}</TableCell>
                        <TableCell className="text-destructive">{row.errors.join(", ")}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {batch.status === "pending" ? (
                <Button onClick={() => commitMutation.mutate()} disabled={commitMutation.isPending}>
                  {t("data.commit")}
                </Button>
              ) : (
                <Badge>{t("data.committed")}</Badge>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-xl font-semibold">{value}</div>
    </div>
  );
}
