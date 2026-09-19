"use client";

import {
  BrainCircuit,
  BookOpenText,
  Check,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Globe2,
  Search,
  Terminal,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { InternalErrorDetails, WebSearchActivity } from "../../lib/sse";

type ChatBubbleProps = {
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  webSearch?: WebSearchActivity;
  internalError?: InternalErrorDetails;
  isIncomplete?: boolean;
};

function MarkdownContent({
  content,
  muted = false,
  streaming = false,
}: {
  content: string;
  muted?: boolean;
  streaming?: boolean;
}) {
  const textColor = muted ? "text-slate-400" : "text-slate-200";

  return (
    <div className={streaming ? "streaming-markdown" : undefined}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className={`mb-4 text-2xl font-semibold tracking-tight ${textColor}`}>{children}</h1>,
          h2: ({ children }) => <h2 className={`mb-3 mt-7 text-xl font-semibold tracking-tight ${textColor}`}>{children}</h2>,
          h3: ({ children }) => <h3 className={`mb-2 mt-6 text-lg font-semibold ${textColor}`}>{children}</h3>,
          h4: ({ children }) => <h4 className={`mb-2 mt-5 font-semibold ${textColor}`}>{children}</h4>,
          p: ({ children }) => <p className={`mb-4 last:mb-0 leading-7 ${textColor}`}>{children}</p>,
          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-indigo-300 underline decoration-indigo-400/40 underline-offset-4 transition-colors hover:text-indigo-200"
            >
              {children}
            </a>
          ),
          ul: ({ children }) => <ul className={`mb-4 list-disc space-y-2 pl-6 marker:text-indigo-400 ${textColor}`}>{children}</ul>,
          ol: ({ children }) => <ol className={`mb-4 list-decimal space-y-2 pl-6 marker:text-indigo-400 ${textColor}`}>{children}</ol>,
          li: ({ children }) => <li className="pl-1 leading-7">{children}</li>,
          blockquote: ({ children }) => (
            <blockquote className="my-5 rounded-r-xl border-l-2 border-indigo-400/60 bg-indigo-400/[0.05] py-2.5 pl-4 pr-3 text-slate-400">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="my-6 border-white/[0.08]" />,
          pre: ({ children }) => (
            <pre className="my-5 overflow-x-auto rounded-2xl border border-white/[0.08] bg-[#090a0d] p-4 text-sm leading-6 text-slate-200 shadow-inner">
              {children}
            </pre>
          ),
          code: ({ children }) => (
            <code className="rounded-md bg-white/[0.07] px-1.5 py-0.5 font-mono text-[0.9em] text-indigo-200">
              {children}
            </code>
          ),
          table: ({ children }) => (
            <div className="my-5 overflow-x-auto rounded-2xl border border-white/[0.08]">
              <table className="w-full border-collapse text-left text-sm">{children}</table>
            </div>
          ),
          thead: ({ children }) => <thead className="bg-white/[0.04] text-slate-200">{children}</thead>,
          th: ({ children }) => <th className="border-b border-white/[0.08] px-4 py-3 font-semibold">{children}</th>,
          td: ({ children }) => <td className="border-b border-white/[0.05] px-4 py-3 align-top text-slate-300">{children}</td>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function ThoughtBlock({ thought }: { thought: string }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="mb-4 overflow-hidden rounded-2xl border border-white/[0.08] bg-black/20 shadow-inner">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="flex w-full cursor-pointer items-center gap-2.5 px-4 py-3 text-slate-400 transition-colors hover:bg-white/[0.035] hover:text-slate-200"
        aria-expanded={isOpen}
      >
        <BrainCircuit size={16} className="text-indigo-400" />
        <span className="text-sm font-medium">Proses berpikir</span>
        {isOpen ? <ChevronDown size={16} className="ml-auto" /> : <ChevronRight size={16} className="ml-auto" />}
      </button>
      {isOpen && (
        <div className="border-t border-white/[0.06] bg-black/20 px-4 py-3.5">
          <div className="font-mono text-[13px]">
            <MarkdownContent content={thought} muted />
          </div>
        </div>
      )}
    </div>
  );
}

const ENGINE_LABELS: Record<string, string> = {
  google: "Google",
};

function engineNames(activity: WebSearchActivity): string[] {
  const rawNames = activity.phase === "searching"
    ? activity.engines
    : activity.phase === "complete"
      ? activity.results.flatMap((result) => result.engine.split(","))
      : [];

  return Array.from(
    new Set(
      rawNames
        .map((name) => name.trim().toLowerCase())
        .filter(Boolean)
        .map((name) => ENGINE_LABELS[name] ?? name),
    ),
  );
}

function sourceDomain(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function WebSearchIndicator({ activity }: { activity: WebSearchActivity }) {
  const [isOpen, setIsOpen] = useState(false);
  const isSearching = activity.phase === "searching";
  const isReading = activity.phase === "reading";
  const isActive = isSearching || isReading;
  const results = activity.phase === "complete" ? activity.results : [];
  const readPages = activity.phase === "complete" ? activity.pages : [];
  const readUrls = new Set(readPages.map((page) => page.url));
  const names = engineNames(activity);
  const canExpand = activity.phase === "complete" && activity.status === "ok" && results.length > 0;

  let title = "Mencari di web";
  let description = names.length > 0 ? names.join(" · ") : "Web";

  if (isReading) {
    title = "Membaca sumber lengkap";
    description = activity.pages.map((page) => sourceDomain(page.url)).join(" · ");
  } else if (activity.phase === "complete") {
    if (activity.status === "ok") {
      title = "Pencarian web selesai";
      description = `${results.length} sumber${readPages.length > 0 ? ` · ${readPages.length} dibaca penuh` : ""}${names.length > 0 ? ` · ${names.join(" · ")}` : ""}`;
    } else if (activity.status === "no_results") {
      title = "Tidak menemukan hasil yang relevan";
      description = activity.query;
    } else {
      title = "Pencarian web tidak tersedia";
      description = "Claire melanjutkan tanpa konteks web";
    }
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      className="mb-5 max-w-2xl"
      role="status"
      aria-live="polite"
    >
      <button
        type="button"
        onClick={() => canExpand && setIsOpen((open) => !open)}
        disabled={!canExpand}
        aria-expanded={canExpand ? isOpen : undefined}
        className={`group flex w-full items-center gap-3 rounded-xl px-1 py-1.5 text-left ${
          canExpand ? "cursor-pointer" : "cursor-default"
        }`}
      >
        <span className="relative flex h-8 w-8 shrink-0 items-center justify-center">
          {isActive && (
            <>
              <motion.span
                className="absolute inset-0 rounded-full border border-indigo-400/30"
                animate={{ scale: [0.78, 1.18], opacity: [0.8, 0] }}
                transition={{ duration: 1.5, repeat: Infinity, ease: "easeOut" }}
              />
              <span className="absolute inset-1 rounded-full bg-indigo-400/10" />
            </>
          )}
          {activity.phase === "searching" ? (
            <motion.span
              animate={{ rotate: [0, -8, 8, 0] }}
              transition={{ duration: 1.7, repeat: Infinity, ease: "easeInOut" }}
            >
              <Search size={17} className="text-indigo-300" strokeWidth={2.2} />
            </motion.span>
          ) : activity.phase === "reading" ? (
            <motion.span
              animate={{ opacity: [0.55, 1, 0.55], scale: [0.96, 1.04, 0.96] }}
              transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
            >
              <BookOpenText size={17} className="text-indigo-300" strokeWidth={2.2} />
            </motion.span>
          ) : activity.status === "ok" ? (
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-400/10 text-emerald-300">
              <Check size={16} strokeWidth={2.5} />
            </span>
          ) : (
            <CircleAlert size={17} className="text-amber-300" />
          )}
        </span>

        <span className="min-w-0 flex-1">
          <AnimatePresence initial={false} mode="wait">
            <motion.span
              key={`${activity.phase}-${activity.phase === "complete" ? activity.status : "active"}`}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -3 }}
              transition={{ duration: 0.2 }}
              className="block"
            >
              <span className="block text-sm font-medium text-slate-200">{title}</span>
              <span className="mt-0.5 block truncate text-xs text-slate-500">{description}</span>
            </motion.span>
          </AnimatePresence>
        </span>

        {canExpand && (
          <ChevronDown
            size={16}
            className={`shrink-0 text-slate-500 transition-transform duration-200 group-hover:text-slate-300 ${
              isOpen ? "rotate-180" : ""
            }`}
          />
        )}
      </button>

      {isSearching && (
        <div className="ml-12 mt-1 flex min-w-0 items-center gap-2 text-xs text-slate-500">
          <Globe2 size={13} className="shrink-0 text-slate-600" />
          <span className="truncate">{activity.query}</span>
        </div>
      )}

      {isReading && (
        <div className="ml-12 mt-1 flex min-w-0 items-center gap-2 text-xs text-slate-500">
          <BookOpenText size={13} className="shrink-0 text-slate-600" />
          <span className="truncate">{activity.pages.map((page) => page.title || sourceDomain(page.url)).join(" · ")}</span>
        </div>
      )}

      <AnimatePresence initial={false}>
        {isOpen && canExpand && (
          <motion.div
            initial={{ opacity: 0, height: 0, y: -4 }}
            animate={{ opacity: 1, height: "auto", y: 0 }}
            exit={{ opacity: 0, height: 0, y: -4 }}
            transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
            className="ml-11 overflow-hidden"
          >
            <div className="grid gap-2 pb-1 pt-3 sm:grid-cols-2">
              {results.map((result, index) => (
                <a
                  key={`${result.url}-${index}`}
                  href={result.url}
                  target="_blank"
                  rel="noreferrer"
                  className="group/source min-w-0 rounded-xl border border-white/[0.07] bg-white/[0.025] px-3.5 py-3 transition-colors hover:border-indigo-400/20 hover:bg-indigo-400/[0.045]"
                >
                  <span className="line-clamp-2 block text-[13px] font-medium leading-5 text-slate-300 transition-colors group-hover/source:text-indigo-200">
                    {result.title}
                  </span>
                  <span className="mt-1.5 block truncate text-[11px] text-slate-600">
                    {sourceDomain(result.url)}{readUrls.has(result.url) ? " · Dibaca penuh" : ""}
                  </span>
                </a>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function StreamingPlaceholder() {
  return (
    <div className="py-3" role="status" aria-label="Jawaban sedang dimuat">
      <div className="space-y-2.5" aria-hidden="true">
        <div className="streaming-skeleton h-2.5 w-[88%]" />
        <div className="streaming-skeleton h-2.5 w-[68%] [animation-delay:120ms]" />
        <div className="streaming-skeleton h-2.5 w-[42%] [animation-delay:240ms]" />
      </div>
    </div>
  );
}

function InternalErrorReport({ error }: { error: InternalErrorDetails }) {
  const [isLogOpen, setIsLogOpen] = useState(false);
  const operation = error.operation.replaceAll("_", " ");

  return (
    <div className="relative overflow-hidden rounded-2xl border border-red-400/20 bg-red-500/[0.045] px-5 py-4 shadow-[0_14px_38px_rgba(127,29,29,0.12)]">
      <div className="absolute inset-y-0 left-0 w-0.5 bg-gradient-to-b from-red-300 via-red-500 to-rose-700" />
      <div className="mb-4 flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-red-400/10 text-red-300 ring-1 ring-red-300/15">
          <CircleAlert size={17} strokeWidth={2.2} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-semibold uppercase tracking-[0.17em] text-red-300">Internal error</div>
          <div className="mt-1 truncate text-xs capitalize text-red-200/60">{operation}</div>
        </div>
      </div>

      <div className="text-[15px]">
        <div className="mb-4 rounded-xl border border-red-300/10 bg-red-950/20 px-3 py-2.5 font-mono text-xs leading-5 text-red-100/65">
          {error.message}
        </div>
        <MarkdownContent content={error.analysis} />
      </div>

      <div className="mt-4 border-t border-red-300/10 pt-3">
        <button
          type="button"
          onClick={() => setIsLogOpen((open) => !open)}
          className="flex w-full cursor-pointer items-center gap-2 text-left text-xs font-medium text-red-200/70 transition hover:text-red-100"
          aria-expanded={isLogOpen}
        >
          <Terminal size={14} />
          Full error log
          <ChevronDown size={14} className={`ml-auto transition-transform ${isLogOpen ? "rotate-180" : ""}`} />
        </button>
        <AnimatePresence initial={false}>
          {isLogOpen && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              <pre className="custom-scrollbar mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-red-300/10 bg-black/30 p-3 font-mono text-[11px] leading-5 text-red-100/65">
                {error.log}
              </pre>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function AssistantContent({ content, isStreaming }: { content: string; isStreaming: boolean }) {
  const regex = /<thought>([\s\S]*?)<\/thought>/g;
  const parts: Array<{ type: "text" | "thought"; content: string }> = [];
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", content: content.slice(lastIndex, match.index) });
    }
    parts.push({ type: "thought", content: match[1] });
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < content.length) {
    parts.push({ type: "text", content: content.slice(lastIndex) });
  }

  if (parts.length === 0) parts.push({ type: "text", content });

  return (
    <div className="flex flex-col">
      {parts.map((part, index) => {
        if (part.type === "thought") {
          return <ThoughtBlock key={index} thought={part.content.trim()} />;
        }
        if (!part.content.trim()) return null;
        return (
          <div key={index} className="text-base">
            <MarkdownContent
              content={part.content.trim()}
              streaming={isStreaming && index === parts.length - 1}
            />
          </div>
        );
      })}
    </div>
  );
}

export default function ChatBubble({
  role,
  content,
  isStreaming = false,
  webSearch,
  internalError,
  isIncomplete = false,
}: ChatBubbleProps) {
  const isUser = role === "user";

  if (isUser) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 10, scale: 0.985 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
        className="mb-7 flex w-full justify-end"
      >
        <div className="max-w-[88%] rounded-[22px] rounded-br-md border border-white/[0.08] bg-gradient-to-br from-[#292c35] to-[#202229] px-5 py-3.5 text-[15px] leading-7 text-slate-100 shadow-[0_12px_30px_rgba(0,0,0,0.18),inset_0_1px_0_rgba(255,255,255,0.05)] sm:max-w-[78%]">
          {content}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.34, ease: [0.22, 1, 0.36, 1] }}
      className="mb-8 w-full"
    >
      <div aria-busy={isStreaming}>
        {internalError ? (
          <InternalErrorReport error={internalError} />
        ) : webSearch && <WebSearchIndicator activity={webSearch} />}
        {!internalError && !content && isStreaming && webSearch?.phase !== "searching" && webSearch?.phase !== "reading" ? (
          <StreamingPlaceholder />
        ) : !internalError && content ? (
          <AssistantContent content={content} isStreaming={isStreaming} />
        ) : null}
        {isIncomplete && !isStreaming && (
          <p role="status" className="mt-3 text-sm text-amber-300">
            Jawaban ini belum lengkap. Kamu bisa meminta lanjutannya.
          </p>
        )}
      </div>
    </motion.div>
  );
}
