import { useEffect, useState } from 'react';
import { X, Key, Box, Plus, Trash2, Save, Loader2, Settings, GripVertical, Edit2, Check, Eye, EyeOff } from 'lucide-react';

type ModelSettingsModalProps = {
  isOpen: boolean;
  onClose: () => void;
};

type ApiKeys = {
  google: string;
  groq: string;
  openai: string;
  hf: string;
};

type ApiKeyProvider = keyof ApiKeys;

const EMPTY_API_KEY_VISIBILITY: Record<ApiKeyProvider, boolean> = {
  google: false,
  groq: false,
  openai: false,
  hf: false,
};

const API_KEY_FIELDS: Array<{
  provider: ApiKeyProvider;
  label: string;
  placeholder: string;
}> = [
  { provider: 'google', label: 'Google Gemini API Key', placeholder: 'Biarin kosong kalau mau pakai dari .env' },
  { provider: 'groq', label: 'Groq API Key', placeholder: 'Biarin kosong kalau mau pakai dari .env' },
  { provider: 'openai', label: 'OpenAI API Key', placeholder: 'sk-...' },
  { provider: 'hf', label: 'HuggingFace API Key', placeholder: 'hf_...' },
];

function normalizeApiKeys(value: unknown): ApiKeys {
  const keys = value && typeof value === 'object'
    ? value as Partial<Record<keyof ApiKeys, unknown>>
    : {};

  return {
    google: typeof keys.google === 'string' ? keys.google : '',
    groq: typeof keys.groq === 'string' ? keys.groq : '',
    openai: typeof keys.openai === 'string' ? keys.openai : '',
    hf: typeof keys.hf === 'string' ? keys.hf : '',
  };
}

export type LLMModel = {
  id: string;
  name: string;
  provider: 'google' | 'groq' | 'openai' | 'huggingface';
};

const DEFAULT_MODELS: LLMModel[] = [
  { id: 'gemini-3.1-flash-lite', name: 'Gemini 3.1 Flash Lite', provider: 'google' },
  { id: 'llama3-70b-8192', name: 'Llama 3 70B', provider: 'groq' }
];

const MODEL_PROVIDERS: Array<{
  id: LLMModel['provider'];
  name: string;
  color: string;
}> = [
  { id: 'google', name: 'Google (Gemini)', color: 'bg-blue-500' },
  { id: 'groq', name: 'Groq', color: 'bg-orange-500' },
  { id: 'openai', name: 'OpenAI', color: 'bg-emerald-500' },
  { id: 'huggingface', name: 'HuggingFace (Serverless)', color: 'bg-yellow-400' },
];

const MODEL_PROVIDER_IDS: LLMModel['provider'][] = ['google', 'groq', 'openai', 'huggingface'];

