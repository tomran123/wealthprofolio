import { api } from "@/lib/api";
import type {
  BackgroundJob,
  BackgroundJobStatus,
  JobSnapshotEvent,
} from "@/lib/types";

const TERMINAL_STATUSES = new Set<BackgroundJobStatus>([
  "succeeded",
  "failed",
  "cancelled",
]);

const STATUS_RANK: Record<BackgroundJobStatus, number> = {
  pending: 0,
  queued: 1,
  running: 2,
  succeeded: 3,
  failed: 3,
  cancelled: 3,
};

export type BackgroundJobTransport =
  | "connecting"
  | "websocket"
  | "polling";

export interface WaitForBackgroundJobOptions<TResult> {
  onUpdate?: (job: BackgroundJob<TResult>) => void;
  onTransportChange?: (transport: BackgroundJobTransport) => void;
  timeoutMs?: number;
  pollIntervalMs?: number;
  signal?: AbortSignal;
}

export class BackgroundJobTimeoutError<TResult> extends Error {
  readonly jobId: string;
  readonly lastJob: BackgroundJob<TResult>;

  constructor(job: BackgroundJob<TResult>) {
    super("background_job_timeout");
    this.name = "BackgroundJobTimeoutError";
    this.jobId = job.id;
    this.lastJob = job;
  }
}

export class BackgroundJobFailedError<TResult> extends Error {
  readonly job: BackgroundJob<TResult>;

  constructor(job: BackgroundJob<TResult>) {
    super(job.error || `background_job_${job.status}`);
    this.name = "BackgroundJobFailedError";
    this.job = job;
  }
}

export function backgroundJobWebSocketUrl(jobId: string): string {
  const configuredApi = process.env.NEXT_PUBLIC_API_BASE_URL;
  const base = configuredApi
    ? new URL(configuredApi, window.location.origin)
    : new URL(window.location.origin);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = `/api/v1/ws/jobs/${encodeURIComponent(jobId)}`;
  base.search = "";
  base.hash = "";
  return base.toString();
}

function isNewerSnapshot<TResult>(
  candidate: BackgroundJob<TResult>,
  current: BackgroundJob<TResult>,
): boolean {
  if (candidate.id !== current.id) {
    return false;
  }

  const candidateRank = STATUS_RANK[candidate.status];
  const currentRank = STATUS_RANK[current.status];
  if (candidateRank < currentRank) {
    return false;
  }
  if (candidateRank > currentRank) {
    return true;
  }

  const candidateUpdatedAt = Date.parse(candidate.updated_at);
  const currentUpdatedAt = Date.parse(current.updated_at);
  if (
    Number.isFinite(candidateUpdatedAt) &&
    Number.isFinite(currentUpdatedAt) &&
    candidateUpdatedAt < currentUpdatedAt
  ) {
    return false;
  }

  return candidate.progress >= current.progress;
}

export function waitForBackgroundJob<TResult = Record<string, unknown>>(
  initial: BackgroundJob<TResult>,
  options: WaitForBackgroundJobOptions<TResult> = {},
): Promise<BackgroundJob<TResult>> {
  const {
    onUpdate,
    onTransportChange,
    timeoutMs = 5 * 60 * 1000,
    pollIntervalMs = 1_500,
    signal,
  } = options;

  return new Promise((resolve, reject) => {
    let settled = false;
    let latest = initial;
    let socket: WebSocket | null = null;
    let pollTimer: number | null = null;
    let timeoutTimer: number | null = null;
    let websocketHandshakeTimer: number | null = null;
    let polling = false;
    let transport: BackgroundJobTransport | null = null;

    const setTransport = (next: BackgroundJobTransport) => {
      if (transport === next || settled) {
        return;
      }
      transport = next;
      onTransportChange?.(next);
    };

    const stopPolling = () => {
      polling = false;
      if (pollTimer !== null) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
      }
    };

    const cleanup = () => {
      stopPolling();
      if (timeoutTimer !== null) {
        window.clearTimeout(timeoutTimer);
        timeoutTimer = null;
      }
      if (websocketHandshakeTimer !== null) {
        window.clearTimeout(websocketHandshakeTimer);
        websocketHandshakeTimer = null;
      }
      signal?.removeEventListener("abort", abortTracking);
      if (socket && socket.readyState < WebSocket.CLOSING) {
        try {
          socket.close(1000, "job tracking complete");
        } catch {
          // Some browsers reject close() while the socket is still connecting.
        }
      }
    };

    const fail = (error: Error) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(error);
    };

    const complete = (job: BackgroundJob<TResult>) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      if (job.status === "succeeded") {
        resolve(job);
      } else {
        reject(new BackgroundJobFailedError(job));
      }
    };

    const accept = (
      job: BackgroundJob<TResult>,
      { force = false }: { force?: boolean } = {},
    ) => {
      if (settled || job.id !== initial.id) {
        return;
      }
      if (!force && !isNewerSnapshot(job, latest)) {
        return;
      }
      latest = job;
      onUpdate?.(job);
      if (TERMINAL_STATUSES.has(job.status)) {
        complete(job);
      }
    };

    const schedulePoll = () => {
      if (!polling || settled || pollTimer !== null) {
        return;
      }
      pollTimer = window.setTimeout(() => {
        pollTimer = null;
        void poll();
      }, pollIntervalMs);
    };

    const poll = async () => {
      if (!polling || settled) {
        return;
      }
      try {
        accept(
          await api.get<BackgroundJob<TResult>>(
            `/api/v1/jobs/${encodeURIComponent(initial.id)}`,
          ),
        );
      } catch {
        // A transient GET failure does not fail the durable server-side job.
      } finally {
        schedulePoll();
      }
    };

    const startPolling = () => {
      if (polling || settled) {
        return;
      }
      polling = true;
      setTransport("polling");
      void poll();
    };

    function abortTracking() {
      fail(new DOMException("Background job tracking aborted", "AbortError"));
    }

    onUpdate?.(initial);
    if (TERMINAL_STATUSES.has(initial.status)) {
      complete(initial);
      return;
    }

    if (signal?.aborted) {
      abortTracking();
      return;
    }
    signal?.addEventListener("abort", abortTracking, { once: true });

    timeoutTimer = window.setTimeout(() => {
      fail(new BackgroundJobTimeoutError(latest));
    }, timeoutMs);

    setTransport("connecting");
    try {
      socket = new WebSocket(backgroundJobWebSocketUrl(initial.id));
      websocketHandshakeTimer = window.setTimeout(startPolling, 3_000);

      socket.addEventListener("open", () => {
        setTransport("websocket");
      });
      socket.addEventListener("message", (event) => {
        try {
          const snapshot = JSON.parse(
            String(event.data),
          ) as JobSnapshotEvent<TResult>;
          if (
            snapshot.type !== "job.snapshot" ||
            snapshot.job?.id !== initial.id
          ) {
            return;
          }
          if (websocketHandshakeTimer !== null) {
            window.clearTimeout(websocketHandshakeTimer);
            websocketHandshakeTimer = null;
          }
          stopPolling();
          setTransport("websocket");
          accept(snapshot.job);
        } catch {
          startPolling();
        }
      });
      socket.addEventListener("error", startPolling);
      socket.addEventListener("close", () => {
        if (!settled) {
          startPolling();
        }
      });
    } catch {
      startPolling();
    }
  });
}
