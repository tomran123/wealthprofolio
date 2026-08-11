import { api, ApiError, csrfHeaders } from "@/lib/api";
import type {
  BackgroundJob,
  DocumentCompleteResult,
  DocumentContentReceipt,
  DocumentDetail,
  DocumentPageResult,
  DocumentTransactionDraft,
  DocumentUploadIntent,
  DocumentUploadIntentInput,
  KnowledgeQueryInput,
  KnowledgeQueryResult,
  KnowledgeSearchInput,
  KnowledgeSearchResult,
} from "@/lib/types";

export const ACCEPTED_DOCUMENT_TYPES = [
  "application/pdf",
  "image/jpeg",
  "image/png",
  "image/webp",
] as const;

const ACCEPTED_TYPE_SET = new Set<string>(ACCEPTED_DOCUMENT_TYPES);
const ACCEPTED_EXTENSIONS = new Set(["pdf", "jpg", "jpeg", "png", "webp"]);
const CONTENT_TYPE_BY_EXTENSION: Record<string, string> = {
  pdf: "application/pdf",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
};

export function isAcceptedDocument(file: File): boolean {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return (
    ACCEPTED_EXTENSIONS.has(extension) &&
    (!file.type || ACCEPTED_TYPE_SET.has(file.type))
  );
}

export function documentContentType(file: File): string {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  return file.type || CONTENT_TYPE_BY_EXTENSION[extension] || "";
}

export async function sha256File(file: File): Promise<string> {
  const digest = await window.crypto.subtle.digest(
    "SHA-256",
    await file.arrayBuffer(),
  );
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function errorFromResponse(response: Response): Promise<ApiError> {
  let detail = response.statusText || `HTTP ${response.status}`;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      detail = payload.detail;
    }
  } catch {
    // OSS and other object stores may return an empty or non-JSON error body.
  }
  return new ApiError(response.status, detail);
}

export async function uploadDocumentContent(
  intent: DocumentUploadIntent,
  file: File,
): Promise<DocumentContentReceipt | null> {
  if (!intent.upload) {
    return null;
  }

  const url = new URL(intent.upload.url, window.location.origin);
  const sameOrigin = url.origin === window.location.origin;
  const response = await fetch(url, {
    method: intent.upload.method,
    body: file,
    credentials: sameOrigin ? "include" : "omit",
    headers: {
      "Content-Type": documentContentType(file),
      ...intent.upload.headers,
      ...(sameOrigin ? csrfHeaders() : {}),
    },
  });

  if (!response.ok) {
    throw await errorFromResponse(response);
  }

  if (!sameOrigin || response.status === 204) {
    return null;
  }

  const text = await response.text();
  return text ? (JSON.parse(text) as DocumentContentReceipt) : null;
}

function queryString(
  params: Record<string, string | number | undefined>,
): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      query.set(key, String(value));
    }
  });
  const value = query.toString();
  return value ? `?${value}` : "";
}

export const documentApi = {
  createUploadIntent: (input: DocumentUploadIntentInput) =>
    api.post<DocumentUploadIntent>("/api/v1/documents/upload-intents", input),

  completeUpload: (
    documentId: string,
    input: { upload_token: string | null; sha256?: string },
  ) =>
    api.post<DocumentCompleteResult>(
      `/api/v1/documents/${documentId}/complete`,
      input,
    ),

  list: (params: {
    offset?: number;
    limit?: number;
    status?: string;
    type?: string;
  }) =>
    api.get<DocumentPageResult>(
      `/api/v1/documents${queryString(params)}`,
    ),

  detail: (documentId: string) =>
    api.get<DocumentDetail>(`/api/v1/documents/${documentId}`),

  reprocess: (documentId: string) =>
    api.post<{ job: BackgroundJob }>(
      `/api/v1/documents/${documentId}/reprocess`,
    ),

  job: (jobId: string) =>
    api.get<BackgroundJob>(`/api/v1/jobs/${jobId}`),

  search: (input: KnowledgeSearchInput) =>
    api.post<KnowledgeSearchResult>("/api/v1/knowledge/search", input),

  query: (input: KnowledgeQueryInput) =>
    api.post<KnowledgeQueryResult>("/api/v1/knowledge/query", input),

  latestTransactionDraft: async (documentId: string) => {
    try {
      return await api.get<DocumentTransactionDraft>(
        `/api/v1/documents/${documentId}/transaction-drafts`,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  },

  createTransactionDraft: (documentId: string) =>
    api.post<DocumentTransactionDraft>(
      `/api/v1/documents/${documentId}/transaction-drafts`,
    ),

  confirmTransactionDraft: (documentId: string, draftId: string) =>
    api.post<DocumentTransactionDraft>(
      `/api/v1/documents/${documentId}/transaction-drafts/${draftId}/confirm`,
    ),

  cancelTransactionDraft: (documentId: string, draftId: string) =>
    api.post<DocumentTransactionDraft>(
      `/api/v1/documents/${documentId}/transaction-drafts/${draftId}/cancel`,
    ),
};

export function documentPreviewUrl(
  documentId: string,
  pageNumber: number,
  suppliedUrl?: string | null,
): string {
  return (
    suppliedUrl ??
    `/api/v1/documents/${documentId}/pages/${pageNumber}/preview`
  );
}

export function jobWebSocketUrl(jobId: string): string {
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
