"use client";

import { useEffect, useRef, useState } from "react";

import { documentApi, jobWebSocketUrl } from "@/lib/documents";
import type {
  BackgroundJob,
  BackgroundJobStatus,
  JobSnapshotEvent,
} from "@/lib/types";

export type JobTransport =
  | "connecting"
  | "websocket"
  | "polling"
  | "complete";

const TERMINAL_STATUSES = new Set<BackgroundJobStatus>([
  "succeeded",
  "failed",
  "cancelled",
]);

export function isTerminalJob(job: BackgroundJob | null): boolean {
  return Boolean(job && TERMINAL_STATUSES.has(job.status));
}

export function useJobMonitor(
  jobId: string,
  onTerminal?: (job: BackgroundJob) => void,
) {
  const [job, setJob] = useState<BackgroundJob | null>(null);
  const [connection, setConnection] = useState<{
    jobId: string;
    transport: JobTransport;
  }>({ jobId: "", transport: "connecting" });
  const [monitorError, setMonitorError] = useState<{
    jobId: string;
    message: string;
  } | null>(null);
  const onTerminalRef = useRef(onTerminal);

  useEffect(() => {
    onTerminalRef.current = onTerminal;
  }, [onTerminal]);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let pollingTimer: number | null = null;
    let reconnectTimer: number | null = null;
    let currentStatus: BackgroundJobStatus | null = null;
    let terminalNotified = false;
    let reconnectAttempt = 0;

    const clearPollingTimer = () => {
      if (pollingTimer !== null) {
        window.clearTimeout(pollingTimer);
        pollingTimer = null;
      }
    };

    const clearReconnectTimer = () => {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    const applySnapshot = (snapshot: BackgroundJob) => {
      if (disposed) {
        return;
      }

      currentStatus = snapshot.status;
      setJob(snapshot);
      setMonitorError(null);

      if (TERMINAL_STATUSES.has(snapshot.status)) {
        clearPollingTimer();
        clearReconnectTimer();
        setConnection({ jobId, transport: "complete" });
        socket?.close(1000, "job complete");
        if (!terminalNotified) {
          terminalNotified = true;
          onTerminalRef.current?.(snapshot);
        }
      }
    };

    const schedulePoll = () => {
      if (
        disposed ||
        (currentStatus !== null && TERMINAL_STATUSES.has(currentStatus)) ||
        pollingTimer !== null
      ) {
        return;
      }

      setConnection({ jobId, transport: "polling" });
      pollingTimer = window.setTimeout(async () => {
        pollingTimer = null;
        try {
          applySnapshot(await documentApi.job(jobId));
        } catch (pollError) {
          if (!disposed) {
            setMonitorError({
              jobId,
              message:
                pollError instanceof Error
                  ? pollError.message
                  : "Unable to refresh job status",
            });
          }
        } finally {
          schedulePoll();
        }
      }, 2_000);
    };

    const scheduleReconnect = () => {
      if (
        disposed ||
        reconnectTimer !== null ||
        (currentStatus !== null && TERMINAL_STATUSES.has(currentStatus))
      ) {
        return;
      }

      const delay = Math.min(15_000, 1_500 * 2 ** reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connect();
      }, delay);
    };

    const connect = () => {
      if (
        disposed ||
        (currentStatus !== null && TERMINAL_STATUSES.has(currentStatus))
      ) {
        return;
      }

      try {
        socket = new WebSocket(jobWebSocketUrl(jobId));
      } catch {
        schedulePoll();
        scheduleReconnect();
        return;
      }

      socket.addEventListener("open", () => {
        if (disposed) {
          return;
        }
        reconnectAttempt = 0;
        clearPollingTimer();
        setConnection({ jobId, transport: "websocket" });
        setMonitorError(null);
      });

      socket.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(String(event.data)) as JobSnapshotEvent;
          if (payload.type === "job.snapshot" && payload.job?.id === jobId) {
            applySnapshot(payload.job);
          }
        } catch {
          setMonitorError({
            jobId,
            message: "Received an invalid job update",
          });
        }
      });

      socket.addEventListener("error", () => {
        if (!disposed) {
          schedulePoll();
        }
      });

      socket.addEventListener("close", () => {
        if (
          !disposed &&
          (currentStatus === null || !TERMINAL_STATUSES.has(currentStatus))
        ) {
          schedulePoll();
          scheduleReconnect();
        }
      });
    };

    void documentApi
      .job(jobId)
      .then(applySnapshot)
      .catch((initialError: unknown) => {
        if (!disposed) {
          setMonitorError({
            jobId,
            message:
              initialError instanceof Error
                ? initialError.message
                : "Unable to load job status",
          });
          schedulePoll();
        }
      });
    connect();

    return () => {
      disposed = true;
      clearPollingTimer();
      clearReconnectTimer();
      socket?.close(1000, "component unmounted");
    };
  }, [jobId]);

  const visibleJob = job?.id === jobId ? job : null;
  return {
    job: visibleJob,
    transport:
      connection.jobId === jobId ? connection.transport : "connecting",
    error: monitorError?.jobId === jobId ? monitorError.message : null,
    isLoading: !visibleJob,
  };
}
