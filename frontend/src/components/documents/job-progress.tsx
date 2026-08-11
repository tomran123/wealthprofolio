"use client";

import {
  Check,
  Circle,
  LoaderCircle,
  RefreshCw,
  Wifi,
  WifiOff,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { BackgroundJob } from "@/lib/types";

import {
  isTerminalJob,
  type JobTransport,
  useJobMonitor,
} from "./use-job-monitor";

const STAGES = [
  { key: "validate", zh: "安全检查", en: "Validate" },
  { key: "paginate", zh: "文档分页", en: "Pages" },
  { key: "ocr", zh: "OCR", en: "OCR" },
  { key: "vision", zh: "结构化抽取", en: "Extract" },
  { key: "chunk", zh: "文本切片", en: "Chunk" },
  { key: "embed", zh: "向量化", en: "Embed" },
  { key: "index", zh: "建立索引", en: "Index" },
] as const;

function stageIndex(stage: string | null, progress: number): number {
  if (!stage) {
    return Math.max(
      0,
      Math.min(STAGES.length - 1, Math.floor(progress * STAGES.length)),
    );
  }

  const normalized = stage.toLowerCase();
  const direct = STAGES.findIndex(({ key }) => normalized.includes(key));
  if (direct >= 0) {
    return direct;
  }
  if (normalized.includes("security") || normalized.includes("virus")) {
    return 0;
  }
  if (normalized.includes("page")) {
    return 1;
  }
  if (normalized.includes("extract")) {
    return 3;
  }
  if (normalized.includes("complete") || normalized.includes("done")) {
    return STAGES.length - 1;
  }
  return Math.max(
    0,
    Math.min(STAGES.length - 1, Math.floor(progress * STAGES.length)),
  );
}

function normalizedProgress(value: number): number {
  const percentage = value <= 1 ? value * 100 : value;
  return Math.round(Math.max(0, Math.min(100, percentage)));
}

function TransportBadge({
  transport,
  zh,
}: {
  transport: JobTransport;
  zh: boolean;
}) {
  if (transport === "websocket") {
    return (
      <Badge variant="outline" className="gap-1 text-emerald-700">
        <Wifi className="size-3" />
        {zh ? "实时" : "Live"}
      </Badge>
    );
  }
  if (transport === "polling") {
    return (
      <Badge variant="outline" className="gap-1 text-amber-700">
        <WifiOff className="size-3" />
        {zh ? "轮询回退" : "Polling"}
      </Badge>
    );
  }
  if (transport === "complete") {
    return null;
  }
  return (
    <Badge variant="outline" className="gap-1 text-muted-foreground">
      <RefreshCw className="size-3 animate-spin" />
      {zh ? "连接中" : "Connecting"}
    </Badge>
  );
}

export function JobProgress({
  job,
  transport,
  zh,
  compact = false,
  error,
}: {
  job: BackgroundJob | null;
  transport: JobTransport;
  zh: boolean;
  compact?: boolean;
  error?: string | null;
}) {
  const progress = normalizedProgress(job?.progress ?? 0);
  const activeStage = stageIndex(job?.stage ?? null, progress / 100);
  const failed = job?.status === "failed";
  const cancelled = job?.status === "cancelled";
  const succeeded = job?.status === "succeeded";

  return (
    <div className="space-y-3" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <div className="flex min-w-0 items-center gap-2">
          {failed || cancelled ? (
            <XCircle className="size-4 shrink-0 text-destructive" />
          ) : succeeded ? (
            <Check className="size-4 shrink-0 text-emerald-600" />
          ) : (
            <LoaderCircle className="size-4 shrink-0 animate-spin text-primary" />
          )}
          <span className="truncate font-medium">
            {failed
              ? zh
                ? "处理失败"
                : "Processing failed"
              : cancelled
                ? zh
                  ? "任务已取消"
                  : "Job cancelled"
                : succeeded
                  ? zh
                    ? "文档已就绪"
                    : "Document ready"
                  : job?.message ||
                    (zh ? "正在准备文档…" : "Preparing document…")}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <TransportBadge transport={transport} zh={zh} />
          <span className="tabular-nums text-muted-foreground">
            {progress}%
          </span>
        </div>
      </div>

      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={zh ? "文档处理进度" : "Document processing progress"}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500",
            failed ? "bg-destructive" : "bg-primary",
          )}
          style={{ width: `${progress}%` }}
        />
      </div>

      {!compact && (
        <ol className="flex gap-1 overflow-x-auto pb-1">
          {STAGES.map((stage, index) => {
            const complete = succeeded || index < activeStage;
            const active = !isTerminalJob(job) && index === activeStage;
            return (
              <li
                key={stage.key}
                className={cn(
                  "flex min-w-max flex-1 items-center gap-1.5 rounded-md px-2 py-1 text-[11px]",
                  active && "bg-primary/10 font-medium text-primary",
                  complete && "text-emerald-700",
                  !active && !complete && "text-muted-foreground",
                )}
              >
                {complete ? (
                  <Check className="size-3" />
                ) : active ? (
                  <LoaderCircle className="size-3 animate-spin" />
                ) : (
                  <Circle className="size-3" />
                )}
                {zh ? stage.zh : stage.en}
              </li>
            );
          })}
        </ol>
      )}

      {(job?.error || error) && (
        <p className="text-xs text-destructive">{job?.error || error}</p>
      )}
    </div>
  );
}

export function MonitoredJobProgress({
  jobId,
  zh,
  compact,
  onTerminal,
}: {
  jobId: string;
  zh: boolean;
  compact?: boolean;
  onTerminal?: (job: BackgroundJob) => void;
}) {
  const monitor = useJobMonitor(jobId, onTerminal);
  return (
    <JobProgress
      job={monitor.job}
      transport={monitor.transport}
      error={monitor.error}
      zh={zh}
      compact={compact}
    />
  );
}
