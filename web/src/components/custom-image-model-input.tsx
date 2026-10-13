"use client";

import { useState } from "react";
import { LoaderCircle, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function CustomImageModelInput({ onAdd, disabled = false }: {
  onAdd: (model: string) => Promise<void>;
  disabled?: boolean;
}) {
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const add = async () => {
    if (!model.trim() || busy || disabled) return;
    setBusy(true);
    setError("");
    try {
      await onAdd(model.trim());
      setModel("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "添加模型失败");
    } finally {
      setBusy(false);
    }
  };
  return <div className="space-y-2">
    <label className="block space-y-2 text-sm">
      <span>自定义上游模型 ID</span>
      <div className="flex gap-2">
        <Input aria-label="自定义上游模型 ID" value={model} disabled={busy || disabled} maxLength={138}
          placeholder="例如 future-image-model"
          onChange={(e) => { setModel(e.target.value); setError(""); }}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); void add(); } }} />
        <Button type="button" disabled={busy || disabled || !model.trim()} onClick={() => void add()}>
          {busy ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}添加并选择
        </Button>
      </div>
    </label>
    <p className="text-xs leading-5 text-stone-500">输入准确 ID，而非显示名称。保存后跨重启保留；不会自动生图验证或切换全局默认。调用时原样传给上游，失败不回退到其他模型。</p>
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
  </div>;
}
