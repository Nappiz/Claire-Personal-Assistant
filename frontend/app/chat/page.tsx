"use client";

import { useState, useRef, useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { Send, Square, Plus, MessageSquare, Menu, X, Sparkles, Trash2, Activity, Settings, Terminal, Check, LoaderCircle, Pin, Folder, FolderOpen, ArrowLeft } from "lucide-react";
import ChatBubble from "./ChatBubble";
import Modal from "../../components/Modal";
import GraphVisualizer from "../../components/GraphVisualizer";
import SystemStatsModal from "../../components/SystemStatsModal";
import ModelSettingsModal, { LLMModel } from "../../components/ModelSettingsModal";
import BackendLogsModal from "../../components/BackendLogsModal";
import { parseSSEStream, type InternalErrorDetails, type WebSearchActivity } from "../../lib/sse";
import {
  getRandomPromptSuggestions,
  PROMPT_SUGGESTIONS,
  type PromptSuggestion,
} from "../../lib/prompt-suggestions";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: "streaming" | "complete" | "incomplete" | "stopped";
  response_status?: "complete" | "incomplete";
  webSearch?: WebSearchActivity;
  internalError?: InternalErrorDetails;
};

type Session = {
  id: string;
  title: string;
  is_pinned: boolean;
  pinned_at?: string | null;
  updated_at: string;
  project_id?: string | null;
};

type Project = {
  id: string;
  name: string;
  description?: string | null;
  session_count: number;
  updated_at: string;
};

type TitleGenerationPhase = "generating" | "complete";

type TitleGeneration = {
  sessionId: string;
  phase: TitleGenerationPhase;
};

