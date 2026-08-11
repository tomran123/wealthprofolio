"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Clock3,
  FileCheck2,
  FileSearch,
  FileText,
  FolderOpen,
  ListChecks,
  RefreshCw,
  Search,
  Sparkles,
  TriangleAlert,
  UploadCloud,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { ListSkeleton } from "@/components/loading-state";
import {
  Alert,
  AlertAction,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api, ApiError } from "@/lib/api";
import { documentApi } from "@/lib/documents";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type {
  AccountWithNames,
  BackgroundJob,
  DocumentStatus,
  DocumentPageResult,
  DocumentSummary,
  Institution,
  Owner,
} from "@/lib/types";

import { JobProgress, MonitoredJobProgress } from "./job-progress";
import { KnowledgeExplorer } from "./knowledge-explorer";
import { UploadPanel } from "./upload-panel";

interface QueuedDocument {
  document: DocumentSummary;
  job: BackgroundJob;
}

const PROCESSING_STATUSES = new Set<DocumentStatus>([
  "pending_upload",
  "uploading",
  "uploaded",
  "queued",
  "processing",
]);

function statusLabel(status: DocumentStatus, zh: boolean): string {
  const values: Record<DocumentStatus, [string, string]> = {
    pending_upload: ["等待上传", "Awaiting upload"],
    uploading: ["上传中", "Uploading"],
    uploaded: ["已上传", "Uploaded"],
    queued: ["排队中", "Queued"],
    processing: ["处理中", "Processing"],
    ready: ["可检索", "Ready"],
    failed: ["失败", "Failed"],
    archived: ["已归档", "Archived"],
  };
  return zh ? values[status][0] : values[status][1];
}

