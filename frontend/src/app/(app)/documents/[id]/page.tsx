import { DocumentDetailClient } from "@/components/documents/document-detail-client";
import { tryServerGet } from "@/lib/server-api";
import type { DocumentDetail } from "@/lib/types";

export default async function DocumentDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ page?: string | string[] }>;
}) {
  const [{ id }, query] = await Promise.all([params, searchParams]);
  const rawPage = Array.isArray(query.page) ? query.page[0] : query.page;
  const parsedPage = rawPage ? Number.parseInt(rawPage, 10) : Number.NaN;
  const initialDocument = await tryServerGet<DocumentDetail>(
    `/api/v1/documents/${encodeURIComponent(id)}`,
  );

  return (
    <DocumentDetailClient
      documentId={id}
      initialDocument={initialDocument}
      initialPage={
        Number.isSafeInteger(parsedPage) && parsedPage > 0 ? parsedPage : null
      }
    />
  );
}