function SessionTitle({
  session,
  generation,
}: {
  session: Session;
  generation: TitleGeneration | null;
}) {
  const phase = generation?.sessionId === session.id ? generation.phase : null;

  return (
    <div className="min-w-0 flex-1 overflow-hidden">
      <AnimatePresence initial={false} mode="wait">
        {phase === "generating" ? (
          <motion.span
            key="generating"
            initial={{ opacity: 0, y: 5, filter: "blur(2px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, y: -5, filter: "blur(2px)" }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="flex items-center gap-1.5 text-xs font-medium text-indigo-300"
          >
            <LoaderCircle size={14} className="shrink-0 animate-spin" aria-hidden="true" />
            <span className="truncate">Menyusun judul</span>
          </motion.span>
        ) : phase === "complete" ? (
          <motion.span
            key="complete"
            initial={{ opacity: 0, scale: 0.9, y: 4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -3 }}
            transition={{ type: "spring", stiffness: 420, damping: 24 }}
            className="flex items-center gap-1.5 text-xs font-medium text-emerald-300"
          >
            <Check size={14} className="shrink-0" strokeWidth={2.75} aria-hidden="true" />
            <span className="truncate">Judul siap</span>
          </motion.span>
        ) : (
          <motion.span
            key="title"
            initial={{ opacity: 0, y: 5, filter: "blur(2px)" }}
            animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
            exit={{ opacity: 0, y: -4, filter: "blur(2px)" }}
            transition={{ duration: 0.25, ease: "easeOut" }}
            className="block truncate"
            title={session.title}
          >
            {session.title}
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [isProjectModalOpen, setIsProjectModalOpen] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectDescription, setNewProjectDescription] = useState("");
  const [projectError, setProjectError] = useState("");
  const [isCreatingProject, setIsCreatingProject] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [sessionToDelete, setSessionToDelete] = useState<string | null>(null);
  const [isGraphOpen, setIsGraphOpen] = useState(false);
  const [isStatsOpen, setIsStatsOpen] = useState(false);
  const [isModelSettingsOpen, setIsModelSettingsOpen] = useState(false);
  const [isLogsOpen, setIsLogsOpen] = useState(false);
  const [titleGeneration, setTitleGeneration] = useState<TitleGeneration | null>(null);
  const [suggestedPrompts, setSuggestedPrompts] = useState<PromptSuggestion[]>(
    () => PROMPT_SUGGESTIONS.slice(0, 4),
  );
  
  const [models, setModels] = useState<LLMModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<LLMModel | null>(null);
  const [isModelDropdownOpen, setIsModelDropdownOpen] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const skipNextHistoryFetchRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const titlePollControllerRef = useRef<AbortController | null>(null);
  const suggestionsReadyRef = useRef(false);

  useEffect(() => {
    if (messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: isLoading ? "auto" : "smooth" });
    }
  }, [messages, isLoading]);

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
      titlePollControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    if (messages.length !== 0 || isLoading || suggestionsReadyRef.current) return;
    setSuggestedPrompts(getRandomPromptSuggestions());
    suggestionsReadyRef.current = true;
  }, [isLoading, messages.length]);

  const fetchSessions = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/sessions`);
      const data = await res.json();
      if (Array.isArray(data)) {
        setSessions(data);
      } else {
        console.error("Expected an array of sessions, but received:", data);
        setSessions([]);
      }
    } catch (err) {
      console.error(err);
      setSessions([]);
    }
  };

  const fetchProjects = async () => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/projects`);
      if (!response.ok) throw new Error(`Projects request failed with HTTP ${response.status}`);
      const data = await response.json();
      setProjects(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error("Failed to fetch projects", error);
      setProjects([]);
    }
  };

  const refreshGeneratedSessionTitle = async (sessionId: string) => {
    titlePollControllerRef.current?.abort();
    const controller = new AbortController();
    titlePollControllerRef.current = controller;
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1";

    // Let the placeholder render before transitioning it into the title
    // generation state, so the sidebar communicates the whole lifecycle.
    await new Promise<void>((resolve) => window.setTimeout(resolve, 350));
    if (controller.signal.aborted) return;
    setTitleGeneration({ sessionId, phase: "generating" });

    // The backend intentionally generates titles after the stream closes so
    // text streaming is never delayed. Poll only this brand-new session until
    // that background task replaces the placeholder title.
    for (let attempt = 0; attempt < 20 && !controller.signal.aborted; attempt += 1) {
      await new Promise<void>((resolve) => window.setTimeout(resolve, attempt === 0 ? 500 : 1000));
      if (controller.signal.aborted) return;

      try {
        const response = await fetch(`${apiUrl}/sessions`, { signal: controller.signal });
        if (!response.ok) continue;

        const latestSessions: Session[] = await response.json();
        const updatedSession = latestSessions.find((session) => session.id === sessionId);
        if (!updatedSession || updatedSession.title === "New Chat...") continue;

        setSessions(latestSessions);
        setTitleGeneration({ sessionId, phase: "complete" });
        await new Promise<void>((resolve) => window.setTimeout(resolve, 650));
        if (!controller.signal.aborted) {
          setTitleGeneration((current) =>
            current?.sessionId === sessionId ? null : current,
          );
        }
        return;
      } catch (error) {
        if (!controller.signal.aborted) {
          console.error("Failed to refresh generated session title", error);
          setTitleGeneration((current) =>
            current?.sessionId === sessionId ? null : current,
          );
        }
        return;
      }
    }

    if (!controller.signal.aborted) {
      setTitleGeneration((current) =>
        current?.sessionId === sessionId ? null : current,
      );
    }
  };

  const fetchModels = async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/settings/custom_models`);
      const data = await res.json();
      if (data.value && data.value.length > 0) {
        setModels(data.value);
        const savedModelId = localStorage.getItem("claire_selected_model");
        if (savedModelId) {
          const found = data.value.find((m: LLMModel) => m.id === savedModelId);
          setSelectedModel(found || data.value[0]);
        } else {
          setSelectedModel(data.value[0]);
        }
      } else {
        const defaultModels: LLMModel[] = [
          { id: 'gemini-3.1-flash-lite', name: 'Gemini 3.1 Flash Lite', provider: 'google' },
          { id: 'llama3-70b-8192', name: 'Llama 3 70B', provider: 'groq' }
        ];
        setModels(defaultModels);
        const savedModelId = localStorage.getItem("claire_selected_model");
        if (savedModelId) {
          const found = defaultModels.find((m: LLMModel) => m.id === savedModelId);
          setSelectedModel(found || defaultModels[0]);
        } else {
          setSelectedModel(defaultModels[0]);
        }
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetchSessions();
      void fetchProjects();
      void fetchModels();
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function fetchHistory(sessionId: string) {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/history/${sessionId}`);
      if (res.ok) {
        const data = await res.json();
        setMessages(
          Array.isArray(data)
            ? data.map((message) => ({
                ...message,
                internalError: message.internal_error ?? undefined,
              }))
            : [],
        );
      }
    } catch (e) {
      console.error("Failed to fetch history", e);
    }
  }

  useEffect(() => {
    if (!activeSessionId) return;
    if (skipNextHistoryFetchRef.current) {
      skipNextHistoryFetchRef.current = false;
      return;
    }

    const timer = window.setTimeout(() => void fetchHistory(activeSessionId), 0);
    return () => window.clearTimeout(timer);
  }, [activeSessionId]);

  const handleNewChat = (projectId: string | null = activeProjectId) => {
    abortControllerRef.current?.abort();
    titlePollControllerRef.current?.abort();
    setTitleGeneration(null);
    setActiveSessionId(null);
    setActiveProjectId(projectId);
    setMessages([]);
    setSuggestedPrompts(getRandomPromptSuggestions());
    suggestionsReadyRef.current = true;
  };

  const handleSend = async (
    customInput?: string,
    forceModelIndex?: number,
    forcedSessionId?: string | null,
    forcedTurnId?: string,
  ) => {
    const textToSend = customInput !== undefined ? customInput : input;
    if (!textToSend.trim() || (isLoading && forceModelIndex === undefined)) return;

    const durableTurnId = forcedTurnId ?? crypto.randomUUID();
    if (forceModelIndex === undefined) {
      const userMsg: Message = { id: durableTurnId, role: "user", content: textToSend };
      setMessages((prev) => [...prev, userMsg]);
      setInput("");
      setIsLoading(true);
    }

    const currentModelIndex = forceModelIndex !== undefined 
      ? forceModelIndex 
      : (selectedModel ? models.findIndex(m => m.id === selectedModel.id) : 0);
      
    const safeIndex = currentModelIndex >= 0 ? currentModelIndex : 0;
    const modelToUse = models[safeIndex];
    const requestSessionId = forcedSessionId ?? activeSessionId;
    const isNewSession = !requestSessionId;
    let streamedSessionId = requestSessionId;
    const assistantMessageId = crypto.randomUUID();

    setMessages((prev) => [
      ...prev,
      {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        status: "streaming",
      },
    ]);

    const controller = new AbortController();
    abortControllerRef.current = controller;
    let receivedContent = false;
    let pendingDelta = "";
    let animationFrameId: number | null = null;

    const flushPendingDelta = () => {
      animationFrameId = null;
      if (!pendingDelta) return;

      const nextDelta = pendingDelta;
      pendingDelta = "";
      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantMessageId
            ? { ...message, content: message.content + nextDelta }
            : message,
        ),
      );
    };

    const scheduleDeltaRender = (delta: string) => {
      pendingDelta += delta;
      if (animationFrameId === null) {
        animationFrameId = window.requestAnimationFrame(flushPendingDelta);
      }
    };

    try {
      const payload: {
        message: string;
        session_id?: string;
        model?: string;
        provider?: string;
        project_id?: string;
        turn_id: string;
      } = { message: textToSend, turn_id: durableTurnId };
      if (requestSessionId) {
        payload.session_id = requestSessionId;
      }
      if (activeProjectId) {
        payload.project_id = activeProjectId;
      }
      if (modelToUse) {
        payload.model = modelToUse.id;
        payload.provider = modelToUse.provider;
      }

      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      let completed = false;
      for await (const event of parseSSEStream(response)) {
        if (event.type === "session") {
          streamedSessionId = event.session_id;
        } else if (event.type === "web_search") {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantMessageId
                ? { ...message, webSearch: event }
                : message,
            ),
          );
        } else if (event.type === "delta") {
          receivedContent = true;
          scheduleDeltaRender(event.delta);
        } else if (event.type === "error") {
          streamedSessionId = event.session_id;
          throw new Error(`${event.error.code}: ${event.error.message}`);
        } else if (event.type === "internal_error") {
          if (event.session_id) streamedSessionId = event.session_id;
          completed = true;
          receivedContent = true;
          pendingDelta = "";
          if (animationFrameId !== null) {
            window.cancelAnimationFrame(animationFrameId);
            animationFrameId = null;
          }
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantMessageId
                ? {
                    ...message,
                    content: event.error.analysis,
                    status: "complete",
                    webSearch: undefined,
                    internalError: event.error,
                  }
                : message,
            ),
          );
        } else if (event.type === "done") {
          streamedSessionId = event.session_id;
          completed = true;
          if (animationFrameId !== null) window.cancelAnimationFrame(animationFrameId);
          flushPendingDelta();
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantMessageId
                ? { ...message, status: event.response_status === "incomplete" ? "incomplete" : "complete",
                    response_status: event.response_status ?? "complete" }
                : message,
            ),
          );
        }
      }

      if (!completed) throw new Error("The chat stream closed without a done event");

      if (!activeSessionId && streamedSessionId) {
        skipNextHistoryFetchRef.current = true;
        setActiveSessionId(streamedSessionId);
      }
      await fetchSessions();
      await fetchProjects();
      if (isNewSession && streamedSessionId) {
        void refreshGeneratedSessionTitle(streamedSessionId);
      }
      if (abortControllerRef.current === controller) abortControllerRef.current = null;
      setIsLoading(false);
    } catch (error) {
      if (controller.signal.aborted) {
        if (animationFrameId !== null) window.cancelAnimationFrame(animationFrameId);
        flushPendingDelta();
        setMessages((prev) =>
          receivedContent
            ? prev.map((message) =>
                message.id === assistantMessageId
                  ? { ...message, status: "stopped" }
                  : message,
              )
            : prev.filter((message) => message.id !== assistantMessageId),
        );
        if (abortControllerRef.current === controller) abortControllerRef.current = null;
        setIsLoading(false);
        return;
      }

      console.error(error);
      if (animationFrameId !== null) window.cancelAnimationFrame(animationFrameId);
      setMessages((prev) => prev.filter((message) => message.id !== assistantMessageId));
      if (abortControllerRef.current === controller) abortControllerRef.current = null;

      const nextIndex = safeIndex + 1;
      if (nextIndex < models.length) {
        const nextModel = models[nextIndex];
        
        setSelectedModel(nextModel);
        localStorage.setItem("claire_selected_model", nextModel.id);
        
        const errorMsg: Message = { 
          id: crypto.randomUUID(), 
          role: "assistant", 
          content: `⚠️ Model **${modelToUse?.name || 'sebelumnya'}** sedang error atau kena limit. Mengalihkan otomatis ke **${nextModel.name}**...` 
        };
        setMessages((prev) => [...prev, errorMsg]);
        
        setTimeout(() => {
           handleSend(textToSend, nextIndex, streamedSessionId, durableTurnId);
        }, 1000);
      } else {
        const errorMsg: Message = { 
          id: crypto.randomUUID(), 
          role: "assistant", 
          content: "❌ Maaf, semua model sedang error atau kena limit. Silakan coba lagi nanti atau tambah model baru di pengaturan." 
        };
        setMessages((prev) => [...prev, errorMsg]);
        if (abortControllerRef.current === controller) abortControllerRef.current = null;
        setIsLoading(false);
      }
    }
  };

  const handleStop = () => {
    abortControllerRef.current?.abort();
  };

  const confirmDeleteSession = async () => {
    if (!sessionToDelete) return;
    
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/sessions/${sessionToDelete}`, {
        method: "DELETE"
      });
      if (res.ok) {
        setSessions(prev => prev.filter(s => s.id !== sessionToDelete));
        void fetchProjects();
        if (activeSessionId === sessionToDelete) {
          setActiveSessionId(null);
          setMessages([]);
        }
      }
    } catch (error) {
      console.error("Failed to delete session", error);
    } finally {
      setSessionToDelete(null);
    }
  };

  const openSession = (sessionId: string) => {
    abortControllerRef.current?.abort();
    setIsLoading(false);
    setActiveSessionId(sessionId);
    setActiveProjectId(sessions.find((session) => session.id === sessionId)?.project_id || null);
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  };

  const openProject = (projectId: string) => {
    handleNewChat(projectId);
    if (window.innerWidth < 768) setIsSidebarOpen(false);
  };

  const createProject = async () => {
    const name = newProjectName.trim();
    if (!name || isCreatingProject) return;
    setIsCreatingProject(true);
    setProjectError("");
    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/projects`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            description: newProjectDescription.trim() || null,
          }),
        },
      );
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Project gagal dibuat");
      setProjects((current) => [data, ...current]);
      setNewProjectName("");
      setNewProjectDescription("");
      setIsProjectModalOpen(false);
      openProject(data.id);
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "Project gagal dibuat");
    } finally {
      setIsCreatingProject(false);
    }
  };

  const toggleSessionPin = async (session: Session) => {
    const nextPinned = !session.is_pinned;
    setSessions((current) =>
      current.map((item) =>
        item.id === session.id
          ? {
              ...item,
              is_pinned: nextPinned,
              pinned_at: nextPinned ? new Date().toISOString() : null,
            }
          : item,
      ),
    );

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/sessions/${session.id}/pin`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_pinned: nextPinned }),
        },
      );
      if (!response.ok) throw new Error(`Pin session failed with HTTP ${response.status}`);
      await fetchSessions();
    } catch (error) {
      console.error("Failed to update session pin", error);
      setSessions((current) =>
        current.map((item) =>
          item.id === session.id ? { ...item, is_pinned: session.is_pinned, pinned_at: session.pinned_at } : item,
        ),
      );
    }
  };

  const renderSessionRow = (session: Session) => (
    <div
      key={session.id}
      className={`group flex w-full items-center rounded-xl text-sm transition-all duration-200 ${
        activeSessionId === session.id
          ? "bg-[#24252a] font-medium text-indigo-300 shadow-[inset_0_1px_2px_rgba(0,0,0,0.2)]"
          : "text-gray-400 hover:bg-[#1e1f22] hover:text-gray-200"
      }`}
    >
      <button
        type="button"
        onClick={() => openSession(session.id)}
        className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 p-3 pr-1 text-left"
      >
        <MessageSquare size={16} className={`shrink-0 transition-colors ${activeSessionId === session.id ? "text-indigo-400" : "text-gray-500 group-hover:text-gray-400"}`} />
        <SessionTitle session={session} generation={titleGeneration} />
      </button>

      <div className="flex shrink-0 items-center gap-0.5 pr-2">
        <button
          type="button"
          onClick={() => void toggleSessionPin(session)}
          className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg transition-all hover:bg-white/[0.06] hover:text-indigo-300 ${
            session.is_pinned
              ? "text-indigo-400 opacity-100"
              : "text-gray-500 opacity-50 sm:opacity-0 sm:group-hover:opacity-100 focus-visible:opacity-100"
          }`}
          aria-label={session.is_pinned ? `Lepas pin ${session.title}` : `Pin ${session.title}`}
          title={session.is_pinned ? "Lepas pin" : "Pin session"}
        >
          <Pin size={14} fill={session.is_pinned ? "currentColor" : "none"} />
        </button>
        <button
          type="button"
          className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg text-gray-500 opacity-50 transition-all hover:bg-red-400/10 hover:text-red-400 sm:opacity-0 sm:group-hover:opacity-100 focus-visible:opacity-100"
          onClick={() => setSessionToDelete(session.id)}
          aria-label={`Hapus ${session.title}`}
          title="Hapus session"
        >
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );

  const scopedSessions = sessions.filter(
    (session) => (session.project_id || null) === activeProjectId,
  );
  const pinnedSessions = scopedSessions.filter((session) => session.is_pinned);
  const regularSessions = scopedSessions.filter((session) => !session.is_pinned);
  const activeProject = projects.find((project) => project.id === activeProjectId) || null;

  const renderInputForm = () => (
    <div className={`composer-shell ${isLoading ? "is-streaming" : ""}`}>
      <div className="relative flex items-end">
        <textarea
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 150)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!isLoading) void handleSend();
            }
          }}
          placeholder={isLoading ? "Tulis pesan berikutnya..." : "Tanya Claire apa saja..."}
          aria-label="Pesan untuk Claire"
          className="custom-scrollbar min-h-[58px] max-h-[150px] w-full resize-none rounded-[22px] bg-transparent py-4 pl-5 pr-16 text-base text-slate-100 placeholder:text-slate-600 focus:outline-none sm:pl-6"
          rows={1}
        />
        <button
          type="button"
          onClick={() => isLoading ? handleStop() : void handleSend()}
          disabled={!isLoading && !input.trim()}
          aria-label={isLoading ? "Hentikan respons" : "Kirim pesan"}
          className={`absolute bottom-2.5 right-2.5 flex h-9 w-9 cursor-pointer items-center justify-center rounded-xl transition-all duration-200 active:scale-95 disabled:cursor-not-allowed disabled:opacity-30 ${
            isLoading
              ? "border border-white/[0.1] bg-white/[0.07] text-slate-300 hover:bg-white/[0.12] hover:text-white"
              : "bg-gradient-to-br from-indigo-400 to-violet-500 text-white shadow-[0_6px_18px_rgba(99,102,241,0.32)] hover:brightness-110"
          }`}
        >
          {isLoading ? <Square size={13} fill="currentColor" /> : <Send size={16} className="ml-0.5" />}
        </button>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen overflow-hidden bg-[#0a0b0e] font-sans text-gray-100 selection:bg-indigo-500/30">
      
      <div className={`fixed md:relative z-30 flex-shrink-0 bg-[#161719] w-72 h-full flex flex-col transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] shadow-[4px_0_24px_rgba(0,0,0,0.5)] md:shadow-none border-r border-white/5
        ${isSidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0 md:w-0"}`}>
        
        <div className="p-6 flex items-center justify-between">
          <div className="flex flex-col">
            <span className="font-black text-2xl tracking-tighter text-white">
              CLAIRE<span className="text-indigo-500">.</span>
            </span>
            <span className="text-[9px] font-bold tracking-[0.2em] text-gray-500 uppercase mt-0.5">
              Personal Assistant
            </span>
          </div>
          <button onClick={() => setIsSidebarOpen(false)} className="md:hidden p-2 text-gray-400 hover:text-white cursor-pointer rounded-lg hover:bg-white/5">
            <X size={20} />
          </button>
        </div>

        <div className="px-3 pb-4 space-y-1">
          <button 
            onClick={() => handleNewChat(activeProjectId)}
            className="flex items-center justify-start gap-3 w-full p-3 rounded-xl bg-transparent text-sm font-medium text-gray-300 cursor-pointer transition-all duration-200 hover:bg-[#1e1f22] hover:text-white"
          >
            <Plus size={18} className="text-gray-400" />
            <span>{activeProject ? `Chat Baru di ${activeProject.name}` : "Mulai Obrolan Baru"}</span>
          </button>
          
          <button 
            onClick={() => setIsGraphOpen(true)}
            className="flex items-center justify-start gap-3 w-full p-3 rounded-xl bg-transparent text-sm font-medium text-gray-300 cursor-pointer transition-all duration-200 hover:bg-[#1e1f22] hover:text-white"
          >
            <Sparkles size={18} className="text-gray-400" />
            <span>Lihat Knowledge Graph</span>
          </button>

          <button 
            onClick={() => setIsStatsOpen(true)}
            className="flex items-center justify-start gap-3 w-full p-3 rounded-xl bg-transparent text-sm font-medium text-gray-300 cursor-pointer transition-all duration-200 hover:bg-[#1e1f22] hover:text-white"
          >
            <Activity size={18} className="text-gray-400" />
            <span>Statistik Sistem</span>
          </button>

          <button 
            onClick={() => setIsModelSettingsOpen(true)}
            className="flex items-center justify-start gap-3 w-full p-3 rounded-xl bg-transparent text-sm font-medium text-gray-300 cursor-pointer transition-all duration-200 hover:bg-[#1e1f22] hover:text-white"
          >
            <Settings size={18} className="text-gray-400" />
            <span>Pengaturan Model</span>
          </button>
        </div>

        <div className="border-y border-white/[0.05] px-3 py-4">
          <div className="mb-2 flex items-center justify-between px-3">
            <span className="text-[10px] font-bold uppercase tracking-[0.17em] text-gray-500">Projects</span>
            <button
              type="button"
              onClick={() => {
                setProjectError("");
                setIsProjectModalOpen(true);
              }}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-white/[0.06] hover:text-indigo-300"
              aria-label="Buat project baru"
              title="Project baru"
            >
              <Plus size={15} />
            </button>
          </div>
          <div className="max-h-44 space-y-1 overflow-y-auto custom-scrollbar">
            {activeProjectId && (
              <button
                type="button"
                onClick={() => handleNewChat(null)}
                className="mb-1 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-xs text-gray-500 transition-colors hover:bg-white/[0.04] hover:text-gray-300"
              >
                <ArrowLeft size={14} /> Semua chat
              </button>
            )}
            {projects.map((project) => {
              const selected = project.id === activeProjectId;
              return (
                <button
                  key={project.id}
                  type="button"
                  onClick={() => openProject(project.id)}
                  className={`group/project flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-all ${
                    selected
                      ? "bg-indigo-500/[0.12] text-indigo-200"
                      : "text-gray-400 hover:bg-white/[0.04] hover:text-gray-200"
                  }`}
                >
                  {selected ? <FolderOpen size={16} className="shrink-0 text-indigo-400" /> : <Folder size={16} className="shrink-0 text-gray-500 group-hover/project:text-indigo-400" />}
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{project.name}</span>
                  <span className={`text-[10px] tabular-nums ${selected ? "text-indigo-400/70" : "text-gray-600"}`}>
                    {project.session_count}
                  </span>
                </button>
              );
            })}
            {projects.length === 0 && (
              <button
                type="button"
                onClick={() => setIsProjectModalOpen(true)}
                className="w-full rounded-xl border border-dashed border-white/[0.07] px-3 py-3 text-left text-xs leading-relaxed text-gray-600 transition-colors hover:border-indigo-400/20 hover:text-gray-400"
              >
                Belum ada project. Buat ruang khusus untuk konteks yang tidak tercampur.
              </button>
            )}
          </div>
        </div>
        
        <div className="flex-1 overflow-y-auto px-3 pb-4 custom-scrollbar">
          <div className="mb-3 mt-4 flex items-center gap-2 px-3">
            {activeProject && <FolderOpen size={13} className="text-indigo-400" />}
            <span className="truncate text-[11px] font-bold uppercase tracking-widest text-gray-500">
              {activeProject ? activeProject.name : "Chat Personal"}
            </span>
          </div>
          {pinnedSessions.length > 0 && (
            <div className="mb-5">
              <div className="mb-2 ml-3 flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.16em] text-indigo-400/70">
                <Pin size={11} fill="currentColor" /> Disematkan
              </div>
              <div className="space-y-1">{pinnedSessions.map(renderSessionRow)}</div>
            </div>
          )}

          <div className="mb-3 ml-3 text-[11px] font-bold uppercase tracking-widest text-gray-500">Riwayat Sesi</div>
          <div className="space-y-1">{regularSessions.map(renderSessionRow)}</div>
          {scopedSessions.length === 0 && (
            <div className="mx-3 mt-5 rounded-xl border border-dashed border-white/[0.06] px-4 py-5 text-center text-xs leading-relaxed text-gray-600">
              {activeProject ? "Belum ada chat di project ini." : "Belum ada chat personal."}
            </div>
          )}
        </div>
        
      </div>

      <div className="chat-canvas relative flex h-full min-w-0 flex-1 flex-col bg-[#0b0c10]">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_50%_-10%,rgba(99,102,241,0.12),transparent_38%)]" />
        
        <div className="h-16 flex items-center px-5 border-b border-white/5 bg-[#161719]/80 backdrop-blur-md md:hidden z-10 sticky top-0">
          <button onClick={() => setIsSidebarOpen(true)} className="p-2 -ml-2 text-gray-400 hover:text-white cursor-pointer rounded-lg hover:bg-white/5">
            <Menu size={22} />
          </button>
          <div className="ml-3 flex flex-col">
            <span className="font-black text-lg tracking-tighter text-white leading-none">
              CLAIRE<span className="text-indigo-500">.</span>
            </span>
          </div>
        </div>

        <div className="hidden md:flex items-center justify-center p-3 border-b border-white/5 bg-transparent backdrop-blur-md relative z-40">
           {activeProject && (
             <div className="absolute left-6 top-1/2 flex -translate-y-1/2 items-center gap-2 text-sm text-gray-400">
               <FolderOpen size={15} className="text-indigo-400" />
               <span className="max-w-48 truncate">{activeProject.name}</span>
             </div>
           )}
           <button 
             onClick={() => setIsLogsOpen(true)}
             className="absolute right-6 top-1/2 -translate-y-1/2 flex items-center gap-2 px-3 py-1.5 rounded-xl border border-white/10 bg-[#1a1b1e]/80 hover:bg-[#25262a] text-gray-400 hover:text-white transition-colors cursor-pointer text-sm shadow-[0_2px_12px_rgba(0,0,0,0.2)]"
           >
             <Terminal size={16} />
             <span className="hidden lg:inline">Logs</span>
           </button>
           {models.length > 0 && (
             <div className="relative">
               <button 
                 onClick={() => setIsModelDropdownOpen(!isModelDropdownOpen)}
                 className="flex items-center gap-2 bg-[#1a1b1e]/80 hover:bg-[#25262a] px-4 py-2 rounded-2xl border border-white/10 transition-all cursor-pointer shadow-[0_2px_12px_rgba(0,0,0,0.2)] group"
               >
                  <div className={`w-2 h-2 rounded-full ${selectedModel?.provider === 'groq' ? 'bg-orange-500' : selectedModel?.provider === 'google' ? 'bg-blue-500' : selectedModel?.provider === 'huggingface' ? 'bg-yellow-400' : 'bg-emerald-500'} shadow-[0_0_8px_currentColor]`}></div>
                  <span className="text-sm font-medium text-gray-200 group-hover:text-white transition-colors">{selectedModel?.name || 'Pilih Model'}</span>
                  <svg className={`w-4 h-4 text-gray-400 transition-transform duration-300 ${isModelDropdownOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
               </button>

               {isModelDropdownOpen && (
                 <>
                   <div className="fixed inset-0 z-30" onClick={() => setIsModelDropdownOpen(false)}></div>
                   <div className="absolute top-full mt-2 w-64 bg-[#161719] border border-white/10 rounded-2xl shadow-[0_12px_40px_rgba(0,0,0,0.6)] py-2 z-50 animate-in fade-in zoom-in-95 duration-200">
                     <div className="px-3 pb-2 mb-2 border-b border-white/5">
                       <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Tersedia</span>
                     </div>
                     <div className="max-h-60 overflow-y-auto custom-scrollbar">
                       {models.map(m => (
                         <button 
                           key={m.id}
                           onClick={() => {
                             setSelectedModel(m);
                             localStorage.setItem("claire_selected_model", m.id);
                             setIsModelDropdownOpen(false);
                           }}
                           className={`w-full text-left px-4 py-2.5 flex items-center justify-between hover:bg-white/5 transition-colors cursor-pointer
                             ${selectedModel?.id === m.id ? 'bg-indigo-500/10 text-indigo-300' : 'text-gray-300'}`}
                         >
                           <div className="flex flex-col">
                             <span className="text-sm font-medium">{m.name}</span>
                             <span className="text-[10px] text-gray-500 uppercase tracking-widest">{m.provider}</span>
                           </div>
                           {selectedModel?.id === m.id && (
                             <div className="w-1.5 h-1.5 rounded-full bg-indigo-400"></div>
                           )}
                         </button>
                       ))}
                     </div>
                   </div>
                 </>
               )}
             </div>
           )}
        </div>

        <div className="custom-scrollbar relative flex-1 overflow-y-auto px-4 pb-8 pt-12 sm:px-10 sm:pt-16 md:px-16 lg:px-24">
          {messages.length === 0 && !isLoading && (
            <div className="h-full flex flex-col justify-center max-w-3xl mx-auto w-full animate-in fade-in duration-700 pb-20">
              <div className="space-y-2 mb-12">
                {activeProject && (
                  <div className="mb-5 flex items-center gap-2 text-sm font-medium text-indigo-300">
                    <FolderOpen size={16} />
                    <span className="truncate">Project {activeProject.name}</span>
                  </div>
                )}
                <h2 className="text-4xl md:text-5xl font-semibold tracking-tight bg-gradient-to-br from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                  Halo, Nafiz.
                </h2>
                <h2 className="text-4xl md:text-5xl font-semibold tracking-tight text-[#4b4e58]">
                  Ada yang bisa aku bantu hari ini?
                </h2>
              </div>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-10">
                {suggestedPrompts.map((chip) => (
                  <button 
                    key={chip.title}
                    onClick={() => {
                      setInput(chip.prompt);
                    }}
                    className="flex flex-col items-start p-5 bg-[#1e1f22] rounded-2xl border border-white/5 shadow-[inset_0_1px_2px_rgba(255,255,255,0.02),0_4px_12px_rgba(0,0,0,0.1)] hover:bg-[#25262a] transition-colors cursor-pointer text-left group"
                  >
                    <span className="text-sm font-medium text-gray-200 mb-1">{chip.title}</span>
                    <span className="text-xs text-gray-500 group-hover:text-gray-400 transition-colors">{chip.desc}</span>
                  </button>
                ))}
              </div>

              <div className="w-full">
                {renderInputForm()}
              </div>
            </div>
          )}
          
          {(messages.length > 0 || isLoading) && (
            <div className="mx-auto max-w-4xl">
              {messages.map((msg) => (
                <ChatBubble
                  key={msg.id}
                  role={msg.role}
                  content={msg.content}
                  isStreaming={msg.status === "streaming"}
                  webSearch={msg.webSearch}
                  internalError={msg.internalError}
                  isIncomplete={msg.status === "incomplete" || msg.response_status === "incomplete"}
                />
              ))}
              <div ref={bottomRef} className="h-32" />
            </div>
          )}
        </div>

        {(messages.length > 0 || isLoading) && (
          <div className="pointer-events-none absolute bottom-0 left-0 w-full animate-in bg-gradient-to-t from-[#0b0c10] via-[#0b0c10]/95 to-transparent px-4 pb-5 pt-14 duration-300 slide-in-from-bottom-4 sm:px-10 md:px-16 lg:px-24">
            <div className="relative mx-auto max-w-4xl pointer-events-auto">
              {renderInputForm()}
              <p className="text-center text-[11px] font-medium text-gray-500 mt-3 tracking-wide">
                Claire AI dapat berhalusinasi. Selalu verifikasi fakta yang penting.
              </p>
            </div>
          </div>
        )}
      </div>

      <Modal 
        isOpen={!!sessionToDelete}
        onClose={() => setSessionToDelete(null)}
        onConfirm={confirmDeleteSession}
        title="Hapus Percakapan"
        description="Kamu yakin ingin menghapus percakapan ini secara permanen? Data obrolan tidak bisa dikembalikan lagi lho."
        confirmText="Ya, Hapus"
        isDestructive={true}
      />

      <AnimatePresence>
        {isProjectModalOpen && (
          <motion.div
            className="fixed inset-0 z-[70] flex items-center justify-center bg-black/65 p-4 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onMouseDown={(event) => {
              if (event.target === event.currentTarget && !isCreatingProject) {
                setIsProjectModalOpen(false);
              }
            }}
          >
            <motion.div
              role="dialog"
              aria-modal="true"
              aria-labelledby="new-project-title"
              initial={{ opacity: 0, y: 14, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 10, scale: 0.98 }}
              transition={{ type: "spring", stiffness: 380, damping: 30 }}
              className="w-full max-w-md overflow-hidden rounded-[24px] border border-white/[0.09] bg-[#17181c] shadow-[0_28px_90px_rgba(0,0,0,0.65)]"
            >
              <div className="flex items-start justify-between border-b border-white/[0.06] px-6 py-5">
                <div className="flex gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-400">
                    <Folder size={19} />
                  </div>
                  <div>
                    <h2 id="new-project-title" className="font-semibold text-white">Project baru</h2>
                    <p className="mt-1 text-xs text-gray-500">Chat dan memori di dalamnya punya konteks khusus.</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setIsProjectModalOpen(false)}
                  disabled={isCreatingProject}
                  className="rounded-lg p-1.5 text-gray-500 transition-colors hover:bg-white/[0.05] hover:text-white disabled:opacity-40"
                  aria-label="Tutup"
                >
                  <X size={18} />
                </button>
              </div>
              <form
                className="space-y-4 p-6"
                onSubmit={(event) => {
                  event.preventDefault();
                  void createProject();
                }}
              >
                <label className="block">
                  <span className="mb-2 block text-xs font-medium text-gray-400">Nama project</span>
                  <input
                    autoFocus
                    value={newProjectName}
                    onChange={(event) => setNewProjectName(event.target.value)}
                    maxLength={120}
                    placeholder="Contoh: TCMudah"
                    className="w-full rounded-xl border border-white/[0.08] bg-[#101115] px-4 py-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-indigo-500/60"
                  />
                </label>
                <label className="block">
                  <span className="mb-2 block text-xs font-medium text-gray-400">Deskripsi <span className="text-gray-600">(opsional)</span></span>
                  <textarea
                    value={newProjectDescription}
                    onChange={(event) => setNewProjectDescription(event.target.value)}
                    maxLength={1000}
                    rows={3}
                    placeholder="Konteks singkat project ini..."
                    className="custom-scrollbar w-full resize-none rounded-xl border border-white/[0.08] bg-[#101115] px-4 py-3 text-sm text-white outline-none transition-colors placeholder:text-gray-700 focus:border-indigo-500/60"
                  />
                </label>
                {projectError && <p className="text-xs text-red-400">{projectError}</p>}
                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setIsProjectModalOpen(false)}
                    disabled={isCreatingProject}
                    className="rounded-xl px-4 py-2.5 text-sm text-gray-400 transition-colors hover:bg-white/[0.05] hover:text-white disabled:opacity-40"
                  >
                    Batal
                  </button>
                  <button
                    type="submit"
                    disabled={!newProjectName.trim() || isCreatingProject}
                    className="flex min-w-28 items-center justify-center gap-2 rounded-xl bg-indigo-500 px-4 py-2.5 text-sm font-medium text-white transition-all hover:bg-indigo-400 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {isCreatingProject && <LoaderCircle size={15} className="animate-spin" />}
                    Buat Project
                  </button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <GraphVisualizer 
        isOpen={isGraphOpen} 
        onClose={() => setIsGraphOpen(false)} 
      />

      <SystemStatsModal 
        isOpen={isStatsOpen} 
        onClose={() => setIsStatsOpen(false)} 
      />

      <ModelSettingsModal
        isOpen={isModelSettingsOpen}
        onClose={() => {
          setIsModelSettingsOpen(false);
          fetchModels();
        }}
      />

      <BackendLogsModal 
        isOpen={isLogsOpen}
        onClose={() => setIsLogsOpen(false)}
      />

    </div>
  );
}
