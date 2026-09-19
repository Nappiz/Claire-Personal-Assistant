"use client";

import dynamic from "next/dynamic";
import {
  AlertCircle,
  ChevronRight,
  Database,
  Focus,
  Loader2,
  Menu,
  Network,
  RefreshCw,
  RotateCcw,
  Search,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ForceGraphMethods, LinkObject, NodeObject } from "react-force-graph-2d";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), { ssr: false });

type GraphNode = {
  id: string;
  entity_key?: string | null;
  name: string;
  label: string;
  identity_context?: string | null;
  importance?: number | null;
};

type GraphLink = {
  id?: string | null;
  source: string | GraphNode;
  target: string | GraphNode;
  label: string;
  is_current?: boolean;
  memory_kind?: string | null;
  review_status?: string | null;
  confidence?: number | null;
  created_at?: string | number | null;
  last_confirmed_at?: string | number | null;
  observed_at?: string | number | null;
  expires_at?: string | number | null;
};

type GraphPayload = { nodes: GraphNode[]; links: GraphLink[] };
type ForceNode = NodeObject<GraphNode>;
type ForceLink = LinkObject<GraphNode, GraphLink>;

type GraphVisualizerProps = {
  isOpen: boolean;
  onClose: () => void;
};

const ENTITY_COLORS: Record<string, string> = {
  Person: "#fb7185",
  Location: "#34d399",
  Organization: "#60a5fa",
  Technology: "#22d3ee",
  Object: "#94a3b8",
  Event: "#fbbf24",
  Concept: "#a78bfa",
  Media: "#e879f9",
  Emotion: "#f87171",
  Activity: "#fb923c",
  Profession: "#facc15",
  Problem: "#ef4444",
  Entity: "#818cf8",
};

const EMPTY_GRAPH: GraphPayload = { nodes: [], links: [] };

function entityColor(label?: string) {
  return ENTITY_COLORS[label || "Entity"] || ENTITY_COLORS.Entity;
}

function endpointId(endpoint: ForceLink["source"] | GraphLink["source"]) {
  if (typeof endpoint === "object" && endpoint !== null) return String(endpoint.id ?? "");
  return String(endpoint ?? "");
}

