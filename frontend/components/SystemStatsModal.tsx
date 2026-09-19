import { useEffect, useState } from 'react';
import { X, Loader2, Database, BrainCircuit, MessageSquare, Network, Box, Activity } from 'lucide-react';

type SystemStatsModalProps = {
  isOpen: boolean;
  onClose: () => void;
};

type Stats = {
  sessions: number;
  messages: number;
  tokens: number;
  graph_nodes: number;
  graph_edges: number;
  vector_memories: number;
};

export default function SystemStatsModal({ isOpen, onClose }: SystemStatsModalProps) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setLoading(true);
      fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/system/stats`)
        .then(res => res.json())
        .then(data => {
          setStats(data);
          setLoading(false);
        })
        .catch(err => {
          console.error(err);
          setLoading(false);
        });
    }
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-[#0d0e10]/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-[#161719] border border-white/10 rounded-3xl shadow-2xl w-full max-w-3xl overflow-hidden flex flex-col animate-in zoom-in-95 duration-300">
        
        <div className="h-16 border-b border-white/5 flex items-center justify-between px-6 bg-[#1a1b1e]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-indigo-500/20 flex items-center justify-center">
              <Activity size={18} className="text-indigo-400" />
            </div>
            <h2 className="text-lg font-semibold text-gray-200">Statistik Sistem & Memori</h2>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-white/10 rounded-xl transition-colors text-gray-400 hover:text-white">
            <X size={20} />
          </button>
        </div>

        <div className="p-6 md:p-8 bg-[#111113]">
          {loading || !stats ? (
            <div className="flex flex-col items-center justify-center py-20 gap-4">
              <Loader2 size={32} className="animate-spin text-indigo-500" />
              <span className="text-gray-400 text-sm font-medium">Mengambil metrik dari database...</span>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 auto-rows-fr">
              
              <div className="md:col-span-2 bg-gradient-to-br from-[#1e1f22] to-[#161719] p-6 rounded-3xl border border-white/5 shadow-[inset_0_1px_2px_rgba(255,255,255,0.02)] flex flex-col justify-between group hover:border-indigo-500/30 transition-colors">
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2.5 rounded-2xl bg-indigo-500/10 text-indigo-400 group-hover:scale-110 transition-transform">
                    <BrainCircuit size={24} />
                  </div>
                  <div>
                    <h3 className="text-gray-400 text-sm font-medium">Total Token LLM Terpakai</h3>
                    <p className="text-xs text-gray-500">Estimasi biaya API terhitung dari pemakaian token</p>
                  </div>
                </div>
                <div>
                  <span className="text-4xl md:text-5xl font-bold bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                    {stats.tokens.toLocaleString()}
                  </span>
                  <span className="text-gray-500 ml-2 font-medium">tokens</span>
                </div>
              </div>

              <div className="bg-[#1e1f22] p-6 rounded-3xl border border-white/5 shadow-[inset_0_1px_2px_rgba(255,255,255,0.02)] flex flex-col justify-between group hover:border-pink-500/30 transition-colors">
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2.5 rounded-2xl bg-pink-500/10 text-pink-400 group-hover:scale-110 transition-transform">
                    <MessageSquare size={20} />
                  </div>
                  <h3 className="text-gray-400 text-sm font-medium">Sesi Obrolan</h3>
                </div>
                <div>
                  <span className="text-3xl font-bold text-gray-100">{stats.sessions.toLocaleString()}</span>
                  <span className="text-gray-500 ml-2 text-xs">sesi aktif</span>
                </div>
              </div>

              <div className="bg-[#1e1f22] p-6 rounded-3xl border border-white/5 shadow-[inset_0_1px_2px_rgba(255,255,255,0.02)] flex flex-col justify-between group hover:border-emerald-500/30 transition-colors">
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2.5 rounded-2xl bg-emerald-500/10 text-emerald-400 group-hover:scale-110 transition-transform">
                    <Network size={20} />
                  </div>
                  <h3 className="text-gray-400 text-sm font-medium">Node Pengetahuan</h3>
                </div>
                <div>
                  <span className="text-3xl font-bold text-gray-100">{stats.graph_nodes.toLocaleString()}</span>
                  <span className="text-gray-500 ml-2 text-xs">fakta tersimpan</span>
                </div>
              </div>

              <div className="bg-[#1e1f22] p-6 rounded-3xl border border-white/5 shadow-[inset_0_1px_2px_rgba(255,255,255,0.02)] flex flex-col justify-between group hover:border-emerald-500/30 transition-colors">
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2.5 rounded-2xl bg-emerald-500/10 text-emerald-400 group-hover:scale-110 transition-transform">
                    <Network size={20} />
                  </div>
                  <h3 className="text-gray-400 text-sm font-medium">Relasi Pengetahuan</h3>
                </div>
                <div>
                  <span className="text-3xl font-bold text-gray-100">{stats.graph_edges.toLocaleString()}</span>
                  <span className="text-gray-500 ml-2 text-xs">hubungan antar fakta</span>
                </div>
              </div>

              <div className="bg-[#1e1f22] p-6 rounded-3xl border border-white/5 shadow-[inset_0_1px_2px_rgba(255,255,255,0.02)] flex flex-col justify-between group hover:border-blue-500/30 transition-colors">
                <div className="flex items-center gap-3 mb-4">
                  <div className="p-2.5 rounded-2xl bg-blue-500/10 text-blue-400 group-hover:scale-110 transition-transform">
                    <Database size={20} />
                  </div>
                  <h3 className="text-gray-400 text-sm font-medium">Vektor Memori</h3>
                </div>
                <div>
                  <span className="text-3xl font-bold text-gray-100">{stats.vector_memories.toLocaleString()}</span>
                  <span className="text-gray-500 ml-2 text-xs">vektor Qdrant</span>
                </div>
              </div>

              <div className="md:col-span-3 bg-gradient-to-r from-[#1e1f22] to-[#1a1b1e] p-6 rounded-3xl border border-white/5 shadow-[inset_0_1px_2px_rgba(255,255,255,0.02)] flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className="p-3 rounded-2xl bg-gray-500/10 text-gray-400">
                    <Box size={24} />
                  </div>
                  <div>
                    <h3 className="text-gray-300 font-medium">Total Pesan Tersimpan</h3>
                    <p className="text-xs text-gray-500">Jumlah seluruh interaksi di SQLite</p>
                  </div>
                </div>
                <div className="text-3xl font-bold text-white">
                  {stats.messages.toLocaleString()}
                </div>
              </div>

            </div>
          )}
        </div>
      </div>
    </div>
  );
}
