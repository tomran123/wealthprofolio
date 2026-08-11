"use client";

/* Protected page previews require the browser's auth cookie, so a native image
 * request is intentional here instead of Next's server-side image optimizer. */
/* eslint-disable @next/next/no-img-element */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowUpRight,
  Ban,
  BookOpenCheck,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleGauge,
  FileQuestion,
  FileText,
  Layers3,
  LoaderCircle,
  RefreshCw,
  ScanText,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { ListSkeleton, LoadingSpinner } from "@/components/loading-state";
import {
  Alert,
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
import { ApiError } from "@/lib/api";
import {
  documentApi,
  documentPreviewUrl,
} from "@/lib/documents";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type {
  DocumentDetail,
  DocumentExtractedField,
  DocumentExtraction,
  DocumentPage,
  DocumentStatus,
  DocumentTransactionDraft,
  DocumentTransactionDraftItem,
} from "@/lib/types";

import { MonitoredJobProgress } from "./job-progress";

type DraftDecision = "confirm" | "cancel";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : fallback;
}

function confidencePercent(value: number | null): number | null {
  if (value === null || !Number.isFinite(value)) {
    return null;
  }
  return Math.round(Math.max(0, Math.min(100, value <= 1 ? value * 100 : value)));
}

function confidenceTone(value: number | null): string {
  const percent = confidencePercent(value);
  if (percent === null) {
    return "text-muted-foreground";
  }
  if (percent >= 85) {
    return "text-emerald-700";
  }
  if (percent >= 65) {
    return "text-amber-700";
  }
  return "text-destructive";
}

function humanValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  return JSON.stringify(value);
}

function statusLabel(status: DocumentStatus, zh: boolean): string {
  const labels: Record<DocumentStatus, [string, string]> = {
    pending_upload: ["等待上传", "Awaiting upload"],
    uploading: ["上传中", "Uploading"],
    uploaded: ["已上传", "Uploaded"],
    queued: ["排队中", "Queued"],
    processing: ["处理中", "Processing"],
    ready: ["已就绪", "Ready"],
    failed: ["处理失败", "Failed"],
    archived: ["已归档", "Archived"],
  };
  return zh ? labels[status][0] : labels[status][1];
}

