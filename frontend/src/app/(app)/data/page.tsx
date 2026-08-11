"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Download,
  History,
  RotateCcw,
  ShieldCheck,
  Upload,
} from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import {
  LoadingSpinner,
  TableSkeleton,
} from "@/components/loading-state";
import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
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
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  AgentOperationLog,
  AgentOperationLogPage,
  AgentUndoResult,
  ImportBatch,
} from "@/lib/types";

export default function DataManagementPage() {
  const { t, locale } = useI18n();
  const zh = locale === "zh";
  return (
    <div className="space-y-5">
      <div><h1 className="text-2xl font-semibold">{zh ? "数据管理与恢复" : "Data Management & Recovery"}</h1><p className="text-sm text-muted-foreground">{zh ? "导入、审计、补偿冲销、导出与数据库恢复" : "Import, audit, compensating reversals, export, and restore"}</p></div>
      <Tabs defaultValue="import">
        <TabsList className="mb-4 h-auto flex-wrap"><TabsTrigger value="import"><Upload className="h-4 w-4" />{zh ? "导入" : "Import"}</TabsTrigger><TabsTrigger value="history"><History className="h-4 w-4" />{zh ? "操作历史" : "Operation history"}</TabsTrigger><TabsTrigger value="backup"><ShieldCheck className="h-4 w-4" />{zh ? "导出与恢复" : "Export & restore"}</TabsTrigger></TabsList>
        <TabsContent value="import"><ImportPanel t={t} /></TabsContent>
        <TabsContent value="history"><OperationHistory zh={zh} /></TabsContent>
        <TabsContent value="backup"><BackupPanel zh={zh} /></TabsContent>
      </Tabs>
    </div>
  );
}

function ImportPanel({ t }: { t: (key: string) => string }) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const previewMutation = useMutation({
    mutationFn: (file: File) => { const formData = new FormData(); formData.append("file", file); return api.post<ImportBatch>("/api/data/import", formData); },
    onSuccess: setBatch,
    onError: () => toast.error(t("common.error")),
  });
  const commitMutation = useMutation({
    mutationFn: () => api.post<ImportBatch>(`/api/data/import/${batch?.id}/commit`),
    onSuccess: (data) => { setBatch(data); ["portfolio", "accounts", "owners", "institutions", "instruments"].forEach((key) => queryClient.invalidateQueries({ queryKey: [key] })); toast.success(t("data.committed")); },
    onError: () => toast.error(t("data.commit_error")),
  });
  return <Card><CardHeader><CardTitle>{t("data.import_title")}</CardTitle></CardHeader><CardContent className="space-y-4">
    <div className="flex flex-wrap gap-3"><Button variant="outline" render={<a href="/api/data/import/template">{t("data.download_template")}</a>} /><Button onClick={() => fileInputRef.current?.click()} disabled={previewMutation.isPending}>{previewMutation.isPending ? t("data.uploading") : t("data.upload_file")}</Button><input ref={fileInputRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={(event) => { const file = event.target.files?.[0]; if (file) previewMutation.mutate(file); event.target.value = ""; }} /></div>
    {batch && <div className="space-y-4"><div className="grid grid-cols-2 gap-3 sm:grid-cols-4"><Stat label={t("data.rows")} value={batch.row_count} /><Stat label={t("data.matched")} value={batch.matched_count} /><Stat label={t("data.created")} value={batch.created_count} /><Stat label={t("data.errors")} value={batch.error_count} /></div>
      <div className="max-h-96 overflow-auto rounded-md border"><Table><TableHeader><TableRow><TableHead>{t("data.row_index")}</TableHead><TableHead>{t("data.account")}</TableHead><TableHead>{t("data.instrument")}</TableHead><TableHead>{t("accounts.quantity")}</TableHead><TableHead>{t("data.errors")}</TableHead></TableRow></TableHeader><TableBody>{batch.rows.map((row) => <TableRow key={row.row_index} className={row.errors.length > 0 ? "bg-destructive/10" : undefined}><TableCell>{row.row_index + 1}</TableCell><TableCell>{row.account_name}</TableCell><TableCell>{row.ticker ? `${row.ticker} · ` : ""}{row.instrument_name}<Badge variant={row.instrument_id ? "secondary" : "outline"} className="ml-2">{row.instrument_id ? "matched" : "new"}</Badge></TableCell><TableCell>{row.quantity ?? "-"}</TableCell><TableCell className="text-destructive">{row.errors.join(", ")}</TableCell></TableRow>)}</TableBody></Table></div>
      {batch.status === "pending" ? <Button onClick={() => commitMutation.mutate()} disabled={commitMutation.isPending}>{t("data.commit")}</Button> : <Badge>{t("data.committed")}</Badge>}
    </div>}
  </CardContent></Card>;
}