function humanize(value?: string | null) {
  return String(value || "—")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function formatDate(value?: string | number | null) {
  if (value === null || value === undefined || value === "") return "—";
  const source = typeof value === "number" && value < 10_000_000_000 ? value * 1000 : value;
  const parsed = new Date(source);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat("id-ID", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-5 border-b border-white/[0.055] py-3 last:border-0">
      <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-slate-600">{label}</span>
      <span className="max-w-[64%] break-words text-right text-xs leading-5 text-slate-300">{value}</span>
    </div>
  );
}

export default function GraphVisualizer({ isOpen, onClose }: GraphVisualizerProps) {
  const [graphData, setGraphData] = useState<GraphPayload>(EMPTY_GRAPH);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [hiddenLabels, setHiddenLabels] = useState<Set<string>>(new Set());
  const [hiddenRelations, setHiddenRelations] = useState<Set<string>>(new Set());
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [hoveredLinkId, setHoveredLinkId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<ForceNode | null>(null);
  const [selectedLink, setSelectedLink] = useState<ForceLink | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [hasFitted, setHasFitted] = useState(false);
  const [memoryUpdating, setMemoryUpdating] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const graphRef = useRef<ForceGraphMethods<NodeObject, LinkObject> | undefined>(undefined);
  const requestRef = useRef<AbortController | null>(null);

  const loadGraph = useCallback(async (background = false) => {
    if (background && requestRef.current && !requestRef.current.signal.aborted) return false;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    if (!background) {
      setLoading(true);
      setError(null);
      setSelectedNode(null);
      setSelectedLink(null);
      setHasFitted(false);
    }

    try {
      const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1";
      const response = await fetch(`${apiBase}/memory/graph?limit=500`, {
        signal: controller.signal,
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`Graph API merespons ${response.status}`);
      const payload = (await response.json()) as Partial<GraphPayload>;
      if (!Array.isArray(payload.nodes) || !Array.isArray(payload.links)) {
        throw new Error("Format data graph tidak valid");
      }
      const nodes = payload.nodes;
      const links = payload.links;
      setGraphData((previous) => {
        const positions = new Map(previous.nodes.map((node) => [node.id, node as ForceNode]));
        return { nodes: nodes.map((node) => {
          const old = positions.get(node.id);
          return background && old ? { ...node, x: old.x, y: old.y, vx: old.vx, vy: old.vy } : node;
        }), links };
      });
      if (background) {
        setSelectedNode((selected) => selected ? nodes.find((node) => node.id === selected.id) ?? null : null);
        setSelectedLink((selected) => selected ? (links.find((link) => link.id === selected.id) as ForceLink | undefined) ?? null : null);
      } else {
        setFiltersOpen(false);
        setHiddenLabels(new Set());
        setHiddenRelations(new Set());
      }
      return true;
    } catch (caughtError) {
      if (caughtError instanceof DOMException && caughtError.name === "AbortError") return false;
      if (!background) setError(caughtError instanceof Error ? caughtError.message : "Knowledge graph gagal dimuat");
      return false;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      if (requestRef.current === controller) requestRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    const loadTimer = window.setTimeout(() => void loadGraph(), 0);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.clearTimeout(loadTimer);
      requestRef.current?.abort();
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen, loadGraph, onClose]);

  useEffect(() => {
    if (!isOpen) return;
    let stopped = false;
    let timer: number;
    let signature: string | null = null;
    const controller = new AbortController();
    const poll = async () => {
      try {
        if (document.visibilityState === "hidden") return;
        const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1";
        const response = await fetch(`${apiBase}/memory/jobs?limit=100`, {
          signal: controller.signal, cache: "no-store", headers: { Accept: "application/json" },
        });
        if (!response.ok) return;
        const payload = await response.json() as { jobs?: Array<{ id: string; status: string; graph_saved?: boolean; updated_at?: string }> };
        if (stopped || !Array.isArray(payload.jobs)) return;
        setMemoryUpdating(payload.jobs.some((job) => job.status === "pending" || job.status === "processing"));
        const next = JSON.stringify(payload.jobs.map((job) => [job.id, job.status, job.graph_saved, job.updated_at]).sort());
        if (next !== signature && await loadGraph(true)) signature = next;
      } catch {
        // Keep the last usable graph during a transient polling failure.
      } finally {
        if (!stopped) timer = window.setTimeout(() => void poll(), document.visibilityState === "hidden" ? 15000 : 3000);
      }
    };
    timer = window.setTimeout(() => void poll(), 3000);
    return () => { stopped = true; window.clearTimeout(timer); controller.abort(); };
  }, [isOpen, loadGraph]);

  useEffect(() => {
    if (!isOpen || !containerRef.current) return;
    const element = containerRef.current;
    const updateDimensions = () => {
      setDimensions({ width: element.clientWidth, height: element.clientHeight });
    };
    updateDimensions();
    const observer = new ResizeObserver(updateDimensions);
    observer.observe(element);
    return () => observer.disconnect();
  }, [isOpen]);

  const labelStats = useMemo(() => {
    const counts = new Map<string, number>();
    graphData.nodes.forEach((node) => {
      const label = node.label || "Entity";
      counts.set(label, (counts.get(label) || 0) + 1);
    });
    return [...counts.entries()].sort((left, right) => right[1] - left[1]);
  }, [graphData.nodes]);

  const relationStats = useMemo(() => {
    const counts = new Map<string, number>();
    graphData.links.forEach((link) => {
      const label = link.label || "RELATED_TO";
      counts.set(label, (counts.get(label) || 0) + 1);
    });
    return [...counts.entries()].sort((left, right) => right[1] - left[1]);
  }, [graphData.links]);

  const visibleGraph = useMemo<GraphPayload>(() => {
    const nodes = graphData.nodes
      .filter((node) => !hiddenLabels.has(node.label || "Entity"))
      .map((node) => ({ ...node }));
    const nodeIds = new Set(nodes.map((node) => String(node.id)));
    const links = graphData.links
      .filter((link) =>
        !hiddenRelations.has(link.label || "RELATED_TO") &&
        nodeIds.has(endpointId(link.source)) &&
        nodeIds.has(endpointId(link.target)),
      )
      .map((link) => ({ ...link, source: endpointId(link.source), target: endpointId(link.target) }));
    return { nodes, links };
  }, [graphData, hiddenLabels, hiddenRelations]);

  const normalizedSearch = searchQuery.trim().toLocaleLowerCase("id-ID");
  const searchResults = useMemo(() => {
    if (!normalizedSearch) return [];
    return graphData.nodes
      .filter((node) =>
        `${node.name} ${node.label} ${node.identity_context || ""}`
          .toLocaleLowerCase("id-ID")
          .includes(normalizedSearch),
      )
      .slice(0, 7);
  }, [graphData.nodes, normalizedSearch]);

  const nodeById = useMemo(
    () => new Map(graphData.nodes.map((node) => [String(node.id), node])),
    [graphData.nodes],
  );

  const selectedNodeConnections = useMemo(() => {
    if (!selectedNode) return [];
    const selectedId = String(selectedNode.id);
    return graphData.links
      .filter((link) => endpointId(link.source) === selectedId || endpointId(link.target) === selectedId)
      .slice(0, 12)
      .map((link) => {
        const sourceId = endpointId(link.source);
        const otherId = sourceId === selectedId ? endpointId(link.target) : sourceId;
        return { link, node: nodeById.get(otherId), outgoing: sourceId === selectedId };
      });
  }, [graphData.links, nodeById, selectedNode]);

  const selectedNodeId = selectedNode ? String(selectedNode.id) : null;
  const selectedLinkId = selectedLink ? String(selectedLink.id || "") : null;
  const connectedNodeIds = useMemo(() => {
    if (!selectedNodeId) return new Set<string>();
    const ids = new Set<string>([selectedNodeId]);
    visibleGraph.links.forEach((link) => {
      const sourceId = endpointId(link.source);
      const targetId = endpointId(link.target);
      if (sourceId === selectedNodeId) ids.add(targetId);
      if (targetId === selectedNodeId) ids.add(sourceId);
    });
    return ids;
  }, [selectedNodeId, visibleGraph.links]);

  const fitGraph = useCallback(() => graphRef.current?.zoomToFit(650, 90), []);

  const focusNode = useCallback((node: ForceNode | GraphNode) => {
    setHiddenLabels((current) => {
      if (!current.has(node.label || "Entity")) return current;
      const next = new Set(current);
      next.delete(node.label || "Entity");
      return next;
    });
    setSelectedLink(null);
    setSelectedNode(node as ForceNode);
    setSearchQuery("");
    window.setTimeout(() => {
      const target = node as ForceNode;
      if (typeof target.x === "number" && typeof target.y === "number") {
        graphRef.current?.centerAt(target.x, target.y, 650);
        graphRef.current?.zoom(3.6, 650);
      }
    }, 40);
  }, []);

  const drawNode = useCallback(
    (node: ForceNode, context: CanvasRenderingContext2D, globalScale: number) => {
      if (typeof node.x !== "number" || typeof node.y !== "number") return;
      const color = entityColor(node.label);
      const importance = Math.max(0.5, Number(node.importance) || 1);
      const radius = Math.min(12, 5.2 + Math.sqrt(importance) * 1.8);
      const id = String(node.id);
      const isSelected = selectedNodeId === id;
      const isHovered = hoveredNodeId === id;
      const searchableText = `${node.name} ${node.label} ${node.identity_context || ""}`.toLocaleLowerCase("id-ID");
      const matchesSearch = Boolean(normalizedSearch && searchableText.includes(normalizedSearch));
      const isDimmed =
        (selectedNodeId !== null && !connectedNodeIds.has(id)) ||
        (normalizedSearch !== "" && !matchesSearch);

      context.save();
      context.globalAlpha = isDimmed ? 0.15 : 1;
      context.beginPath();
      context.arc(node.x, node.y, radius + (isSelected ? 4 : 2.5), 0, Math.PI * 2);
      context.fillStyle = `${color}${isSelected ? "32" : "18"}`;
      context.shadowColor = color;
      context.shadowBlur = isSelected || isHovered ? 24 : 12;
      context.fill();

      context.shadowBlur = 0;
      context.beginPath();
      context.arc(node.x, node.y, radius, 0, Math.PI * 2);
      context.fillStyle = color;
      context.fill();
      context.lineWidth = (isSelected ? 2.2 : 1.1) / Math.max(globalScale, 0.5);
      context.strokeStyle = isSelected ? "#ffffff" : "rgba(255,255,255,0.55)";
      context.stroke();

      context.beginPath();
      context.arc(node.x - radius * 0.28, node.y - radius * 0.3, radius * 0.23, 0, Math.PI * 2);
      context.fillStyle = "rgba(255,255,255,0.64)";
      context.fill();

      if (isSelected || isHovered || matchesSearch || globalScale > 5.25 || importance >= 4) {
        const label = node.name || "Unknown";
        const fontSize = Math.max(3.2, 11 / globalScale);
        context.font = `600 ${fontSize}px ui-sans-serif, system-ui, sans-serif`;
        const paddingX = 4.5 / globalScale;
        const paddingY = 3 / globalScale;
        const width = context.measureText(label).width + paddingX * 2;
        const height = fontSize + paddingY * 2;
        const x = node.x - width / 2;
        const y = node.y + radius + 4 / globalScale;
        context.fillStyle = "rgba(7,9,16,0.91)";
        context.strokeStyle = isSelected ? `${color}aa` : "rgba(255,255,255,0.1)";
        context.lineWidth = 0.8 / globalScale;
        context.beginPath();
        context.roundRect(x, y, width, height, 4 / globalScale);
        context.fill();
        context.stroke();
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillStyle = "rgba(248,250,252,0.95)";
        context.fillText(label, node.x, y + height / 2);
      }
      context.restore();
    },
    [connectedNodeIds, hoveredNodeId, normalizedSearch, selectedNodeId],
  );

  const drawLinkLabel = useCallback(
    (link: ForceLink, context: CanvasRenderingContext2D, globalScale: number) => {
      const source = link.source as ForceNode;
      const target = link.target as ForceNode;
      if (
        typeof source !== "object" || typeof target !== "object" ||
        typeof source.x !== "number" || typeof source.y !== "number" ||
        typeof target.x !== "number" || typeof target.y !== "number"
      ) return;
      const id = String(link.id || "");
      const touchesSelected = selectedNodeId !== null &&
        (String(source.id) === selectedNodeId || String(target.id) === selectedNodeId);
      if (selectedLinkId !== id && hoveredLinkId !== id && !touchesSelected) return;

      const label = humanize(link.label);
      const fontSize = Math.max(3, 9.5 / globalScale);
      const x = (source.x + target.x) / 2;
      const y = (source.y + target.y) / 2;
      context.save();
      context.font = `600 ${fontSize}px ui-sans-serif, system-ui, sans-serif`;
      const width = context.measureText(label).width + 8 / globalScale;
      const height = fontSize + 5 / globalScale;
      context.fillStyle = "rgba(8,10,18,0.92)";
      context.strokeStyle = "rgba(129,140,248,0.35)";
      context.lineWidth = 0.7 / globalScale;
      context.beginPath();
      context.roundRect(x - width / 2, y - height / 2, width, height, 3 / globalScale);
      context.fill();
      context.stroke();
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillStyle = "rgba(203,213,225,0.95)";
      context.fillText(label, x, y);
      context.restore();
    },
    [hoveredLinkId, selectedLinkId, selectedNodeId],
  );

  const toggleLabel = (label: string) => {
    setSelectedNode(null);
    setSelectedLink(null);
    setHasFitted(false);
    setHiddenLabels((current) => {
      const next = new Set(current);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const toggleRelation = (label: string) => {
    setSelectedNode(null);
    setSelectedLink(null);
    setHasFitted(false);
    setHiddenRelations((current) => {
      const next = new Set(current);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  };

  const clearFilters = () => {
    setHiddenLabels(new Set());
    setHiddenRelations(new Set());
    setSelectedNode(null);
    setSelectedLink(null);
    setHasFitted(false);
  };

  if (!isOpen) return null;

  const activeSelection = selectedNode || selectedLink;
  const selectedLinkSource = selectedLink ? nodeById.get(endpointId(selectedLink.source)) : undefined;
  const selectedLinkTarget = selectedLink ? nodeById.get(endpointId(selectedLink.target)) : undefined;

  return (
    <div
      className="fixed inset-0 z-[70] flex flex-col overflow-hidden bg-[#070911] text-slate-100 animate-in fade-in duration-300"
      role="dialog"
      aria-modal="true"
      aria-label="Visualisasi Knowledge Graph"
    >
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_12%_10%,rgba(99,102,241,0.12),transparent_28%),radial-gradient(circle_at_84%_18%,rgba(14,165,233,0.08),transparent_25%),radial-gradient(circle_at_52%_100%,rgba(168,85,247,0.07),transparent_32%)]" />

      <header className="relative z-20 border-b border-white/[0.07] bg-[#090b13]/80 px-4 py-3 backdrop-blur-2xl sm:px-6 lg:px-8">
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <h2 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-slate-100 sm:text-base">Visualisasi Knowledge Graph</h2>
              <span className="hidden text-[9px] font-semibold uppercase tracking-[0.2em] text-indigo-300 sm:inline">Claire Knowledge</span>
            </div>
            <p className="mt-0.5 hidden text-[11px] text-slate-500 sm:block">Lihat bagaimana ingatan Claire saling terhubung</p>
          </div>

          <div className="hidden items-center gap-6 lg:flex">
            {[[graphData.nodes.length, "Entitas"], [graphData.links.length, "Relasi"], [labelStats.length, "Kategori"]].map(([value, label], index) => (
              <div key={String(label)} className="contents">
                {index > 0 && <div className="h-7 w-px bg-white/[0.07]" />}
                <div className="text-right">
                  <div className="text-sm font-semibold tabular-nums text-slate-200">{value}</div>
                  <div className="text-[9px] uppercase tracking-[0.16em] text-slate-600">{label}</div>
                </div>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button type="button" onClick={() => void loadGraph()} disabled={loading} className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-xl border border-white/[0.07] bg-white/[0.035] text-slate-400 transition hover:border-white/[0.12] hover:bg-white/[0.07] hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-50" aria-label="Muat ulang graph">
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            </button>
            <button type="button" onClick={onClose} className="flex h-9 w-9 cursor-pointer items-center justify-center rounded-xl border border-white/[0.07] bg-white/[0.035] text-slate-400 transition hover:border-rose-400/20 hover:bg-rose-400/10 hover:text-rose-200" aria-label="Tutup Knowledge Graph">
              <X size={17} />
            </button>
          </div>
        </div>
      </header>

      <div className="relative z-10 flex min-h-0 flex-1">
        <main className="relative min-w-0 flex-1 overflow-hidden">
          <div className="absolute left-4 right-4 top-4 z-20 flex flex-col gap-2.5 sm:left-6 sm:right-auto sm:w-[min(780px,calc(100%-3rem))]">
            <div className="flex items-start gap-2.5">
              <div className="relative z-30 min-w-0 flex-1">
                <Search size={15} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-500" />
                <input
                  ref={searchRef}
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder="Cari entitas, tipe, atau konteks..."
                  className="h-11 w-full rounded-2xl border border-white/[0.08] bg-[#0d101a]/88 pl-10 pr-14 text-sm text-slate-200 shadow-[0_12px_35px_rgba(0,0,0,0.3)] outline-none backdrop-blur-xl transition placeholder:text-slate-600 focus:border-indigo-400/30 focus:bg-[#10131f]/95 focus:ring-4 focus:ring-indigo-500/[0.06]"
                />
                {searchQuery ? (
                  <button type="button" onClick={() => setSearchQuery("")} className="absolute right-3 top-1/2 flex h-6 w-6 -translate-y-1/2 cursor-pointer items-center justify-center rounded-lg text-slate-500 transition hover:bg-white/[0.06] hover:text-slate-200" aria-label="Hapus pencarian"><X size={13} /></button>
                ) : (
                  <kbd className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded-md border border-white/[0.07] bg-white/[0.035] px-1.5 py-0.5 font-sans text-[10px] text-slate-600">/</kbd>
                )}

                {normalizedSearch && (
                  <div className="absolute left-0 right-0 top-[calc(100%+8px)] overflow-hidden rounded-2xl border border-white/[0.08] bg-[#0c0f18]/95 p-1.5 shadow-[0_24px_60px_rgba(0,0,0,0.5)] backdrop-blur-2xl">
                    {searchResults.length > 0 ? searchResults.map((node) => (
                      <button key={node.id} type="button" onClick={() => focusNode(node)} className="group flex w-full cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-left transition hover:bg-white/[0.055]">
                        <span className="h-2.5 w-2.5 shrink-0 rounded-full shadow-[0_0_10px_currentColor]" style={{ color: entityColor(node.label), backgroundColor: entityColor(node.label) }} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-xs font-medium text-slate-200">{node.name}</span>
                          <span className="mt-0.5 block text-[10px] uppercase tracking-[0.12em] text-slate-600">{node.label}</span>
                        </span>
                        <ChevronRight size={14} className="text-slate-700 transition group-hover:translate-x-0.5 group-hover:text-slate-400" />
                      </button>
                    )) : <div className="px-3 py-5 text-center text-xs text-slate-500">Tidak ada entitas yang cocok</div>}
                  </div>
                )}
              </div>

              {(labelStats.length > 0 || relationStats.length > 0) && (
                <button
                  type="button"
                  onClick={() => setFiltersOpen((current) => !current)}
                  aria-expanded={filtersOpen}
                  aria-controls="knowledge-graph-filters"
                  className={`relative flex h-11 shrink-0 cursor-pointer items-center justify-center gap-2 rounded-2xl border px-3.5 text-xs font-medium shadow-[0_12px_35px_rgba(0,0,0,0.3)] backdrop-blur-xl transition ${filtersOpen ? "border-indigo-400/25 bg-indigo-500/15 text-indigo-200" : "border-white/[0.08] bg-[#0d101a]/88 text-slate-400 hover:border-white/[0.13] hover:bg-[#111521]/95 hover:text-slate-200"}`}
                  aria-label={filtersOpen ? "Tutup filter graph" : "Buka filter graph"}
                >
                  <Menu size={16} />
                  <span className="hidden sm:inline">Filter</span>
                  {(hiddenLabels.size > 0 || hiddenRelations.size > 0) && (
                    <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-indigo-400 px-1 text-[8px] font-bold tabular-nums text-[#090b13] shadow-[0_0_12px_rgba(129,140,248,0.7)]">
                      {hiddenLabels.size + hiddenRelations.size}
                    </span>
                  )}
                </button>
              )}
            </div>

            {filtersOpen && (labelStats.length > 0 || relationStats.length > 0) && (
              <div id="knowledge-graph-filters" className="custom-scrollbar relative z-20 max-h-[min(60vh,520px)] overflow-y-auto rounded-2xl border border-white/[0.07] bg-[#0d1018]/94 p-3 shadow-[0_20px_55px_rgba(0,0,0,0.42)] backdrop-blur-2xl animate-in fade-in slide-in-from-top-2 duration-200">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Filter graph</span>
                  <button
                    type="button"
                    onClick={clearFilters}
                    disabled={hiddenLabels.size === 0 && hiddenRelations.size === 0}
                    className="flex cursor-pointer items-center gap-1.5 text-[10px] font-medium text-indigo-300 transition hover:text-indigo-200 disabled:cursor-default disabled:text-slate-700"
                  >
                    <RotateCcw size={11} /> Clear filter
                  </button>
                </div>

                {labelStats.length > 0 && (
                  <div>
                    <div className="mb-2 text-[9px] font-medium uppercase tracking-[0.14em] text-slate-600">Kategori node</div>
                    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                      {labelStats.map(([label, count]) => {
                        const hidden = hiddenLabels.has(label);
                        return (
                          <button key={label} type="button" title={label} onClick={() => toggleLabel(label)} aria-pressed={!hidden} className={`flex min-w-0 cursor-pointer items-center gap-2 rounded-xl border px-2.5 py-2 text-[10px] font-medium transition ${hidden ? "border-white/[0.045] bg-black/10 text-slate-600" : "border-white/[0.08] bg-white/[0.035] text-slate-300 hover:border-white/[0.13] hover:bg-white/[0.055]"}`}>
                            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${hidden ? "opacity-30" : "shadow-[0_0_8px_currentColor]"}`} style={{ color: entityColor(label), backgroundColor: entityColor(label) }} />
                            <span className="min-w-0 flex-1 truncate text-left">{label}</span>
                            <span className="shrink-0 tabular-nums text-slate-600">{count}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {relationStats.length > 0 && (
                  <div className="mt-3 border-t border-white/[0.055] pt-3">
                    <div className="mb-2 text-[9px] font-medium uppercase tracking-[0.14em] text-slate-600">Relasi</div>
                    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
                      {relationStats.map(([label, count]) => {
                        const hidden = hiddenRelations.has(label);
                        return (
                          <button key={label} type="button" title={humanize(label)} onClick={() => toggleRelation(label)} aria-pressed={!hidden} className={`flex min-w-0 cursor-pointer items-center gap-2 rounded-xl border px-2.5 py-2 text-[10px] font-medium transition ${hidden ? "border-white/[0.045] bg-black/10 text-slate-600" : "border-white/[0.08] bg-white/[0.035] text-slate-300 hover:border-indigo-300/20 hover:bg-indigo-400/[0.055]"}`}>
                            <span className={`h-px w-3 shrink-0 bg-indigo-300 ${hidden ? "opacity-20" : "shadow-[0_0_7px_rgba(165,180,252,0.75)]"}`} />
                            <span className="min-w-0 flex-1 truncate text-left">{humanize(label)}</span>
                            <span className="shrink-0 tabular-nums text-slate-600">{count}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <div ref={containerRef} className="knowledge-graph-surface absolute inset-0">
            {loading ? (
              <div className="absolute inset-0 z-10 flex items-center justify-center">
                <div className="flex flex-col items-center">
                  <div className="relative mb-5 flex h-16 w-16 items-center justify-center">
                    <div className="absolute inset-0 animate-ping rounded-full border border-indigo-400/15" />
                    <div className="absolute inset-2 animate-pulse rounded-full border border-indigo-300/20 bg-indigo-500/[0.06]" />
                    <Loader2 size={22} className="animate-spin text-indigo-300" />
                  </div>
                  <p className="text-sm font-medium text-slate-300">Menyusun peta memori</p>
                  <p className="mt-1.5 text-xs text-slate-600">Menghubungkan entitas dan relasi...</p>
                </div>
              </div>
            ) : error ? (
              <div className="absolute inset-0 z-10 flex items-center justify-center px-6">
                <div className="max-w-sm rounded-3xl border border-rose-400/10 bg-[#10121b]/90 p-7 text-center shadow-2xl backdrop-blur-xl">
                  <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-2xl bg-rose-400/10 text-rose-300"><AlertCircle size={20} /></div>
                  <h3 className="text-sm font-semibold text-slate-200">Graph belum bisa dimuat</h3>
                  <p className="mt-2 text-xs leading-5 text-slate-500">{error}</p>
                  <button type="button" onClick={() => void loadGraph()} className="mt-5 cursor-pointer rounded-xl border border-indigo-400/20 bg-indigo-500/10 px-4 py-2 text-xs font-medium text-indigo-200 transition hover:bg-indigo-500/20">Coba lagi</button>
                </div>
              </div>
            ) : graphData.nodes.length === 0 ? (
              <div className="absolute inset-0 z-10 flex items-center justify-center px-6">
                <div className="max-w-sm text-center">
                  <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl border border-white/[0.07] bg-white/[0.035] text-slate-500"><Database size={22} /></div>
                  <h3 className="text-sm font-semibold text-slate-300">Memory atlas masih kosong</h3>
                  <p className="mt-2 text-xs leading-5 text-slate-600">Entitas dan hubungan akan muncul setelah Claire menyimpan fakta dari percakapanmu.</p>
                </div>
              </div>
            ) : dimensions.width > 0 && dimensions.height > 0 ? (
              <ForceGraph2D
                ref={graphRef}
                width={dimensions.width}
                height={dimensions.height}
                graphData={visibleGraph}
                nodeId="id"
                nodeLabel={() => ""}
                nodeVal={(node) => Math.max(1, Number((node as ForceNode).importance) || 1)}
                nodeCanvasObject={(node, context, scale) => drawNode(node as ForceNode, context, scale)}
                nodePointerAreaPaint={(node, color, context) => {
                  const item = node as ForceNode;
                  if (typeof item.x !== "number" || typeof item.y !== "number") return;
                  context.fillStyle = color;
                  context.beginPath();
                  context.arc(item.x, item.y, 11, 0, Math.PI * 2);
                  context.fill();
                }}
                linkLabel={() => ""}
                linkColor={(link) => {
                  const item = link as ForceLink;
                  const id = String(item.id || "");
                  const related = selectedNodeId !== null && (endpointId(item.source) === selectedNodeId || endpointId(item.target) === selectedNodeId);
                  if (selectedLinkId === id || hoveredLinkId === id) return "rgba(199,210,254,0.98)";
                  if (related) return "rgba(165,180,252,0.78)";
                  if (selectedNodeId || normalizedSearch) return "rgba(100,116,139,0.12)";
                  return "rgba(129,140,248,0.46)";
                }}
                linkWidth={(link) => selectedLinkId === String((link as ForceLink).id || "") || hoveredLinkId === String((link as ForceLink).id || "") ? 2.2 : 0.9}
                linkCurvature={0.16}
                linkDirectionalArrowLength={4.5}
                linkDirectionalArrowRelPos={0.92}
                linkDirectionalArrowColor={(link) => {
                  const item = link as ForceLink;
                  const id = String(item.id || "");
                  const related = selectedNodeId !== null && (endpointId(item.source) === selectedNodeId || endpointId(item.target) === selectedNodeId);
                  if (selectedLinkId === id || hoveredLinkId === id) return "rgba(224,231,255,1)";
                  if (related) return "rgba(199,210,254,0.92)";
                  if (selectedNodeId || normalizedSearch) return "rgba(100,116,139,0.22)";
                  return "rgba(165,180,252,0.78)";
                }}
                linkDirectionalParticles={(link) => selectedLinkId === String((link as ForceLink).id || "") || hoveredLinkId === String((link as ForceLink).id || "") ? 2 : 0}
                linkDirectionalParticleWidth={1.8}
                linkDirectionalParticleSpeed={0.004}
                linkDirectionalParticleColor={() => "#a5b4fc"}
                linkCanvasObjectMode={() => "after"}
                linkCanvasObject={(link, context, scale) => drawLinkLabel(link as ForceLink, context, scale)}
                onNodeHover={(node) => setHoveredNodeId(node ? String(node.id) : null)}
                onLinkHover={(link) => setHoveredLinkId(link ? String(link.id || "") : null)}
                onNodeClick={(node) => focusNode(node as ForceNode)}
                onLinkClick={(link) => { setSelectedNode(null); setSelectedLink(link as ForceLink); }}
                onBackgroundClick={() => { setSelectedNode(null); setSelectedLink(null); }}
                onEngineStop={() => { if (!hasFitted) { setHasFitted(true); fitGraph(); } }}
                showPointerCursor
                minZoom={0.25}
                maxZoom={8}
                backgroundColor="rgba(0,0,0,0)"
                d3VelocityDecay={0.34}
                cooldownTicks={120}
              />
            ) : null}
          </div>

          {!loading && !error && graphData.nodes.length > 0 && (
            <>
            {memoryUpdating && <p role="status" className="absolute bottom-5 left-5 z-20 rounded-lg bg-black/70 px-3 py-2 text-xs text-slate-300">Memori sedang diperbarui. Graph akan mengikuti hasil terbaru.</p>}
            <div className="absolute bottom-5 right-4 z-20 flex flex-col gap-1.5 sm:right-6">
              <button type="button" onClick={() => graphRef.current?.zoom((graphRef.current?.zoom() || 1) * 1.35, 250)} className="graph-control" aria-label="Perbesar graph"><ZoomIn size={15} /></button>
              <button type="button" onClick={() => graphRef.current?.zoom((graphRef.current?.zoom() || 1) / 1.35, 250)} className="graph-control" aria-label="Perkecil graph"><ZoomOut size={15} /></button>
              <button type="button" onClick={fitGraph} className="graph-control" aria-label="Tampilkan seluruh graph"><Focus size={15} /></button>
            </div>
            </>
          )}
        </main>

        {activeSelection && (
          <aside className="absolute inset-x-3 bottom-3 z-30 max-h-[46%] overflow-hidden rounded-3xl border border-white/[0.08] bg-[#0c0f18]/95 shadow-[0_28px_80px_rgba(0,0,0,0.62)] backdrop-blur-2xl animate-in slide-in-from-bottom-5 duration-300 md:static md:inset-auto md:m-0 md:max-h-none md:w-[340px] md:shrink-0 md:rounded-none md:border-y-0 md:border-r-0 md:bg-[#0a0d15]/88 md:shadow-[-24px_0_70px_rgba(0,0,0,0.24)] md:slide-in-from-right-4">
            <div className="flex h-full flex-col">
              <div className="flex items-start justify-between border-b border-white/[0.06] px-5 py-5">
                <div className="min-w-0 pr-4">
                  {selectedNode ? (
                    <>
                      <div className="mb-3 flex items-center gap-2">
                        <span className="h-2 w-2 rounded-full shadow-[0_0_12px_currentColor]" style={{ color: entityColor(selectedNode.label), backgroundColor: entityColor(selectedNode.label) }} />
                        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{selectedNode.label || "Entity"}</span>
                      </div>
                      <h3 className="truncate text-lg font-semibold tracking-[-0.02em] text-slate-100">{selectedNode.name}</h3>
                      {selectedNode.identity_context && <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-slate-500">{selectedNode.identity_context}</p>}
                    </>
                  ) : selectedLink ? (
                    <>
                      <div className="mb-3 flex items-center gap-2 text-indigo-300"><Network size={13} /><span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Relationship</span></div>
                      <h3 className="text-base font-semibold text-slate-100">{humanize(selectedLink.label)}</h3>
                      <p className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
                        <span className="truncate">{selectedLinkSource?.name || "Unknown"}</span><ChevronRight size={12} className="shrink-0 text-indigo-400" /><span className="truncate">{selectedLinkTarget?.name || "Unknown"}</span>
                      </p>
                    </>
                  ) : null}
                </div>
                <button type="button" onClick={() => { setSelectedNode(null); setSelectedLink(null); }} className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-xl bg-white/[0.035] text-slate-500 transition hover:bg-white/[0.07] hover:text-slate-200" aria-label="Tutup detail"><X size={14} /></button>
              </div>

              <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-5 py-2">
                {selectedNode ? (
                  <>
                    <DetailRow label="Importance" value={Number(selectedNode.importance || 1).toFixed(1)} />
                    <DetailRow label="Entity key" value={selectedNode.entity_key || "—"} />
                    <div className="pb-5 pt-5">
                      <div className="mb-3 flex items-center justify-between">
                        <h4 className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Connections</h4>
                        <span className="rounded-md bg-white/[0.04] px-1.5 py-0.5 text-[10px] tabular-nums text-slate-600">{selectedNodeConnections.length}</span>
                      </div>
                      <div className="space-y-1.5">
                        {selectedNodeConnections.length ? selectedNodeConnections.map(({ link, node, outgoing }, index) => (
                          <button key={`${link.id || link.label}-${index}`} type="button" onClick={() => node && focusNode(node)} className="group flex w-full cursor-pointer items-center gap-3 rounded-xl border border-transparent bg-white/[0.025] px-3 py-2.5 text-left transition hover:border-white/[0.06] hover:bg-white/[0.055]">
                            <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: entityColor(node?.label) }} />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-xs text-slate-300">{node?.name || "Unknown"}</span>
                              <span className="mt-0.5 block truncate text-[9px] uppercase tracking-[0.1em] text-slate-600">{outgoing ? "→" : "←"} {humanize(link.label)}</span>
                            </span>
                            <ChevronRight size={12} className="text-slate-700 transition group-hover:text-slate-400" />
                          </button>
                        )) : <p className="rounded-xl bg-white/[0.025] px-3 py-4 text-center text-xs text-slate-600">Tidak ada koneksi aktif</p>}
                      </div>
                    </div>
                  </>
                ) : selectedLink ? (
                  <>
                    <DetailRow label="Jenis" value={humanize(selectedLink.memory_kind)} />
                    <DetailRow label="Status" value={humanize(selectedLink.review_status)} />
                    <DetailRow label="Confidence" value={`${Math.round(Math.max(0, Math.min(1, Number(selectedLink.confidence ?? 1))) * 100)}%`} />
                    <DetailRow label="Current" value={selectedLink.is_current === false ? "Tidak" : "Ya"} />
                    <DetailRow label="Dibuat" value={formatDate(selectedLink.created_at)} />
                    <DetailRow label="Dikonfirmasi" value={formatDate(selectedLink.last_confirmed_at)} />
                    <DetailRow label="Diamati" value={formatDate(selectedLink.observed_at)} />
                    {selectedLink.expires_at && <DetailRow label="Kedaluwarsa" value={formatDate(selectedLink.expires_at)} />}
                  </>
                ) : null}
              </div>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
