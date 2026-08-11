"use client";

import { useMutation } from "@tanstack/react-query";
import {
  ArrowUpRight,
  BookOpen,
  Search,
  Send,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { LoadingSpinner } from "@/components/loading-state";
import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api";
import { documentApi } from "@/lib/documents";
import type {
  KnowledgeQueryResult,
  KnowledgeSearchResult,
} from "@/lib/types";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError || error instanceof Error
    ? error.message
    : fallback;
}

function RetrievalBadges({
  mode,
  degraded,
  zh,
}: {
  mode: string;
  degraded: boolean;
  zh: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="outline">{mode}</Badge>
      {degraded && (
        <Badge variant="destructive">
          <TriangleAlert className="size-3" />
          {zh ? "降级检索" : "Degraded retrieval"}
        </Badge>
      )}
    </div>
  );
}

export function KnowledgeExplorer({ zh }: { zh: boolean }) {
  const [searchText, setSearchText] = useState("");
  const [question, setQuestion] = useState("");
  const searchMutation = useMutation({
    mutationFn: (query: string) =>
      documentApi.search({ query, limit: 12 }),
  });
  const queryMutation = useMutation({
    mutationFn: (nextQuestion: string) =>
      documentApi.query({ question: nextQuestion, limit: 12 }),
  });

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    const value = searchText.trim();
    if (value && !searchMutation.isPending) {
      searchMutation.mutate(value);
    }
  };

  const submitQuestion = (event: FormEvent) => {
    event.preventDefault();
    const value = question.trim();
    if (value && !queryMutation.isPending) {
      queryMutation.mutate(value);
    }
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <Card>
        <CardHeader>
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-primary/10 p-2 text-primary">
              <Search className="size-5" />
            </div>
            <div>
              <CardTitle>
                {zh ? "检索文档证据" : "Search document evidence"}
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                {zh
                  ? "混合全文与向量检索，结果直接定位到来源页。"
                  : "Hybrid full-text and vector search with page-level evidence."}
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={submitSearch} className="flex gap-2">
            <Input
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              placeholder={
                zh
                  ? "例如：2025 年 6 月的 Fidelity 买入记录"
                  : "e.g. Fidelity purchases in June 2025"
              }
              aria-label={zh ? "知识检索关键词" : "Knowledge search terms"}
            />
            <Button
              type="submit"
              disabled={!searchText.trim() || searchMutation.isPending}
            >
              {searchMutation.isPending ? (
                <LoadingSpinner
                  label={zh ? "正在检索" : "Searching"}
                />
              ) : (
                <Search className="size-4" />
              )}
              <span className="hidden sm:inline">
                {zh ? "检索" : "Search"}
              </span>
            </Button>
          </form>

          {searchMutation.isError && (
            <Alert variant="destructive">
              <TriangleAlert />
              <AlertTitle>{zh ? "检索失败" : "Search failed"}</AlertTitle>
              <AlertDescription>
                {errorMessage(
                  searchMutation.error,
                  zh ? "请稍后重试。" : "Please try again.",
                )}
              </AlertDescription>
            </Alert>
          )}

          <SearchResults result={searchMutation.data} zh={zh} />

          {!searchMutation.data &&
            !searchMutation.isPending &&
            !searchMutation.isError && (
              <div className="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed p-6 text-center">
                <BookOpen className="mb-3 size-7 text-muted-foreground" />
                <p className="font-medium">
                  {zh ? "查找原始依据" : "Find the original evidence"}
                </p>
                <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                  {zh
                    ? "可搜索机构、证券、金额、日期或文档中的任意描述。"
                    : "Search institutions, securities, amounts, dates, or any phrase in your documents."}
                </p>
              </div>
            )}
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        <CardHeader>
          <div className="flex items-start gap-3">
            <div className="rounded-lg bg-primary/10 p-2 text-primary">
              <Sparkles className="size-5" />
            </div>
            <div>
              <CardTitle>
                {zh ? "向家庭知识库提问" : "Ask the family knowledge base"}
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                {zh
                  ? "回答只基于已索引文档，并附可核验页码引用。"
                  : "Answers are grounded in indexed documents with verifiable page citations."}
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={submitQuestion} className="space-y-2">
            <Textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder={
                zh
                  ? "例如：这些月结单里有哪些尚未入账的股息？"
                  : "e.g. Which dividends in these statements are not yet recorded?"
              }
              className="min-h-24 resize-y"
              aria-label={zh ? "知识库问题" : "Knowledge base question"}
            />
            <div className="flex justify-end">
              <Button
                type="submit"
                disabled={!question.trim() || queryMutation.isPending}
              >
                {queryMutation.isPending ? (
                  <LoadingSpinner
                    label={zh ? "正在生成回答" : "Generating answer"}
                  />
                ) : (
                  <Send className="size-4" />
                )}
                {queryMutation.isPending
                  ? zh
                    ? "思考中…"
                    : "Thinking…"
                  : zh
                    ? "提问"
                    : "Ask"}
              </Button>
            </div>
          </form>

          {queryMutation.isError && (
            <Alert variant="destructive">
              <TriangleAlert />
              <AlertTitle>{zh ? "问答失败" : "Question failed"}</AlertTitle>
              <AlertDescription>
                {errorMessage(
                  queryMutation.error,
                  zh ? "请稍后重试。" : "Please try again.",
                )}
              </AlertDescription>
            </Alert>
          )}

          <AnswerResult result={queryMutation.data} zh={zh} />

          {!queryMutation.data &&
            !queryMutation.isPending &&
            !queryMutation.isError && (
              <div className="min-h-52 rounded-lg border bg-muted/20 p-5">
                <div className="space-y-3">
                  <div className="h-3 w-2/3 rounded bg-muted" />
                  <div className="h-3 w-full rounded bg-muted" />
                  <div className="h-3 w-5/6 rounded bg-muted" />
                </div>
                <p className="mt-8 text-center text-sm text-muted-foreground">
                  {zh
                    ? "回答和引用会显示在这里"
                    : "The grounded answer and citations will appear here"}
                </p>
              </div>
            )}
        </CardContent>
      </Card>
    </div>
  );
}

