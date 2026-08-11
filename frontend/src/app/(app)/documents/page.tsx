import { DocumentCenterClient } from "@/components/documents/document-center-client";
import { tryServerGet } from "@/lib/server-api";
import type { DocumentPageResult } from "@/lib/types";

export default async function DocumentsPage() {
  const initialDocuments = await tryServerGet<DocumentPageResult>(
    "/api/v1/documents?offset=0&limit=100",
  );

  return <DocumentCenterClient initialDocuments={initialDocuments} />;
}
