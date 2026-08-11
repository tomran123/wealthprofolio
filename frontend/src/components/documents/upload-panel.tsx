"use client";

import {
  CheckCircle2,
  FileImage,
  FileText,
  LoaderCircle,
  ShieldCheck,
  UploadCloud,
  X,
  XCircle,
} from "lucide-react";
import {
  DragEvent,
  useId,
  useRef,
  useState,
} from "react";

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  documentApi,
  documentContentType,
  isAcceptedDocument,
  sha256File,
  uploadDocumentContent,
} from "@/lib/documents";
import { cn } from "@/lib/utils";
import type {
  AccountWithNames,
  BackgroundJob,
  DocumentSummary,
  Institution,
  Owner,
} from "@/lib/types";

type UploadStep =
  | "waiting"
  | "hashing"
  | "preparing"
  | "uploading"
  | "queueing"
  | "queued"
  | "duplicate"
  | "failed";

interface UploadEntry {
  key: string;
  file: File;
  step: UploadStep;
  progress: number;
  error: string | null;
}

interface UploadMetadata {
  documentType: string;
  documentDate: string;
  ownerId: string;
  institutionId: string;
  accountId: string;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function entryLabel(step: UploadStep, zh: boolean): string {
  const labels: Record<UploadStep, [string, string]> = {
    waiting: ["等待上传", "Waiting"],
    hashing: ["生成安全摘要", "Hashing"],
    preparing: ["创建上传凭证", "Preparing"],
    uploading: ["上传加密文件", "Uploading"],
    queueing: ["提交处理队列", "Queueing"],
    queued: ["已进入处理队列", "Queued"],
    duplicate: ["已识别重复文件", "Duplicate found"],
    failed: ["上传失败", "Upload failed"],
  };
  return zh ? labels[step][0] : labels[step][1];
}

export function UploadPanel({
  zh,
  owners,
  institutions,
  accounts,
  onQueued,
}: {
  zh: boolean;
  owners: Owner[];
  institutions: Institution[];
  accounts: AccountWithNames[];
  onQueued: (document: DocumentSummary, job: BackgroundJob) => void;
}) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [entries, setEntries] = useState<UploadEntry[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<UploadMetadata>({
    documentType: "statement",
    documentDate: "",
    ownerId: "",
    institutionId: "",
    accountId: "",
  });

  const updateEntry = (
    key: string,
    update: Partial<Omit<UploadEntry, "key" | "file">>,
  ) => {
    setEntries((current) =>
      current.map((entry) =>
        entry.key === key ? { ...entry, ...update } : entry,
      ),
    );
  };

  const selectFiles = (files: File[]) => {
    const accepted = files.filter(isAcceptedDocument);
    const rejected = files.length - accepted.length;
    setSelectionError(
      rejected > 0
        ? zh
          ? `${rejected} 个文件格式不受支持。仅接受 PDF、JPEG、PNG 或 WebP。`
          : `${rejected} file(s) were rejected. Use PDF, JPEG, PNG, or WebP.`
        : null,
    );

    if (accepted.length === 0) {
      return;
    }

    setEntries((current) => {
      const existing = new Set(
        current.map(({ file }) => `${file.name}:${file.size}:${file.lastModified}`),
      );
      const next = accepted
        .filter(
          (file) =>
            !existing.has(`${file.name}:${file.size}:${file.lastModified}`),
        )
        .map((file) => ({
          key: window.crypto.randomUUID(),
          file,
          step: "waiting" as const,
          progress: 0,
          error: null,
        }));
      return [...current, ...next];
    });
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    selectFiles(Array.from(event.dataTransfer.files));
  };

  const uploadAll = async () => {
    const waiting = entries.filter(
      ({ step }) => step === "waiting" || step === "failed",
    );
    if (waiting.length === 0 || isUploading) {
      return;
    }

    setIsUploading(true);
    for (const entry of waiting) {
      try {
        updateEntry(entry.key, {
          step: "hashing",
          progress: 10,
          error: null,
        });
        const sha256 = await sha256File(entry.file);

        updateEntry(entry.key, { step: "preparing", progress: 25 });
        const intent = await documentApi.createUploadIntent({
          filename: entry.file.name,
          content_type: documentContentType(entry.file),
          size_bytes: entry.file.size,
          sha256,
          document_type: metadata.documentType || undefined,
          document_date: metadata.documentDate || undefined,
          owner_id: metadata.ownerId || undefined,
          institution_id: metadata.institutionId || undefined,
          account_id: metadata.accountId || undefined,
        });

        if (intent.upload) {
          updateEntry(entry.key, { step: "uploading", progress: 55 });
          await uploadDocumentContent(intent, entry.file);
        }

        updateEntry(entry.key, { step: "queueing", progress: 82 });
        const completed = await documentApi.completeUpload(intent.document_id, {
          upload_token: intent.upload_token,
          sha256,
        });
        updateEntry(entry.key, {
          step: intent.duplicate ? "duplicate" : "queued",
          progress: 100,
        });
        onQueued(completed.document, completed.job);
      } catch (error) {
        updateEntry(entry.key, {
          step: "failed",
          error:
            error instanceof Error
              ? error.message
              : zh
                ? "上传失败，请重试。"
                : "Upload failed. Please retry.",
        });
      }
    }
    setIsUploading(false);
  };

  const selectedAccount = accounts.find(
    (account) => account.id === metadata.accountId,
  );

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.15fr)_minmax(300px,0.85fr)]">
      <div className="space-y-4">
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              inputRef.current?.click();
            }
          }}
          onDragEnter={(event) => {
            event.preventDefault();
            setIsDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => {
            if (event.currentTarget === event.target) {
              setIsDragging(false);
            }
          }}
          onDrop={onDrop}
          className={cn(
            "flex min-h-56 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            isDragging
              ? "border-primary bg-primary/5"
              : "border-border bg-muted/15 hover:border-primary/50 hover:bg-muted/30",
          )}
          aria-label={zh ? "选择或拖放文档上传" : "Choose or drop documents"}
        >
          <div className="rounded-2xl bg-primary/10 p-3 text-primary">
            <UploadCloud className="size-7" />
          </div>
          <p className="mt-4 font-medium">
            {zh ? "拖放账单或截图到这里" : "Drop statements or screenshots here"}
          </p>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            {zh
              ? "支持 PDF、JPEG、PNG、WebP；可一次选择多个文件。文件会先经过安全检查，再进入 OCR 与索引。"
              : "PDF, JPEG, PNG, and WebP are supported. Files are security-checked before OCR and indexing."}
          </p>
          <Button type="button" variant="outline" className="mt-4">
            {zh ? "选择文件" : "Choose files"}
          </Button>
          <input
            ref={inputRef}
            id={inputId}
            type="file"
            className="sr-only"
            accept=".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp"
            multiple
            onChange={(event) => {
              selectFiles(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
        </div>

        {selectionError && (
          <Alert variant="destructive">
            <XCircle />
            <AlertTitle>
              {zh ? "部分文件未加入" : "Some files were not added"}
            </AlertTitle>
            <AlertDescription>{selectionError}</AlertDescription>
          </Alert>
        )}

        {entries.length > 0 && (
          <div className="space-y-2" aria-live="polite">
            {entries.map((entry) => (
              <div
                key={entry.key}
                className="rounded-lg border bg-card p-3"
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 rounded-md bg-muted p-2">
                    {entry.file.type === "application/pdf" ? (
                      <FileText className="size-4" />
                    ) : (
                      <FileImage className="size-4" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">
                          {entry.file.name}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatBytes(entry.file.size)}
                        </p>
                      </div>
                      {entry.step === "waiting" && !isUploading ? (
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="ghost"
                          onClick={() =>
                            setEntries((current) =>
                              current.filter(
                                (candidate) => candidate.key !== entry.key,
                              ),
                            )
                          }
                          aria-label={
                            zh ? `移除 ${entry.file.name}` : `Remove ${entry.file.name}`
                          }
                        >
                          <X className="size-4" />
                        </Button>
                      ) : entry.step === "failed" ? (
                        <XCircle className="size-4 text-destructive" />
                      ) : entry.step === "queued" ||
                        entry.step === "duplicate" ? (
                        <CheckCircle2 className="size-4 text-emerald-600" />
                      ) : (
                        <LoaderCircle className="size-4 animate-spin text-primary" />
                      )}
                    </div>
                    <div className="mt-2 flex items-center justify-between gap-3">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                        <div
                          className={cn(
                            "h-full rounded-full transition-[width] duration-300",
                            entry.step === "failed"
                              ? "bg-destructive"
                              : "bg-primary",
                          )}
                          style={{ width: `${entry.progress}%` }}
                        />
                      </div>
                      <span className="min-w-max text-xs text-muted-foreground">
                        {entryLabel(entry.step, zh)}
                      </span>
                    </div>
                    {entry.error && (
                      <p className="mt-2 text-xs text-destructive">
                        {entry.error}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-4 rounded-xl border bg-muted/15 p-4 sm:p-5">
        <div>
          <h3 className="font-medium">
            {zh ? "文档归类（可选）" : "Document context (optional)"}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {zh
              ? "提前关联范围可提高抽取准确度，后续仍可在详情中核验。"
              : "Adding context can improve extraction accuracy and remains reviewable."}
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor={`${inputId}-type`}>
            {zh ? "文档类型" : "Document type"}
          </Label>
          <select
            id={`${inputId}-type`}
            value={metadata.documentType}
            onChange={(event) =>
              setMetadata((current) => ({
                ...current,
                documentType: event.target.value,
              }))
            }
            className="h-9 w-full rounded-md border bg-background px-3 text-sm"
          >
            <option value="statement">
              {zh ? "账户月结单" : "Account statement"}
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
              {zh ? "应用截图" : "App screenshot"}
            </option>
            <option value="other">{zh ? "其他" : "Other"}</option>
          </select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor={`${inputId}-date`}>
            {zh ? "文档日期" : "Document date"}
          </Label>
          <Input
            id={`${inputId}-date`}
            type="date"
            value={metadata.documentDate}
            onChange={(event) =>
              setMetadata((current) => ({
                ...current,
                documentDate: event.target.value,
              }))
            }
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor={`${inputId}-account`}>
            {zh ? "关联账户" : "Account"}
          </Label>
          <select
            id={`${inputId}-account`}
            value={metadata.accountId}
            onChange={(event) => {
              const account = accounts.find(
                (candidate) => candidate.id === event.target.value,
              );
              setMetadata((current) => ({
                ...current,
                accountId: event.target.value,
                ownerId: account?.owner_id ?? current.ownerId,
                institutionId:
                  account?.institution_id ?? current.institutionId,
              }));
            }}
            className="h-9 w-full rounded-md border bg-background px-3 text-sm"
          >
            <option value="">{zh ? "暂不关联" : "Not linked"}</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {account.name} · {account.institution_name}
              </option>
            ))}
          </select>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor={`${inputId}-owner`}>
              {zh ? "持有人" : "Owner"}
            </Label>
            <select
              id={`${inputId}-owner`}
              value={metadata.ownerId}
              onChange={(event) =>
                setMetadata((current) => ({
                  ...current,
                  ownerId: event.target.value,
                }))
              }
              className="h-9 w-full rounded-md border bg-background px-3 text-sm"
            >
              <option value="">{zh ? "未指定" : "Unspecified"}</option>
              {owners.map((owner) => (
                <option key={owner.id} value={owner.id}>
                  {owner.name}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`${inputId}-institution`}>
              {zh ? "金融机构" : "Institution"}
            </Label>
            <select
              id={`${inputId}-institution`}
              value={metadata.institutionId}
              onChange={(event) =>
                setMetadata((current) => ({
                  ...current,
                  institutionId: event.target.value,
                }))
              }
              className="h-9 w-full rounded-md border bg-background px-3 text-sm"
            >
              <option value="">{zh ? "未指定" : "Unspecified"}</option>
              {institutions.map((institution) => (
                <option key={institution.id} value={institution.id}>
                  {institution.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {selectedAccount && (
          <div className="rounded-lg border bg-background p-3 text-xs text-muted-foreground">
            {zh ? "已自动关联" : "Auto-linked"}:{" "}
            <span className="font-medium text-foreground">
              {selectedAccount.owner_name} ·{" "}
              {selectedAccount.institution_name}
            </span>
          </div>
        )}

        <div className="flex items-start gap-2 rounded-lg bg-emerald-500/8 p-3 text-xs text-emerald-800">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" />
          <p>
            {zh
              ? "上传只创建待处理文档。OCR 结果和交易草案绝不会自动写入账本，必须由你确认。"
              : "Upload only creates a document. OCR results and transaction drafts never post automatically; your confirmation is required."}
          </p>
        </div>

        <Button
          type="button"
          className="w-full"
          onClick={() => void uploadAll()}
          disabled={
            isUploading ||
            !entries.some(
              ({ step }) => step === "waiting" || step === "failed",
            )
          }
        >
          {isUploading ? (
            <LoaderCircle className="size-4 animate-spin" />
          ) : (
            <UploadCloud className="size-4" />
          )}
          {isUploading
            ? zh
              ? "上传并排队中…"
              : "Uploading and queueing…"
            : zh
              ? `上传 ${entries.filter(({ step }) => step === "waiting" || step === "failed").length} 个文件`
              : `Upload ${entries.filter(({ step }) => step === "waiting" || step === "failed").length} file(s)`}
        </Button>
        <div className="flex flex-wrap gap-1.5">
          {["PDF", "JPEG", "PNG", "WebP"].map((format) => (
            <Badge key={format} variant="outline">
              {format}
            </Badge>
          ))}
        </div>
      </div>
    </div>
  );
}