export default function ModelSettingsModal({ isOpen, onClose }: ModelSettingsModalProps) {
  const [activeTab, setActiveTab] = useState<'models' | 'apikeys'>('models');
  
  const [apiKeys, setApiKeys] = useState<ApiKeys>({ google: '', groq: '', openai: '', hf: '' });
  const [models, setModels] = useState<LLMModel[]>([]);
  
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [isSaveSuccessOpen, setIsSaveSuccessOpen] = useState(false);
  const [visibleApiKeys, setVisibleApiKeys] = useState(EMPTY_API_KEY_VISIBILITY);

  const [newModelId, setNewModelId] = useState('');
  const [newModelName, setNewModelName] = useState('');
  const [newModelProvider, setNewModelProvider] = useState<'google' | 'groq' | 'openai' | 'huggingface'>('google');
  const [isProviderDropdownOpen, setIsProviderDropdownOpen] = useState(false);

  const [editingModelId, setEditingModelId] = useState<string | null>(null);
  const [editModelIdText, setEditModelIdText] = useState('');
  const [editModelName, setEditModelName] = useState('');
  const [editModelProvider, setEditModelProvider] = useState<'google' | 'groq' | 'openai' | 'huggingface'>('google');
  const [isEditProviderDropdownOpen, setIsEditProviderDropdownOpen] = useState(false);

  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);

  const fetchSettings = async () => {
    setLoading(true);
    try {
      const resKeys = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/settings/api_keys/reveal`, {
        cache: 'no-store',
      });
      if (!resKeys.ok) throw new Error(`Gagal memuat API keys (${resKeys.status})`);
      const dataKeys = await resKeys.json();
      setApiKeys(normalizeApiKeys(dataKeys.value));

      const resModels = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/settings/custom_models`);
      if (!resModels.ok) throw new Error(`Gagal memuat model (${resModels.status})`);
      const dataModels = await resModels.json();
      if (dataModels.value && dataModels.value.length > 0) {
        setModels(dataModels.value);
      } else {
        setModels(DEFAULT_MODELS);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!isOpen) return;

    const timer = window.setTimeout(() => {
      void fetchSettings();
    }, 0);

    return () => window.clearTimeout(timer);
  }, [isOpen]);

  const saveApiKeys = async () => {
    setSaving(true);
    setIsSaveSuccessOpen(false);
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: "api_keys", value: apiKeys })
      });
      if (!response.ok) throw new Error(`Gagal menyimpan API keys (${response.status})`);
      setIsSaveSuccessOpen(true);
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const handleClose = () => {
    setVisibleApiKeys(EMPTY_API_KEY_VISIBILITY);
    setIsSaveSuccessOpen(false);
    onClose();
  };

  const toggleApiKeyVisibility = (provider: ApiKeyProvider) => {
    setVisibleApiKeys(current => ({
      ...current,
      [provider]: !current[provider],
    }));
  };

  const saveModels = async (updatedModels: LLMModel[]) => {
    setSaving(true);
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100/api/v1"}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: "custom_models", value: updatedModels })
      });
      setModels(updatedModels);
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const handleAddModel = () => {
    if (!newModelId || !newModelName) return;
    const newModel: LLMModel = { id: newModelId, name: newModelName, provider: newModelProvider };
    const updated = [...models, newModel];
    saveModels(updated);
    setNewModelId('');
    setNewModelName('');
  };

  const handleDeleteModel = (id: string) => {
    const updated = models.filter(m => m.id !== id);
    saveModels(updated);
  };

  const startEdit = (model: LLMModel) => {
    setEditingModelId(model.id);
    setEditModelIdText(model.id);
    setEditModelName(model.name);
    setEditModelProvider(model.provider);
  };

  const saveEdit = () => {
    if (!editModelIdText || !editModelName) return;
    const updated = models.map(m => 
      m.id === editingModelId 
        ? { ...m, id: editModelIdText, name: editModelName, provider: editModelProvider } 
        : m
    );
    saveModels(updated);
    setEditingModelId(null);
  };

  const handleDragStart = (index: number) => {
    setDraggedIndex(index);
  };

  const handleDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault();
    if (draggedIndex === null || draggedIndex === index) return;
    
    const newModels = [...models];
    const draggedModel = newModels[draggedIndex];
    newModels.splice(draggedIndex, 1);
    newModels.splice(index, 0, draggedModel);
    
    setModels(newModels);
    setDraggedIndex(index);
  };

  const handleDragEnd = () => {
    setDraggedIndex(null);
    saveModels(models);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 bg-[#0d0e10]/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-[#161719] border border-white/10 rounded-3xl shadow-2xl w-full max-w-2xl overflow-hidden flex flex-col h-[600px] animate-in zoom-in-95 duration-300">
        
        <div className="h-16 border-b border-white/5 flex items-center justify-between px-6 bg-[#1a1b1e]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-xl bg-purple-500/20 flex items-center justify-center">
              <Settings size={18} className="text-purple-400" />
            </div>
            <h2 className="text-lg font-semibold text-gray-200">Pengaturan Model LLM</h2>
          </div>
          <button onClick={handleClose} className="p-2 hover:bg-white/10 rounded-xl transition-colors text-gray-400 hover:text-white cursor-pointer">
            <X size={20} />
          </button>
        </div>

        <div className="flex border-b border-white/5 bg-[#111113]">
          <button 
            onClick={() => setActiveTab('models')}
            className={`cursor-pointer flex-1 flex justify-center items-center gap-2 py-4 text-sm font-medium transition-colors ${activeTab === 'models' ? 'text-purple-400 border-b-2 border-purple-500' : 'text-gray-500 hover:text-gray-300'}`}
          >
            <Box size={16} /> Daftar Model
          </button>
          <button 
            onClick={() => setActiveTab('apikeys')}
            className={`cursor-pointer flex-1 flex justify-center items-center gap-2 py-4 text-sm font-medium transition-colors ${activeTab === 'apikeys' ? 'text-purple-400 border-b-2 border-purple-500' : 'text-gray-500 hover:text-gray-300'}`}
          >
            <Key size={16} /> API Keys
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6 bg-[#111113] custom-scrollbar">
          {loading ? (
            <div className="flex justify-center items-center h-full">
              <Loader2 size={32} className="animate-spin text-purple-500" />
            </div>
          ) : activeTab === 'apikeys' ? (
            <div className="space-y-6">
              {API_KEY_FIELDS.map(({ provider, label, placeholder }) => (
                <div key={provider} className="space-y-2">
                  <label htmlFor={`api-key-${provider}`} className="text-sm text-gray-400 font-medium">
                    {label}
                  </label>
                  <div className="relative">
                    <input
                      id={`api-key-${provider}`}
                      type={visibleApiKeys[provider] ? 'text' : 'password'}
                      value={apiKeys[provider]}
                      onChange={e => setApiKeys(current => ({ ...current, [provider]: e.target.value }))}
                      className="w-full bg-[#1a1b1e] border border-white/10 rounded-xl py-3 pl-3 pr-12 text-white focus:outline-none focus:border-purple-500"
                      placeholder={placeholder}
                      autoComplete="off"
                      spellCheck={false}
                    />
                    <button
                      type="button"
                      onClick={() => toggleApiKeyVisibility(provider)}
                      aria-label={visibleApiKeys[provider] ? `Sembunyikan ${label}` : `Tampilkan ${label}`}
                      aria-pressed={visibleApiKeys[provider]}
                      title={visibleApiKeys[provider] ? 'Sembunyikan API key' : 'Tampilkan API key'}
                      className="absolute inset-y-0 right-0 flex w-12 items-center justify-center text-gray-500 transition-colors hover:text-purple-400 focus:outline-none focus-visible:text-purple-400 cursor-pointer"
                    >
                      {visibleApiKeys[provider] ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </div>
              ))}
              <button 
                onClick={saveApiKeys}
                disabled={saving}
                className="w-full flex justify-center items-center gap-2 bg-purple-600 hover:bg-purple-700 text-white p-3 rounded-xl font-medium transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
              >
                {saving ? <Loader2 size={18} className="animate-spin" /> : <Save size={18} />}
                Simpan API Keys
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="bg-[#1a1b1e] p-5 rounded-2xl border border-white/5 space-y-4">
                <h3 className="text-white font-medium text-sm">Tambah Model Baru</h3>
                <div className="grid grid-cols-2 gap-3">
                  <input 
                    type="text"
                    value={newModelName}
                    onChange={e => setNewModelName(e.target.value)}
                    placeholder="Nama (e.g. Llama 3 HF)"
                    className="bg-[#111113] border border-white/10 rounded-xl p-2.5 text-sm text-white focus:outline-none focus:border-purple-500"
                  />
                  <input 
                    type="text"
                    value={newModelId}
                    onChange={e => setNewModelId(e.target.value)}
                    placeholder="Model ID (e.g. meta-llama/Llama-3-70b-chat-hf)"
                    className="bg-[#111113] border border-white/10 rounded-xl p-2.5 text-sm text-white focus:outline-none focus:border-purple-500"
                  />
                  <div className="col-span-2 relative">
                    <button 
                      onClick={() => setIsProviderDropdownOpen(!isProviderDropdownOpen)}
                      className="w-full bg-[#111113] border border-white/10 rounded-xl p-2.5 text-sm text-white focus:outline-none focus:border-purple-500 cursor-pointer flex justify-between items-center transition-colors hover:bg-white/5"
                    >
                      <span className="flex items-center gap-2">
                        <div className={`w-2 h-2 rounded-full ${newModelProvider === 'groq' ? 'bg-orange-500' : newModelProvider === 'google' ? 'bg-blue-500' : newModelProvider === 'huggingface' ? 'bg-yellow-400' : 'bg-emerald-500'}`}></div>
                        {newModelProvider === 'google' ? 'Google (Gemini)' : 
                         newModelProvider === 'groq' ? 'Groq' : 
                         newModelProvider === 'huggingface' ? 'HuggingFace (Serverless)' : 'OpenAI'}
                      </span>
                      <svg className={`w-4 h-4 text-gray-500 transition-transform duration-200 ${isProviderDropdownOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>

                    {isProviderDropdownOpen && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setIsProviderDropdownOpen(false)}></div>
                        <div className="absolute top-full left-0 w-full mt-1.5 bg-[#161719] border border-white/10 rounded-xl shadow-2xl py-1 z-20 animate-in fade-in zoom-in-95 duration-150">
                          {MODEL_PROVIDERS.map((prov) => (
                            <button
                              key={prov.id}
                              onClick={() => {
                                setNewModelProvider(prov.id);
                                setIsProviderDropdownOpen(false);
                              }}
                              className={`w-full text-left px-3 py-2 flex items-center gap-2 text-sm transition-colors cursor-pointer hover:bg-white/5
                                ${newModelProvider === prov.id ? 'text-purple-300 bg-purple-500/10' : 'text-gray-300'}`}
                            >
                              <div className={`w-2 h-2 rounded-full ${prov.color}`}></div>
                              {prov.name}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </div>
                <button 
                  onClick={handleAddModel}
                  disabled={saving || !newModelId || !newModelName}
                  className="w-full flex justify-center items-center gap-2 bg-white/10 hover:bg-white/20 text-white p-2.5 rounded-xl text-sm font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Plus size={16} /> Tambah
                </button>
              </div>

              <div className="space-y-3">
                <h3 className="text-gray-400 font-medium text-sm px-1">Daftar Tersimpan (Drag untuk urutkan)</h3>
                {models.map((model, index) => (
                  <div 
                    key={model.id} 
                    draggable={editingModelId === null}
                    onDragStart={() => handleDragStart(index)}
                    onDragOver={(e) => handleDragOver(e, index)}
                    onDragEnd={handleDragEnd}
                    className={`flex items-center justify-between bg-[#1a1b1e] p-3 rounded-2xl border border-white/5 group transition-all ${draggedIndex === index ? 'opacity-40 scale-95' : 'opacity-100'} ${editingModelId === model.id ? 'border-purple-500/50 shadow-[0_0_15px_rgba(168,85,247,0.1)]' : ''}`}
                  >
                    {editingModelId === model.id ? (
                      <div className="flex-1 space-y-2 pr-3">
                        <input 
                          type="text"
                          value={editModelName}
                          onChange={e => setEditModelName(e.target.value)}
                          placeholder="Nama Model"
                          className="w-full bg-[#111113] border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-purple-500 transition-colors"
                        />
                        <input 
                          type="text"
                          value={editModelIdText}
                          onChange={e => setEditModelIdText(e.target.value)}
                          placeholder="Model ID"
                          className="w-full bg-[#111113] border border-white/10 rounded-lg p-2 text-sm text-white focus:outline-none focus:border-purple-500 transition-colors"
                        />
                        <div className="relative">
                          <button 
                            onClick={() => setIsEditProviderDropdownOpen(!isEditProviderDropdownOpen)}
                            className="w-full bg-[#111113] border border-white/10 rounded-lg p-2 text-xs text-white focus:outline-none cursor-pointer flex justify-between items-center hover:bg-white/5 transition-colors"
                          >
                            <span className="flex items-center gap-2">
                              <div className={`w-1.5 h-1.5 rounded-full ${editModelProvider === 'groq' ? 'bg-orange-500' : editModelProvider === 'google' ? 'bg-blue-500' : editModelProvider === 'huggingface' ? 'bg-yellow-400' : 'bg-emerald-500'}`}></div>
                              {editModelProvider === 'google' ? 'Google' : editModelProvider === 'groq' ? 'Groq' : editModelProvider === 'huggingface' ? 'HuggingFace' : 'OpenAI'}
                            </span>
                          </button>
                          {isEditProviderDropdownOpen && (
                            <>
                              <div className="fixed inset-0 z-10" onClick={() => setIsEditProviderDropdownOpen(false)}></div>
                              <div className="absolute top-full left-0 w-full mt-1 bg-[#161719] border border-white/10 rounded-lg shadow-xl py-1 z-20">
                                {MODEL_PROVIDER_IDS.map((prov) => (
                                  <button
                                    key={prov}
                                    onClick={() => {
                                      setEditModelProvider(prov);
                                      setIsEditProviderDropdownOpen(false);
                                    }}
                                    className="w-full text-left px-3 py-1.5 text-xs text-gray-300 hover:bg-white/5 capitalize cursor-pointer transition-colors"
                                  >
                                    {prov === 'google' ? 'Google' : prov === 'groq' ? 'Groq' : prov === 'huggingface' ? 'HuggingFace' : 'OpenAI'}
                                  </button>
                                ))}
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div className="flex items-center gap-3 overflow-hidden pr-2">
                        <div className="cursor-grab active:cursor-grabbing p-1 text-gray-600 hover:text-gray-400 transition-colors">
                          <GripVertical size={16} />
                        </div>
                        <div className="min-w-0">
                          <h4 className="text-white text-sm font-medium flex items-center gap-2 truncate">
                             <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${model.provider === 'groq' ? 'bg-orange-500' : model.provider === 'google' ? 'bg-blue-500' : model.provider === 'huggingface' ? 'bg-yellow-400' : 'bg-emerald-500'}`}></div>
                             <span className="truncate">{model.name}</span>
                          </h4>
                          <p className="text-xs text-gray-500 mt-1 flex gap-2">
                            <span className="bg-white/5 px-2 py-0.5 rounded-md uppercase tracking-wider shrink-0">{model.provider}</span>
                            <span className="bg-white/5 px-2 py-0.5 rounded-md truncate">{model.id}</span>
                          </p>
                        </div>
                      </div>
                    )}

                    <div className="flex flex-col gap-1 shrink-0">
                      {editingModelId === model.id ? (
                        <>
                          <button 
                            onClick={saveEdit}
                            className="p-2 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 rounded-lg transition-all cursor-pointer"
                          >
                            <Check size={14} />
                          </button>
                          <button 
                            onClick={() => setEditingModelId(null)}
                            className="p-2 bg-red-500/10 text-red-400 hover:bg-red-500/20 rounded-lg transition-all cursor-pointer"
                          >
                            <X size={14} />
                          </button>
                        </>
                      ) : (
                        <>
                          <button 
                            onClick={() => startEdit(model)}
                            className="p-1.5 text-gray-500 hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition-all cursor-pointer opacity-50 group-hover:opacity-100"
                          >
                            <Edit2 size={16} />
                          </button>
                          <button 
                            onClick={() => handleDeleteModel(model.id)}
                            className="p-1.5 text-gray-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-all cursor-pointer opacity-50 group-hover:opacity-100"
                          >
                            <Trash2 size={16} />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {isSaveSuccessOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#0d0e10]/70 p-4 backdrop-blur-sm animate-in fade-in duration-200">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="api-key-save-success-title"
            className="w-full max-w-sm rounded-3xl border border-white/10 bg-[#191a1d] p-7 text-center shadow-2xl animate-in zoom-in-95 duration-200"
          >
            <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl border border-emerald-400/20 bg-emerald-400/10 text-emerald-400">
              <Check size={28} strokeWidth={2.5} />
            </div>
            <h3 id="api-key-save-success-title" className="text-lg font-semibold text-white">
              API Keys Berhasil Disimpan
            </h3>
            <p className="mt-2 text-sm leading-6 text-gray-400">
              Perubahan sudah tersimpan dan siap digunakan oleh model yang dipilih.
            </p>
            <button
              type="button"
              onClick={() => setIsSaveSuccessOpen(false)}
              className="mt-6 w-full rounded-xl bg-purple-600 px-4 py-3 text-sm font-medium text-white transition-colors hover:bg-purple-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-purple-400 cursor-pointer"
            >
              Oke
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
