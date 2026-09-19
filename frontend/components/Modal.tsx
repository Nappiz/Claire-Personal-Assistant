"use client";

import React from "react";

type ModalProps = {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description: string;
  confirmText?: string;
  cancelText?: string;
  isDestructive?: boolean;
};

export default function Modal({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  confirmText = "Ya",
  cancelText = "Batal",
  isDestructive = false,
}: ModalProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="w-full max-w-sm bg-[#1e1f22] rounded-3xl p-6 shadow-[0_16px_40px_rgba(0,0,0,0.5),inset_0_2px_4px_rgba(255,255,255,0.05)] border border-white/5 transform transition-all scale-100 animate-in zoom-in-95 duration-200">
        <h3 className="text-lg font-semibold text-gray-100 mb-2">{title}</h3>
        <p className="text-sm text-gray-400 mb-6 leading-relaxed">
          {description}
        </p>
        <div className="flex items-center gap-3 justify-end">
          <button 
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-sm font-medium text-gray-300 hover:text-white hover:bg-white/5 transition-colors cursor-pointer"
          >
            {cancelText}
          </button>
          <button 
            onClick={onConfirm}
            className={`px-4 py-2 rounded-xl text-sm font-medium text-white shadow-[inset_0_1px_1px_rgba(255,255,255,0.2)] transition-all active:scale-95 cursor-pointer
              ${isDestructive 
                ? "bg-red-500/80 hover:bg-red-500" 
                : "bg-indigo-500/80 hover:bg-indigo-500"
              }`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