function OperationHistory({ zh }: { zh: boolean }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<AgentOperationLog | null>(null);
  const logsQuery = useQuery({ queryKey: ["agent", "logs"], queryFn: () => api.get<AgentOperationLogPage>("/api/agent/logs?limit=200") });
  const undoMutation = useMutation({
    mutationFn: (id: string) =>
      api.post<AgentUndoResult>(`/api/agent/logs/${id}/undo`),
    onSuccess: () => {
      setSelected(null);
      [
        "agent",
        "portfolio",
        "transactions",
        "accounts",
        "instruments",
        "owners",
        "institutions",
      ].forEach((key) =>
        queryClient.invalidateQueries({ queryKey: [key] }),
      );
      toast.success(
        zh
          ? "补偿冲销事件已创建，原始记录与审计轨迹均已保留"
          : "Compensating reversal events created; the original records and audit trail remain",
      );
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : (zh ? "撤销失败" : "Undo failed")),
  });
  return (
    <>
      <Card aria-busy={logsQuery.isLoading}>
        <CardHeader>
          <CardTitle>
            {zh ? "Agent 操作历史" : "Agent operation history"}
          </CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          {logsQuery.isLoading ? (
            <TableSkeleton
              columns={5}
              rows={7}
              label={
                zh
                  ? "正在加载 Agent 操作历史"
                  : "Loading agent operation history"
              }
              className="min-w-[720px]"
            />
          ) : logsQuery.isError ? (
            <Alert variant="destructive">
              <AlertTriangle />
              <AlertTitle>
                {zh ? "无法加载操作历史" : "Could not load operation history"}
              </AlertTitle>
              <AlertDescription>
                {logsQuery.error instanceof ApiError
                  ? logsQuery.error.message
                  : zh
                    ? "请检查网络连接后重试。"
                    : "Check your connection and try again."}
              </AlertDescription>
              <AlertAction>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void logsQuery.refetch()}
                >
                  {zh ? "重试" : "Retry"}
                </Button>
              </AlertAction>
            </Alert>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{zh ? "时间" : "Time"}</TableHead>
                  <TableHead>{zh ? "操作" : "Operation"}</TableHead>
                  <TableHead>{zh ? "用户请求" : "User request"}</TableHead>
                  <TableHead>{zh ? "变更" : "Changes"}</TableHead>
                  <TableHead className="text-right">
                    {zh ? "动作" : "Action"}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(logsQuery.data?.items ?? []).map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="whitespace-nowrap">
                      {new Date(log.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <div className="font-medium">{log.description}</div>
                      <Badge
                        variant={
                          log.operation_type === "undo"
                            ? "secondary"
                            : "outline"
                        }
                      >
                        {log.operation_type}
                      </Badge>
                      {log.is_undone && (
                        <Badge variant="secondary" className="ml-1">
                          {zh ? "已补偿" : "Compensated"}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell
                      className="max-w-80 truncate"
                      title={log.user_message}
                    >
                      {log.user_message}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <div>
                        +{log.change_summary.created} / ~
                        {log.change_summary.updated} / −
                        {log.change_summary.deleted}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {operationEventCount(log)}{" "}
                        {zh ? "个账本事件" : "ledger events"}
                        {operationResources(log).length > 0 &&
                          ` · ${operationResources(log).join(", ")}`}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      {log.is_undoable ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setSelected(log)}
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                          {zh ? "补偿冲销" : "Compensate"}
                        </Button>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {log.is_undone
                            ? zh
                              ? "已补偿"
                              : "Compensated"
                            : zh
                              ? "不可补偿"
                              : "Not compensatable"}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {(logsQuery.data?.items ?? []).length === 0 && (
                  <TableRow>
                    <TableCell
                      colSpan={5}
                      className="py-10 text-center text-muted-foreground"
                    >
                      {zh ? "暂无 Agent 操作" : "No agent operations"}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={Boolean(selected)}
        onOpenChange={(open) => !open && setSelected(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {zh ? "创建补偿冲销事件？" : "Create compensating reversals?"}
            </DialogTitle>
            <DialogDescription>
              {zh
                ? "系统不会删除或改写历史数据，而是为本次 Agent 操作追加反向账本事件。原始事件和完整审计记录会保留，并据此重新计算当前持仓与现金。非账本类增删改不会被恢复。"
                : "The system will not delete or rewrite history. It appends inverse ledger events for this agent operation, retains the originals and full audit trail, then recalculates current holdings and cash. Non-ledger CRUD is not restored."}
            </DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="rounded-lg bg-muted p-3 text-sm">
              <div className="font-medium">{selected.description}</div>
              <div className="mt-1">
                +{selected.change_summary.created} / ~
                {selected.change_summary.updated} / −
                {selected.change_summary.deleted}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {zh ? "将补偿" : "Will compensate"}{" "}
                {operationEventCount(selected)}{" "}
                {zh ? "个账本事件" : "ledger events"}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelected(null)}>
              {zh ? "取消" : "Cancel"}
            </Button>
            <Button
              onClick={() => selected && undoMutation.mutate(selected.id)}
              disabled={undoMutation.isPending || !selected?.is_undoable}
              aria-busy={undoMutation.isPending}
            >
              {undoMutation.isPending && (
                <LoadingSpinner
                  label={zh ? "正在创建冲销" : "Creating reversals"}
                />
              )}
              {undoMutation.isPending
                ? zh
                  ? "冲销中…"
                  : "Creating…"
                : zh
                  ? "确认创建冲销"
                  : "Create reversals"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function operationEventCount(log: AgentOperationLog): number {
  return typeof log.summary.event_count === "number"
    ? log.summary.event_count
    : log.event_ids.length;
}

function operationResources(log: AgentOperationLog): string[] {
  return Array.isArray(log.summary.resources)
    ? log.summary.resources.filter(
        (resource): resource is string => typeof resource === "string",
      )
    : [];
}

function BackupPanel({ zh }: { zh: boolean }) {
  const restoreInputRef = useRef<HTMLInputElement>(null);
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const restoreMutation = useMutation({
    mutationFn: () => { const data = new FormData(); data.append("confirmation", confirmation); if (restoreFile) data.append("file", restoreFile); return api.post("/api/data/backup/restore", data); },
    onSuccess: () => { setRestoreFile(null); setConfirmation(""); toast.success(zh ? "数据库已恢复，请重新登录确认数据" : "Database restored; sign in again to verify data"); window.setTimeout(() => window.location.reload(), 1200); },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : (zh ? "恢复失败" : "Restore failed")),
  });
  return <div className="grid gap-4 lg:grid-cols-2"><Card><CardHeader><CardTitle>{zh ? "导出与下载" : "Exports & downloads"}</CardTitle></CardHeader><CardContent className="space-y-3"><p className="text-sm text-muted-foreground">{zh ? "JSON 包含完整可恢复状态；SQL 是 PostgreSQL 全量备份。请将文件保存在安全位置。" : "JSON contains restorable state; SQL is a full PostgreSQL dump. Store files securely."}</p><DownloadButton href="/api/data/export/csv" label={zh ? "导出 CSV ZIP" : "Export CSV ZIP"} /><DownloadButton href="/api/data/export/json" label={zh ? "导出完整 JSON" : "Export full JSON"} /><DownloadButton href="/api/data/backup/download" label={zh ? "下载 SQL 数据库备份" : "Download SQL backup"} /></CardContent></Card>
    <Card className="border-amber-300"><CardHeader><CardTitle>{zh ? "恢复备份" : "Restore backup"}</CardTitle></CardHeader><CardContent className="space-y-4"><p className="text-sm text-amber-700">{zh ? "恢复会替换当前数据库全部内容。仅上传本系统生成且可信的 .json 或 .sql 文件。" : "Restore replaces the entire current database. Upload only a trusted .json or .sql generated by this app."}</p><Button variant="outline" onClick={() => restoreInputRef.current?.click()}><Upload className="h-4 w-4" />{restoreFile?.name ?? (zh ? "选择备份文件" : "Choose backup")}</Button><input ref={restoreInputRef} type="file" accept=".json,.sql" className="hidden" onChange={(event) => { setRestoreFile(event.target.files?.[0] ?? null); event.target.value = ""; }} /><div className="space-y-1.5"><Label>{zh ? "输入 RESTORE 确认" : "Type RESTORE to confirm"}</Label><Input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} placeholder="RESTORE" /></div><Button variant="destructive" disabled={!restoreFile || confirmation !== "RESTORE" || restoreMutation.isPending} onClick={() => restoreMutation.mutate()}>{restoreMutation.isPending ? (zh ? "恢复中…" : "Restoring…") : (zh ? "恢复数据库" : "Restore database")}</Button></CardContent></Card>
  </div>;
}

function DownloadButton({ href, label }: { href: string; label: string }) { return <Button variant="outline" className="w-full justify-start" render={<a href={href}><Download className="h-4 w-4" />{label}</a>} />; }
function Stat({ label, value }: { label: string; value: number }) { return <div className="rounded-md border p-3"><div className="text-xs text-muted-foreground">{label}</div><div className="text-xl font-semibold">{value}</div></div>; }