function statusVariant(
  status: DocumentStatus,
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "ready") {
    return "default";
  }
  if (status === "failed") {
    return "destructive";
  }
  if (PROCESSING_STATUSES.has(status)) {
    return "secondary";
  }
  return "outline";
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) {
    return "—";
  }
  if (bytes < 1024 * 1024) {
    return `${Math.max(0.1, bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function errorText(error: unknown, fallback: string): string {
  if (error instanceof ApiError || error instanceof Error) {
    return error.message;
  }
  return fallback;
}

export function DocumentCenterClient({
  initialDocuments,
}: {
  initialDocuments: DocumentPageResult | null;
}) {
  const { locale } = useI18n();
  const zh = locale === "zh";
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [filenameSearch, setFilenameSearch] = useState("");
  const [queuedDocuments, setQueuedDocuments] = useState<
    Record<string, QueuedDocument>
  >({});

  const documentsQuery = useQuery({
    queryKey: ["documents", { statusFilter, typeFilter }],
    queryFn: () =>
      documentApi.list({
        offset: 0,
        limit: 100,
        status: statusFilter || undefined,
        type: typeFilter || undefined,
      }),
    initialData:
      !statusFilter && !typeFilter ? initialDocuments ?? undefined : undefined,
  });
  const ownersQuery = useQuery({
    queryKey: ["owners"],
    queryFn: () => api.get<Owner[]>("/api/owners"),
  });
  const institutionsQuery = useQuery({
    queryKey: ["institutions"],
    queryFn: () => api.get<Institution[]>("/api/institutions"),
  });
  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<AccountWithNames[]>("/api/accounts"),
  });

  const documents = useMemo(
    () => documentsQuery.data?.items ?? [],
    [documentsQuery.data?.items],
  );
  const visibleDocuments = useMemo(() => {
    const search = filenameSearch.trim().toLocaleLowerCase();
    if (!search) {
      return documents;
    }
    return documents.filter((document) =>
      document.filename.toLocaleLowerCase().includes(search),
    );
  }, [documents, filenameSearch]);

  const processingCount = documents.filter((document) =>
    PROCESSING_STATUSES.has(document.status),
  ).length;
  const readyCount = documents.filter(
    (document) => document.status === "ready",
  ).length;

  const onQueued = (document: DocumentSummary, job: BackgroundJob) => {
    setQueuedDocuments((current) => ({
      ...current,
      [document.id]: { document, job },
    }));
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  };

  const refreshDocuments = () => {
    void queryClient.invalidateQueries({ queryKey: ["documents"] });
  };

  const completeQueuedDocument = (documentId: string) => {
    setQueuedDocuments((current) => {
      if (!current[documentId]) {
        return current;
      }
      const next = { ...current };
      delete next[documentId];
      return next;
    });
    refreshDocuments();
  };

  const metadataWarning =
    ownersQuery.isError || institutionsQuery.isError || accountsQuery.isError;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-medium text-primary">
            <FileSearch className="size-4" />
            {zh ? "可信 AI 文档录入" : "Trusted AI document intake"}
          </div>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            {zh ? "文档与知识中心" : "Documents & Knowledge"}
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {zh
              ? "上传账单或截图，跟踪 OCR 与索引进度，核验每个字段的来源页，再决定是否写入交易账本。"
              : "Upload statements or screenshots, follow OCR and indexing, verify every field against its source page, then decide whether to post transactions."}
          </p>
        </div>
        <Button
          variant="outline"
          onClick={refreshDocuments}
          disabled={documentsQuery.isFetching}
        >
          <RefreshCw
            className={cn(
              "size-4",
              documentsQuery.isFetching && "animate-spin",
            )}
          />
          {zh ? "刷新" : "Refresh"}
        </Button>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <SummaryCard
          icon={FolderOpen}
          label={zh ? "全部文档" : "All documents"}
          value={documentsQuery.data?.total ?? documents.length}
        />
        <SummaryCard
          icon={Clock3}
          label={zh ? "正在处理" : "Processing"}
          value={processingCount}
          accent={processingCount > 0}
        />
        <SummaryCard
          icon={FileCheck2}
          label={zh ? "已可检索" : "Searchable"}
          value={readyCount}
          className="col-span-2 md:col-span-1"
        />
      </div>

      <Tabs defaultValue="documents">
        <TabsList className="h-auto w-full justify-start overflow-x-auto sm:w-fit">
          <TabsTrigger value="documents" className="px-3 py-1.5">
            <FileText className="size-4" />
            {zh ? "文档录入" : "Document intake"}
          </TabsTrigger>
          <TabsTrigger value="knowledge" className="px-3 py-1.5">
            <Sparkles className="size-4" />
            {zh ? "知识检索与问答" : "Search & ask"}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="documents" className="mt-4 space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-start gap-3">
                <div className="rounded-lg bg-primary/10 p-2 text-primary">
                  <UploadCloud className="size-5" />
                </div>
                <div>
                  <CardTitle>
                    {zh ? "上传并开始处理" : "Upload and process"}
                  </CardTitle>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {zh
                      ? "文件保存在私有对象存储；处理结果严格限制在当前 Family。"
                      : "Files remain in private object storage and results stay within the active family."}
                  </p>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {metadataWarning && (
                <Alert className="mb-4">
                  <TriangleAlert />
                  <AlertTitle>
                    {zh
                      ? "部分归类选项暂不可用"
                      : "Some document context is unavailable"}
                  </AlertTitle>
                  <AlertDescription>
                    {zh
                      ? "仍可上传文档，稍后在详情中关联账户。"
                      : "You can still upload and link the account later."}
                  </AlertDescription>
                </Alert>
              )}
              <UploadPanel
                zh={zh}
                owners={ownersQuery.data ?? []}
                institutions={institutionsQuery.data ?? []}
                accounts={accountsQuery.data ?? []}
                onQueued={onQueued}
              />
            </CardContent>
          </Card>

          <ProcessingQueue
            documents={documents}
            queuedDocuments={queuedDocuments}
            zh={zh}
            onTerminal={completeQueuedDocument}
          />

          <Card>
            <CardHeader>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                <div>
                  <CardTitle>{zh ? "文档库" : "Document library"}</CardTitle>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {zh
                      ? "打开文档可查看抽取摘要、字段置信度、页码引用和交易草案。"
                      : "Open a document to review its summary, confidence, page citations, and transaction draft."}
                  </p>
                </div>
                <div className="grid gap-2 sm:grid-cols-3">
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
                    <Input
                      value={filenameSearch}
                      onChange={(event) =>
                        setFilenameSearch(event.target.value)
                      }
                      placeholder={zh ? "搜索文件名" : "Search filename"}
                      className="pl-8"
                      aria-label={zh ? "搜索文件名" : "Search filename"}
                    />
                  </div>
                  <select
                    value={statusFilter}
                    onChange={(event) => setStatusFilter(event.target.value)}
                    className="h-8 rounded-lg border bg-background px-2.5 text-sm"
                    aria-label={zh ? "按状态筛选" : "Filter by status"}
                  >
                    <option value="">{zh ? "全部状态" : "All statuses"}</option>
                    <option value="processing">
                      {zh ? "处理中" : "Processing"}
                    </option>
                    <option value="ready">
                      {zh ? "已就绪" : "Ready"}
                    </option>
                    <option value="failed">
                      {zh ? "失败" : "Failed"}
                    </option>
                  </select>
                  <select
                    value={typeFilter}
                    onChange={(event) => setTypeFilter(event.target.value)}
                    className="h-8 rounded-lg border bg-background px-2.5 text-sm"
                    aria-label={zh ? "按文档类型筛选" : "Filter by type"}
                  >
                    <option value="">{zh ? "全部类型" : "All types"}</option>
                    <option value="statement">
                      {zh ? "月结单" : "Statement"}
                    </option>
                    <option value="trade_confirmation">
                      {zh ? "交易确认单" : "Trade confirmation"}
                    </option>
                    <option value="tax_document">
                      {zh ? "税务文件" : "Tax document"}
                    </option>
                    <option value="valuation_report">
                      {zh ? "估值报告" : "Valuation report"}
                    </option>
                    <option value="screenshot">
                      {zh ? "应用截图" : "Screenshot"}
                    </option>
                  </select>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {documentsQuery.isLoading ? (
                <ListSkeleton
                  rows={6}
                  label={zh ? "正在加载文档" : "Loading documents"}
                />
              ) : documentsQuery.isError ? (
                <Alert variant="destructive">
                  <TriangleAlert />
                  <AlertTitle>
                    {zh ? "无法加载文档" : "Unable to load documents"}
                  </AlertTitle>
                  <AlertDescription>
                    {errorText(
                      documentsQuery.error,
                      zh ? "请稍后重试。" : "Please try again.",
                    )}
                  </AlertDescription>
                  <AlertAction>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void documentsQuery.refetch()}
                    >
                      {zh ? "重试" : "Retry"}
                    </Button>
                  </AlertAction>
                </Alert>
              ) : (
                <DocumentList documents={visibleDocuments} zh={zh} />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="knowledge" className="mt-4">
          <KnowledgeExplorer zh={zh} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  accent = false,
  className,
}: {
  icon: typeof FolderOpen;
  label: string;
  value: number;
  accent?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-xl border bg-card p-3 sm:p-4",
        accent && "border-primary/30 bg-primary/5",
        className,
      )}
    >
      <div
        className={cn(
          "rounded-lg bg-muted p-2 text-muted-foreground",
          accent && "bg-primary/10 text-primary",
        )}
      >
        <Icon className="size-4" />
      </div>
      <div>
        <div className="text-xl font-semibold tabular-nums">{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
      </div>
    </div>
  );
}

function ProcessingQueue({
  documents,
  queuedDocuments,
  zh,
  onTerminal,
}: {
  documents: DocumentSummary[];
  queuedDocuments: Record<string, QueuedDocument>;
  zh: boolean;
  onTerminal: (documentId: string) => void;
}) {
  const items = useMemo(() => {
    const combined = new Map<
      string,
      { document: DocumentSummary; job: BackgroundJob | null }
    >();
    documents
      .filter((document) => PROCESSING_STATUSES.has(document.status))
      .forEach((document) => {
        combined.set(document.id, {
          document,
          job: queuedDocuments[document.id]?.job ?? null,
        });
      });
    Object.values(queuedDocuments).forEach(({ document, job }) => {
      combined.set(document.id, { document, job });
    });
    return Array.from(combined.values()).sort(
      (a, b) =>
        new Date(b.document.updated_at).getTime() -
        new Date(a.document.updated_at).getTime(),
    );
  }, [documents, queuedDocuments]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-primary/10 p-2 text-primary">
              <ListChecks className="size-5" />
            </div>
            <div>
              <CardTitle>{zh ? "处理队列" : "Processing queue"}</CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                {zh
                  ? "优先使用实时连接；网络受限时自动回退为轮询。"
                  : "Uses live updates first and falls back to polling when needed."}
              </p>
            </div>
          </div>
          <Badge variant="outline">{items.length}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <div className="flex min-h-28 flex-col items-center justify-center rounded-lg border border-dashed p-5 text-center text-sm text-muted-foreground">
            <ListChecks className="mb-2 size-5" />
            {zh ? "当前没有处理中的文档" : "No documents are processing"}
          </div>
        ) : (
          <div className="space-y-3">
            {items.map(({ document, job }) => {
              const jobId = job?.id ?? document.latest_job_id;
              return (
                <div key={document.id} className="rounded-lg border p-3 sm:p-4">
                  <div className="mb-3 flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {document.filename}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {document.document_type || (zh ? "未分类" : "Unclassified")}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      render={<Link href={`/documents/${document.id}`} />}
                    >
                      {zh ? "查看" : "Open"}
                      <ArrowUpRight className="size-3" />
                    </Button>
                  </div>
                  {jobId ? (
                    <MonitoredJobProgress
                      jobId={jobId}
                      zh={zh}
                      onTerminal={() => onTerminal(document.id)}
                    />
                  ) : job ? (
                    <JobProgress
                      job={job}
                      transport="connecting"
                      zh={zh}
                    />
                  ) : (
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Clock3 className="size-4" />
                      {statusLabel(document.status, zh)}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DocumentList({
  documents,
  zh,
}: {
  documents: DocumentSummary[];
  zh: boolean;
}) {
  if (documents.length === 0) {
    return (
      <div className="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed p-6 text-center">
        <FolderOpen className="mb-3 size-7 text-muted-foreground" />
        <p className="font-medium">
          {zh ? "还没有匹配的文档" : "No matching documents"}
        </p>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          {zh
            ? "上传第一份 PDF 或截图，或调整当前筛选条件。"
            : "Upload the first PDF or screenshot, or change the active filters."}
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="grid gap-3 md:hidden">
        {documents.map((document) => (
          <Link
            key={document.id}
            href={`/documents/${document.id}`}
            className="rounded-lg border p-3 transition-colors hover:bg-muted/30"
          >
            <div className="flex items-start gap-3">
              <div className="rounded-md bg-muted p-2">
                <FileText className="size-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <p className="truncate font-medium">{document.filename}</p>
                  <Badge variant={statusVariant(document.status)}>
                    {statusLabel(document.status, zh)}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  {document.document_type || (zh ? "未分类" : "Unclassified")} ·{" "}
                  {document.page_count} {zh ? "页" : "pages"} ·{" "}
                  {formatBytes(document.size_bytes)}
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {new Date(document.updated_at).toLocaleString()}
                </p>
              </div>
            </div>
          </Link>
        ))}
      </div>

      <div className="hidden overflow-x-auto rounded-lg border md:block">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/35 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">
                {zh ? "文档" : "Document"}
              </th>
              <th className="px-4 py-3 font-medium">
                {zh ? "类型" : "Type"}
              </th>
              <th className="px-4 py-3 font-medium">
                {zh ? "页数 / 大小" : "Pages / size"}
              </th>
              <th className="px-4 py-3 font-medium">
                {zh ? "状态" : "Status"}
              </th>
              <th className="px-4 py-3 font-medium">
                {zh ? "更新时间" : "Updated"}
              </th>
              <th className="px-4 py-3 text-right font-medium">
                {zh ? "动作" : "Action"}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {documents.map((document) => (
              <tr key={document.id} className="hover:bg-muted/20">
                <td className="max-w-xs px-4 py-3">
                  <div className="flex items-center gap-2">
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <span className="truncate font-medium">
                      {document.filename}
                    </span>
                  </div>
                </td>
                <td className="px-4 py-3 text-muted-foreground">
                  {document.document_type || (zh ? "未分类" : "Unclassified")}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                  {document.page_count} {zh ? "页" : "pages"} ·{" "}
                  {formatBytes(document.size_bytes)}
                </td>
                <td className="px-4 py-3">
                  <Badge variant={statusVariant(document.status)}>
                    {statusLabel(document.status, zh)}
                  </Badge>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                  {new Date(document.updated_at).toLocaleString()}
                </td>
                <td className="px-4 py-3 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    render={<Link href={`/documents/${document.id}`} />}
                  >
                    {zh ? "查看详情" : "Review"}
                    <ArrowUpRight className="size-3" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
