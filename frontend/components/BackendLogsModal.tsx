import { useState, useEffect, useRef } from "react";
import { Terminal, X, RefreshCw } from "lucide-react";

interface BackendLogsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function BackendLogsModal({ isOpen, onClose }: BackendLogsModalProps) {
  const [logs, setLogs] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  const fetchLogs = async () => {
    setIsLoading(true);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/logs`);
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs || "No logs available.");
      } else {
        setLogs("Error fetching logs.");
      }
    } catch (err) {
      setLogs("Failed to connect to backend to fetch logs.");
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchLogs();
    }
  }, [isOpen]);

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs, isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div 
        className="w-full max-w-4xl max-h-[85vh] bg-[#161719] rounded-2xl border border-white/10 shadow-[0_24px_60px_rgba(0,0,0,0.8)] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-5 border-b border-white/5 bg-[#1a1b1e]">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-500/10 rounded-xl">
              <Terminal size={20} className="text-indigo-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Backend Logs</h2>
              <p className="text-xs text-gray-400">Log terminal dari server FastAPI</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button 
              onClick={fetchLogs}
              disabled={isLoading}
              className="p-2 text-gray-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors cursor-pointer"
              title="Refresh Logs"
            >
              <RefreshCw size={18} className={isLoading ? "animate-spin text-indigo-400" : ""} />
            </button>
            <button 
              onClick={onClose}
              className="p-2 text-gray-400 hover:text-white hover:bg-white/5 rounded-lg transition-colors cursor-pointer"
            >
              <X size={20} />
            </button>
          </div>
        </div>
        
        <div className="flex-1 overflow-y-auto p-4 bg-[#0d0e10] custom-scrollbar font-mono text-sm leading-relaxed text-gray-300">
          <pre className="whitespace-pre-wrap break-words">{logs}</pre>
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
}