function SearchResults({
  result,
  zh,
}: {
  result?: KnowledgeSearchResult;
  zh: boolean;
}) {
  if (!result) {
    return null;
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {zh
            ? `找到 ${result.items.length} 条证据`
            : `${result.items.length} evidence matches`}
        </p>
        <RetrievalBadges
          mode={result.retrieval_mode}
          degraded={result.degraded}
          zh={zh}
        />
      </div>
      {result.items.map((item) => (
        <article
          key={item.chunk_id}
          className="rounded-lg border p-3 transition-colors hover:bg-muted/30"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate font-medium">{item.filename}</p>
              <p className="mt-1 line-clamp-3 text-sm text-muted-foreground">
                {item.content}
              </p>
            </div>
            <Badge variant="secondary">
              {Math.round(item.score * 100)}%
            </Badge>
          </div>
          <Link
            href={`/documents/${item.document_id}?page=${item.page_number}`}
            className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            {item.citation ||
              (zh ? `第 ${item.page_number} 页` : `Page ${item.page_number}`)}
            <ArrowUpRight className="size-3" />
          </Link>
        </article>
      ))}
      {result.items.length === 0 && (
        <div className="rounded-lg border border-dashed py-10 text-center text-sm text-muted-foreground">
          {zh
            ? "没有找到匹配证据，请尝试更具体或不同的关键词。"
            : "No matching evidence. Try a more specific or different phrase."}
        </div>
      )}
    </div>
  );
}

function AnswerResult({
  result,
  zh,
}: {
  result?: KnowledgeQueryResult;
  zh: boolean;
}) {
  if (!result) {
    return null;
  }

  return (
    <div className="space-y-4 rounded-lg border bg-muted/15 p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">
          {zh ? "基于文档的回答" : "Document-grounded answer"}
        </p>
        <RetrievalBadges
          mode={result.retrieval_mode}
          degraded={result.degraded}
          zh={zh}
        />
      </div>
      <div className="prose prose-sm max-w-none text-foreground dark:prose-invert">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {result.answer}
        </ReactMarkdown>
      </div>
      {result.warnings.length > 0 && (
        <Alert>
          <TriangleAlert />
          <AlertTitle>{zh ? "注意" : "Note"}</AlertTitle>
          <AlertDescription>{result.warnings.join(" · ")}</AlertDescription>
        </Alert>
      )}
      <div className="space-y-2 border-t pt-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {zh ? "引用" : "Citations"}
        </p>
        <div className="flex flex-wrap gap-2">
          {result.citations.map((citation, index) => (
            <Button
              key={`${citation.document_id}-${citation.page_number}-${index}`}
              variant="outline"
              size="sm"
              render={
                <Link
                  href={`/documents/${citation.document_id}?page=${citation.page_number}`}
                />
              }
            >
              {citation.citation ||
                `${citation.filename} · ${
                  zh
                    ? `第 ${citation.page_number} 页`
                    : `p. ${citation.page_number}`
                }`}
              <ArrowUpRight className="size-3" />
            </Button>
          ))}
          {result.citations.length === 0 && (
            <span className="text-xs text-amber-700">
              {zh
                ? "当前回答没有可核验引用，请勿据此执行交易。"
                : "This answer has no verifiable citations; do not act on it."}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
