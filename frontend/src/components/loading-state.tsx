import { Loader2 } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

interface LoadingSpinnerProps {
  label: string;
  className?: string;
  iconClassName?: string;
  showLabel?: boolean;
}

function LoadingSpinner({
  label,
  className,
  iconClassName,
  showLabel = false,
}: LoadingSpinnerProps) {
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn("inline-flex items-center gap-2", className)}
    >
      <Loader2
        aria-hidden="true"
        className={cn(
          "h-4 w-4 shrink-0 animate-spin motion-reduce:animate-none",
          iconClassName,
        )}
      />
      <span className={showLabel ? undefined : "sr-only"}>{label}</span>
    </span>
  );
}

function InlineLoading({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex items-center gap-2 rounded-lg border border-border/70 bg-muted/45 px-3 py-2 text-sm text-muted-foreground",
        className,
      )}
    >
      <LoadingSpinner label={label} />
      <span>{label}</span>
    </div>
  );
}

function TableSkeleton({
  columns = 4,
  rows = 5,
  label = "Loading table",
  className,
}: {
  columns?: number;
  rows?: number;
  label?: string;
  className?: string;
}) {
  const gridStyle = {
    gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
  };

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className={cn("overflow-hidden rounded-lg border", className)}
    >
      <span className="sr-only">{label}</span>
      <div
        aria-hidden="true"
        className="grid gap-4 border-b bg-muted/35 px-4 py-3"
        style={gridStyle}
      >
        {Array.from({ length: columns }).map((_, index) => (
          <Skeleton
            key={`heading-${index}`}
            className={cn("h-3", index === 0 ? "w-24" : "ml-auto w-16")}
          />
        ))}
      </div>
      <div aria-hidden="true" className="divide-y">
        {Array.from({ length: rows }).map((_, rowIndex) => (
          <div
            key={`row-${rowIndex}`}
            className="grid items-center gap-4 px-4 py-3.5"
            style={gridStyle}
          >
            {Array.from({ length: columns }).map((__, columnIndex) => (
              <Skeleton
                key={`cell-${rowIndex}-${columnIndex}`}
                className={cn(
                  "h-3.5",
                  columnIndex === 0
                    ? rowIndex % 2 === 0
                      ? "w-32"
                      : "w-24"
                    : "ml-auto w-16",
                )}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function ListSkeleton({
  rows = 4,
  label = "Loading list",
  compact = false,
  className,
}: {
  rows?: number;
  label?: string;
  compact?: boolean;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className={cn("space-y-2", className)}
    >
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          aria-hidden="true"
          className={cn(
            "flex items-center justify-between gap-4 rounded-lg border border-border/60",
            compact ? "px-3 py-2.5" : "p-3",
          )}
        >
          <div className="min-w-0 flex-1 space-y-2">
            <Skeleton className={cn("h-3.5", index % 2 === 0 ? "w-2/3" : "w-1/2")} />
            <Skeleton className="h-3 w-1/3" />
          </div>
          <Skeleton className="h-6 w-14 rounded-full" />
        </div>
      ))}
    </div>
  );
}

function ChartSkeleton({
  label = "Loading chart",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className={cn(
        "relative flex h-64 items-end gap-3 overflow-hidden rounded-lg border border-border/50 bg-muted/15 px-5 pb-5 pt-8",
        className,
      )}
    >
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="absolute inset-x-5 top-5 space-y-12">
        {Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="border-t border-dashed border-border/70" />
        ))}
      </div>
      {["45%", "68%", "54%", "82%", "62%", "74%", "58%"].map(
        (height, index) => (
          <Skeleton
            key={index}
            aria-hidden="true"
            className="relative flex-1 rounded-t-md rounded-b-sm"
            style={{ height }}
          />
        ),
      )}
    </div>
  );
}

export {
  ChartSkeleton,
  InlineLoading,
  ListSkeleton,
  LoadingSpinner,
  TableSkeleton,
};