export function DocumentDetailClient({
  documentId,
  initialPage,
  initialDocument,
}: {
  documentId: string;
  initialPage: number | null;
  initialDocument: DocumentDetail | null;
}) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const queryClient = useQueryClient();
  const [selectedPageNumber, setSelectedPageNumber] = useState<number | null>(
    initialPage,
  );
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [decision, setDecision] = useState<DraftDecision | null>(null);

  const detailQuery = useQuery({
    queryKey: ["documents", documentId],
    queryFn: () => documentApi.detail(documentId),
    initialData: initialDocument ?? undefined,
  });
  const draftQuery = useQuery({
    queryKey: ["documents", documentId, "transaction-draft"],
    queryFn: () => documentApi.latestTransactionDraft(documentId),
  });

  const detail = detailQuery.data;
  const pages = useMemo(() => detail?.pages ?? [], [detail?.pages]);
  const selectedPage =
    pages.find((page) => page.page_number === selectedPageNumber) ??
    pages[0] ??
    null;

  const reprocessMutation = useMutation({
    mutationFn: () => documentApi.reprocess(documentId),
    onSuccess: ({ job }) => {
      setActiveJobId(job.id);
      void queryClient.invalidateQueries({
        queryKey: ["documents", documentId],
      });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  const createDraftMutation = useMutation({
    mutationFn: () => documentApi.createTransactionDraft(documentId),
    onSuccess: (draft) => {
      queryClient.setQueryData(
        ["documents", documentId, "transaction-draft"],
        draft,
      );
    },
  });

  const resolveDraftMutation = useMutation({
    mutationFn: async ({
      nextDecision,
      draft,
    }: {
      nextDecision: DraftDecision;
      draft: DocumentTransactionDraft;
    }) => {
      return nextDecision === "confirm"
        ? documentApi.confirmTransactionDraft(
            documentId,
            draft.extraction_id,
          )
        : documentApi.cancelTransactionDraft(
            documentId,
            draft.extraction_id,
          );
    },
    onSuccess: (draft, variables) => {
      setDecision(null);
      queryClient.setQueryData(
        ["documents", documentId, "transaction-draft"],
        draft,
      );
      if (variables.nextDecision === "confirm") {
        ["transactions", "portfolio", "accounts", "instruments"].forEach(
          (key) => void queryClient.invalidateQueries({ queryKey: [key] }),
        );
      }
    },
  });

  if (detailQuery.isLoading) {
    return (
      <div className="space-y-5">
        <Button
          variant="ghost"
          render={<Link href="/documents" />}
        >
          <ArrowLeft className="size-4" />
          {zh ? "返回文档中心" : "Back to documents"}
        </Button>
        <ListSkeleton
          rows={7}
          label={zh ? "正在加载文档详情" : "Loading document details"}
        />
      </div>
    );
  }

  if (detailQuery.isError || !detail) {
    return (
      <div className="space-y-5">
        <Button
          variant="ghost"
          render={<Link href="/documents" />}
        >
          <ArrowLeft className="size-4" />
          {zh ? "返回文档中心" : "Back to documents"}
        </Button>
        <Alert variant="destructive">
          <TriangleAlert />
          <AlertTitle>
            {zh ? "无法打开文档" : "Unable to open document"}
          </AlertTitle>
          <AlertDescription>
            {errorMessage(
              detailQuery.error,
              zh ? "文档不存在或无权访问。" : "The document is unavailable.",
            )}
          </AlertDescription>
        </Alert>
      </div>
    );
  }

  const effectiveJobId = activeJobId ?? detail.latest_job_id;
  const jobIsRelevant =
    effectiveJobId &&
    ["pending_upload", "uploaded", "queued", "processing", "failed"].includes(
      detail.status,
    );

  return (
    <div className="space-y-6">
      <div>
        <Button
          variant="ghost"
          className="-ml-2 mb-3"
          render={<Link href="/documents" />}
        >
          <ArrowLeft className="size-4" />
          {zh ? "返回文档中心" : "Back to documents"}
        </Button>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge
                variant={
                  detail.status === "failed"
                    ? "destructive"
                    : detail.status === "ready"
                      ? "default"
                      : "secondary"
                }
              >
                {statusLabel(detail.status, zh)}
              </Badge>
              {detail.document_type && (
                <Badge variant="outline">{detail.document_type}</Badge>
              )}
            </div>
            <h1 className="mt-3 break-words text-2xl font-semibold tracking-tight sm:text-3xl">
              {detail.filename}
            </h1>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
              <span className="inline-flex items-center gap-1.5">
                <Layers3 className="size-4" />
                {detail.page_count} {zh ? "页" : "pages"}
              </span>
              {detail.document_date && (
                <span className="inline-flex items-center gap-1.5">
                  <CalendarDays className="size-4" />
                  {detail.document_date}
                </span>
              )}
              <span>
                {zh ? "更新于" : "Updated"}{" "}
                {new Date(detail.updated_at).toLocaleString()}
              </span>
            </div>
          </div>
          <Button
            variant="outline"
            onClick={() => reprocessMutation.mutate()}
            disabled={reprocessMutation.isPending || detail.status === "processing"}
          >
            {reprocessMutation.isPending ? (
              <LoadingSpinner label={zh ? "正在重新处理" : "Reprocessing"} />
            ) : (
              <RefreshCw className="size-4" />
            )}
            {zh ? "重新处理" : "Reprocess"}
          </Button>
        </div>
      </div>

      {reprocessMutation.isError && (
        <Alert variant="destructive">
          <TriangleAlert />
          <AlertTitle>{zh ? "无法重新处理" : "Reprocess failed"}</AlertTitle>
          <AlertDescription>
            {errorMessage(
              reprocessMutation.error,
              zh ? "请稍后重试。" : "Please try again.",
            )}
          </AlertDescription>
        </Alert>
      )}

      {jobIsRelevant && effectiveJobId && (
        <Card className="border-primary/20 bg-primary/[0.025]">
          <CardHeader>
            <CardTitle className="text-base">
              {zh ? "文档处理进度" : "Document processing"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MonitoredJobProgress
              jobId={effectiveJobId}
              zh={zh}
              onTerminal={() => {
                void detailQuery.refetch();
                void queryClient.invalidateQueries({
                  queryKey: ["documents"],
                });
              }}
            />
          </CardContent>
        </Card>
      )}

      {detail.status === "failed" && (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>{zh ? "文档处理失败" : "Document processing failed"}</AlertTitle>
          <AlertDescription>
            {zh
              ? "原始文件仍安全保存。你可以重新处理；若持续失败，请检查文件是否损坏或受密码保护。"
              : "The original remains safely stored. Reprocess it, or check whether the file is damaged or password-protected."}
          </AlertDescription>
        </Alert>
      )}

      <ProgressiveExtraction
        detail={detail}
        zh={zh}
        onOpenPage={setSelectedPageNumber}
      />

      <TransactionDraftPanel
        zh={zh}
        document={detail}
        draft={draftQuery.data ?? null}
        isLoading={draftQuery.isLoading}
        loadError={draftQuery.isError ? draftQuery.error : null}
        creating={createDraftMutation.isPending}
        createError={
          createDraftMutation.isError ? createDraftMutation.error : null
        }
        onCreate={() => createDraftMutation.mutate()}
        onDecision={setDecision}
      />

      <PageViewer
        documentId={documentId}
        pages={pages}
        selectedPage={selectedPage}
        zh={zh}
        onSelect={setSelectedPageNumber}
      />

      <Dialog
        open={decision !== null}
        onOpenChange={(open) => !open && setDecision(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {decision === "confirm"
                ? zh
                  ? "确认写入交易账本？"
                  : "Post these transactions?"
                : zh
                  ? "取消这份交易草案？"
                  : "Cancel this transaction draft?"}
            </DialogTitle>
            <DialogDescription>
              {decision === "confirm"
                ? zh
                  ? "系统将通过事件账本创建交易、复式 postings 与审计记录，不会直接修改持仓。请先核对金额、账户和来源页。"
                  : "This creates ledger events, balanced postings, and an audit record without writing holdings directly. Verify accounts, amounts, and citations first."
                : zh
                  ? "取消后不会改变任何业务数据，原始文档和抽取结果仍会保留。"
                  : "Cancelling changes no business data; the source document and extraction remain available."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDecision(null)}
              disabled={resolveDraftMutation.isPending}
            >
              {zh ? "返回核对" : "Keep reviewing"}
            </Button>
            <Button
              variant={decision === "confirm" ? "default" : "destructive"}
              disabled={!decision || resolveDraftMutation.isPending}
              onClick={() => {
                if (decision && draftQuery.data) {
                  resolveDraftMutation.mutate({
                    nextDecision: decision,
                    draft: draftQuery.data,
                  });
                }
              }}
            >
              {resolveDraftMutation.isPending ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : decision === "confirm" ? (
                <Check className="size-4" />
              ) : (
                <X className="size-4" />
              )}
              {decision === "confirm"
                ? zh
                  ? "确认写入"
                  : "Confirm and post"
                : zh
                  ? "确认取消"
                  : "Cancel draft"}
            </Button>
          </DialogFooter>
          {resolveDraftMutation.isError && (
            <p className="text-sm text-destructive">
              {errorMessage(
                resolveDraftMutation.error,
                zh ? "操作失败，请重试。" : "Action failed. Please retry.",
              )}
            </p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function ProgressiveExtraction({
  detail,
  zh,
  onOpenPage,
}: {
  detail: DocumentDetail;
  zh: boolean;
  onOpenPage: (page: number) => void;
}) {
  const extractions = detail.extractions ?? [];
  const summaries = extractions
    .map((extraction) => extraction.summary)
    .filter((value): value is string => Boolean(value));

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2 text-primary">
            <ScanText className="size-5" />
          </div>
          <div>
            <CardTitle>
              {zh ? "1. 抽取摘要" : "1. Extraction summary"}
            </CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              {zh
                ? "先看结论，再展开字段；每项低置信度内容都应回到来源页核验。"
                : "Start with the conclusion, expand fields as needed, and verify low-confidence data against its source page."}
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {summaries.length > 0 ? (
          <div className="space-y-3">
            {summaries.map((summary, index) => (
              <p key={index} className="text-sm leading-6">
                {summary}
              </p>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed p-5 text-center text-sm text-muted-foreground">
            {detail.status === "ready"
              ? zh
                ? "没有生成摘要，可展开字段或查看原始页。"
                : "No summary was produced. Review fields or source pages."
              : zh
                ? "处理完成后会在这里显示摘要。"
                : "The summary will appear when processing completes."}
          </div>
        )}

        <div className="space-y-2 border-t pt-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="font-medium">
                {zh ? "2. 详细字段" : "2. Detailed fields"}
              </h3>
              <p className="text-xs text-muted-foreground">
                {zh
                  ? `${extractions.reduce((count, extraction) => count + extraction.fields.length, 0)} 个字段`
                  : `${extractions.reduce((count, extraction) => count + extraction.fields.length, 0)} fields`}
              </p>
            </div>
            <CircleGauge className="size-5 text-muted-foreground" />
          </div>

          {extractions.map((extraction) => (
            <ExtractionDisclosure
              key={extraction.id}
              extraction={extraction}
              zh={zh}
              onOpenPage={onOpenPage}
            />
          ))}

          {extractions.length === 0 && (
            <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              {zh
                ? "尚无结构化抽取结果。"
                : "No structured extraction is available yet."}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function ExtractionDisclosure({
  extraction,
  zh,
  onOpenPage,
}: {
  extraction: DocumentExtraction;
  zh: boolean;
  onOpenPage: (page: number) => void;
}) {
  const percent = confidencePercent(extraction.confidence);
  return (
    <details className="group rounded-lg border bg-muted/10">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-3 text-sm">
        <div className="flex min-w-0 items-center gap-2">
          <ChevronRight className="size-4 shrink-0 transition-transform group-open:rotate-90" />
          <span className="truncate font-medium">
            {extraction.extraction_type}
          </span>
          <Badge variant="outline">{extraction.fields.length}</Badge>
        </div>
        <span className={cn("text-xs font-medium", confidenceTone(extraction.confidence))}>
          {percent === null
            ? zh
              ? "置信度未知"
              : "No confidence"
            : `${percent}%`}
        </span>
      </summary>
      <div className="border-t">
        <div className="grid gap-px bg-border">
          {extraction.fields.map((field, index) => (
            <FieldRow
              key={`${field.name}-${index}`}
              field={field}
              zh={zh}
              onOpenPage={onOpenPage}
            />
          ))}
        </div>
        {extraction.fields.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">
            {zh ? "该抽取没有字段。" : "This extraction has no fields."}
          </p>
        )}
      </div>
    </details>
  );
}

function FieldRow({
  field,
  zh,
  onOpenPage,
}: {
  field: DocumentExtractedField;
  zh: boolean;
  onOpenPage: (page: number) => void;
}) {
  const percent = confidencePercent(field.confidence);
  return (
    <div className="grid gap-2 bg-card p-3 sm:grid-cols-[minmax(130px,0.6fr)_minmax(0,1.4fr)_auto] sm:items-center">
      <div>
        <p className="text-xs text-muted-foreground">
          {field.label || field.name}
        </p>
        {field.label && (
          <p className="mt-0.5 text-[10px] text-muted-foreground/70">
            {field.name}
          </p>
        )}
      </div>
      <p className="break-words text-sm font-medium">
        {humanValue(field.value)}
      </p>
      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        <span className={cn("text-xs font-medium", confidenceTone(field.confidence))}>
          {percent === null ? "—" : `${percent}%`}
        </span>
        {field.page_number !== null && (
          <Button
            size="xs"
            variant="outline"
            onClick={() => onOpenPage(field.page_number as number)}
            title={field.citation ?? undefined}
          >
            {zh ? `第 ${field.page_number} 页` : `p. ${field.page_number}`}
            <ArrowUpRight className="size-3" />
          </Button>
        )}
      </div>
    </div>
  );
}

function TransactionDraftPanel({
  zh,
  document,
  draft,
  isLoading,
  loadError,
  creating,
  createError,
  onCreate,
  onDecision,
}: {
  zh: boolean;
  document: DocumentDetail;
  draft: DocumentTransactionDraft | null;
  isLoading: boolean;
  loadError: unknown;
  creating: boolean;
  createError: unknown;
  onCreate: () => void;
  onDecision: (decision: DraftDecision) => void;
}) {
  const pending = draft?.status === "pending_review";
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-primary/10 p-2 text-primary">
              <BookOpenCheck className="size-5" />
            </div>
            <div>
              <CardTitle>
                {zh ? "交易草案核对" : "Transaction draft review"}
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                {zh
                  ? "草案不是账本记录；只有确认后才会创建不可变事件与审计。"
                  : "A draft is not a ledger entry. Immutable events and audit records are created only after confirmation."}
              </p>
            </div>
          </div>
          {draft && (
            <Badge
              variant={
                draft.status === "confirmed"
                  ? "default"
                  : draft.status === "cancelled"
                    ? "outline"
                    : draft.status === "failed"
                      ? "destructive"
                      : "secondary"
              }
            >
              {draft.status}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading ? (
          <div className="flex items-center gap-2 rounded-lg border p-4 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" />
            {zh ? "正在加载交易草案…" : "Loading transaction draft…"}
          </div>
        ) : loadError ? (
          <Alert variant="destructive">
            <TriangleAlert />
            <AlertTitle>
              {zh ? "无法加载交易草案" : "Unable to load draft"}
            </AlertTitle>
            <AlertDescription>
              {errorMessage(
                loadError,
                zh ? "请稍后重试。" : "Please try again.",
              )}
            </AlertDescription>
          </Alert>
        ) : draft ? (
          <>
            <DraftItems items={draft.items} zh={zh} />
            {draft.warnings.length > 0 && (
              <Alert>
                <AlertTriangle />
                <AlertTitle>{zh ? "需要注意" : "Review warnings"}</AlertTitle>
                <AlertDescription>
                  {draft.warnings.join(" · ")}
                </AlertDescription>
              </Alert>
            )}
            {pending && (
              <div className="flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-end">
                <Button
                  variant="outline"
                  onClick={() => onDecision("cancel")}
                >
                  <Ban className="size-4" />
                  {zh ? "取消草案" : "Cancel draft"}
                </Button>
                <Button onClick={() => onDecision("confirm")}>
                  <ShieldCheck className="size-4" />
                  {zh ? "核对无误，确认写入" : "Verified — confirm and post"}
                </Button>
              </div>
            )}
            {draft.status === "confirmed" && (
              <div className="flex items-center gap-2 rounded-lg bg-emerald-500/10 p-3 text-sm text-emerald-800">
                <CheckCircle2 className="size-4" />
                {zh
                  ? "交易已通过事件账本写入并生成审计记录。"
                  : "Transactions were posted through the event ledger with an audit record."}
              </div>
            )}
            {draft.status === "cancelled" && (
              <div className="flex items-center gap-2 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                <Ban className="size-4" />
                {zh
                  ? "草案已取消，业务数据没有变化。"
                  : "The draft was cancelled; business data was unchanged."}
              </div>
            )}
          </>
        ) : (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-6 text-center">
            <Sparkles className="mb-3 size-6 text-muted-foreground" />
            <p className="font-medium">
              {zh ? "尚未生成交易草案" : "No transaction draft yet"}
            </p>
            <p className="mt-1 max-w-md text-sm text-muted-foreground">
              {zh
                ? "系统会根据已抽取字段提出待确认交易；低置信度内容仍需人工核对。"
                : "Create a proposed set of transactions from extracted fields. Low-confidence values still require manual review."}
            </p>
            <Button
              className="mt-4"
              onClick={onCreate}
              disabled={creating || document.status !== "ready"}
            >
              {creating ? (
                <LoaderCircle className="size-4 animate-spin" />
              ) : (
                <Sparkles className="size-4" />
              )}
              {creating
                ? zh
                  ? "生成中…"
                  : "Creating…"
                : zh
                  ? "生成待确认草案"
                  : "Create review draft"}
            </Button>
            {document.status !== "ready" && (
              <p className="mt-2 text-xs text-muted-foreground">
                {zh
                  ? "文档处理完成后才能生成草案。"
                  : "The document must finish processing first."}
              </p>
            )}
          </div>
        )}
        {createError ? (
          <p className="text-sm text-destructive">
            {errorMessage(
              createError,
              zh ? "草案生成失败，请重试。" : "Draft creation failed.",
            )}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function DraftItems({
  items,
  zh,
}: {
  items: DocumentTransactionDraftItem[];
  zh: boolean;
}) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-5 text-center text-sm text-muted-foreground">
        {zh ? "草案中没有交易。" : "The draft contains no transactions."}
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {items.map((item, index) => {
        const confidence = confidencePercent(item.confidence);
        return (
          <article key={item.id ?? index} className="rounded-lg border p-3 sm:p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{item.transaction_type}</Badge>
                  <span className="font-medium">
                    {item.instrument_symbol
                      ? `${item.instrument_symbol} · `
                      : ""}
                    {item.instrument_name || (zh ? "现金交易" : "Cash transaction")}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.account_name ||
                    item.account_id ||
                    (zh ? "账户待确认" : "Account to verify")}
                </p>
              </div>
              <span className={cn("text-xs font-medium", confidenceTone(item.confidence))}>
                {zh ? "置信度" : "Confidence"}{" "}
                {confidence === null ? "—" : `${confidence}%`}
              </span>
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <DraftValue
                label={zh ? "数量" : "Quantity"}
                value={item.quantity}
              />
              <DraftValue
                label={zh ? "价格" : "Price"}
                value={item.price}
              />
              <DraftValue
                label={zh ? "金额" : "Amount"}
                value={
                  item.amount ? `${item.amount} ${item.currency}` : null
                }
              />
              <DraftValue
                label={zh ? "交易日期" : "Trade date"}
                value={item.trade_date}
              />
            </dl>
            {(item.page_number !== null || item.citation) && (
              <p className="mt-3 border-t pt-2 text-xs text-muted-foreground">
                {item.citation ||
                  (zh
                    ? `来源：第 ${item.page_number} 页`
                    : `Source: page ${item.page_number}`)}
              </p>
            )}
          </article>
        );
      })}
    </div>
  );
}

function DraftValue({
  label,
  value,
}: {
  label: string;
  value: string | null;
}) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium">{value || "—"}</dd>
    </div>
  );
}

function PageViewer({
  documentId,
  pages,
  selectedPage,
  zh,
  onSelect,
}: {
  documentId: string;
  pages: DocumentPage[];
  selectedPage: DocumentPage | null;
  zh: boolean;
  onSelect: (page: number) => void;
}) {
  return (
    <Card id="source-pages">
      <CardHeader>
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-primary/10 p-2 text-primary">
            <FileText className="size-5" />
          </div>
          <div>
            <CardTitle>
              {zh ? "3. 原始页核验" : "3. Verify source pages"}
            </CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              {zh
                ? "页级预览来自受保护的原始文档，不会生成公开链接。"
                : "Page previews come from the protected source document and are never public."}
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {pages.length === 0 ? (
          <div className="flex min-h-44 flex-col items-center justify-center rounded-lg border border-dashed p-6 text-center">
            <FileQuestion className="mb-3 size-7 text-muted-foreground" />
            <p className="font-medium">
              {zh ? "页预览尚未生成" : "Page previews are not ready"}
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              {zh
                ? "文档分页完成后会在这里显示。"
                : "They will appear after pagination completes."}
            </p>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[180px_minmax(0,1fr)]">
            <div
              className="flex gap-2 overflow-x-auto pb-2 lg:max-h-[720px] lg:flex-col lg:overflow-y-auto lg:overflow-x-hidden lg:pr-2"
              aria-label={zh ? "文档页面列表" : "Document page list"}
            >
              {pages.map((page) => (
                <button
                  key={page.page_number}
                  type="button"
                  onClick={() => onSelect(page.page_number)}
                  className={cn(
                    "min-w-28 rounded-lg border p-2 text-left transition-colors lg:min-w-0",
                    selectedPage?.page_number === page.page_number
                      ? "border-primary bg-primary/5"
                      : "hover:bg-muted/40",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-medium">
                      {zh ? `第 ${page.page_number} 页` : `Page ${page.page_number}`}
                    </span>
                    {page.status === "ready" ? (
                      <CheckCircle2 className="size-3 text-emerald-600" />
                    ) : page.status === "failed" ? (
                      <AlertTriangle className="size-3 text-destructive" />
                    ) : (
                      <LoaderCircle className="size-3 animate-spin text-muted-foreground" />
                    )}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">
                    {page.text_preview ||
                      (zh ? "暂无文本预览" : "No text preview")}
                  </p>
                  {confidencePercent(page.ocr_confidence) !== null && (
                    <p className={cn("mt-1 text-[10px]", confidenceTone(page.ocr_confidence))}>
                      OCR {confidencePercent(page.ocr_confidence)}%
                    </p>
                  )}
                </button>
              ))}
            </div>

            <div className="min-w-0">
              {selectedPage?.status === "ready" ? (
                <div className="overflow-auto rounded-lg border bg-muted/30 p-2 sm:p-4">
                  <img
                    key={selectedPage.page_number}
                    src={documentPreviewUrl(
                      documentId,
                      selectedPage.page_number,
                      selectedPage.preview_url,
                    )}
                    alt={
                      zh
                        ? `${selectedPage.page_number} 页原始预览`
                        : `Source preview, page ${selectedPage.page_number}`
                    }
                    className="mx-auto h-auto max-h-[900px] max-w-full rounded-sm bg-white object-contain shadow-sm"
                  />
                </div>
              ) : (
                <div className="flex min-h-80 flex-col items-center justify-center rounded-lg border border-dashed p-6 text-center text-muted-foreground">
                  {selectedPage?.status === "failed" ? (
                    <AlertTriangle className="mb-3 size-7 text-destructive" />
                  ) : (
                    <LoaderCircle className="mb-3 size-7 animate-spin" />
                  )}
                  <p className="font-medium text-foreground">
                    {selectedPage?.status === "failed"
                      ? zh
                        ? "该页预览生成失败"
                        : "This page preview failed"
                      : zh
                        ? "该页仍在处理"
                        : "This page is still processing"}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
