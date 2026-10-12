"use client";

import { useEffect, useRef, useState } from "react";
import { LoaderCircle, RefreshCw, Save } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { fetchModelCatalog, refreshModelCatalog, saveDefaultImageModel, type ModelCatalog } from "@/lib/api";

export function ModelCatalogCard() {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  const load = async (accountId = "") => {
    const id = ++requestId.current;
    setBusy(true);
    setError("");
    try {
      const result = await fetchModelCatalog(accountId);
      if (id !== requestId.current) return;
      setCatalog(result);
      setSelected(result.default_image_model);
    } catch (e) {
      if (id === requestId.current) setError(e instanceof Error ? e.message : "读取目录失败");
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  };

  useEffect(() => {
    void load();
    return () => { requestId.current += 1; };
  }, []);

  const refresh = async () => {
    if (!catalog?.account_id) return;
    const id = ++requestId.current;
    setBusy(true);
    setError("");
    try {
      const result = await refreshModelCatalog(catalog.account_id);
      if (id !== requestId.current) return;
      setCatalog(result);
      if (result.refreshed) {
        toast.success(`已发现 ${result.models.length} 个模型，生图能力需实际调用确认`);
        window.dispatchEvent(new Event("model-catalog-updated"));
      } else {
        setError(result.error || "刷新失败，保留最近成功目录");
      }
    } catch (e) {
      if (id === requestId.current) setError(e instanceof Error ? e.message : "刷新失败");
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await saveDefaultImageModel(selected);
      setCatalog((current) => current ? { ...current, ...result } : current);
      toast.success("默认生图模型已保存；API 省略 model 时使用此模型");
      window.dispatchEvent(new Event("model-catalog-updated"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const options = catalog?.image_models || ["gpt-image-2"];
  const selectedMissing = !!selected && !options.includes(selected);
  const selectClass = "h-10 w-full rounded-xl border border-stone-200 bg-white px-3 text-sm";
  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div>
          <h2 className="text-base font-semibold">账号模型发现</h2>
          <p className="mt-2 text-sm leading-6 text-stone-500">
            读取所选网页账号的上游模型目录，不执行生成、不测试额度。上游新增模型且调用协议不变时，刷新即可选择，无需更新项目。
          </p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <label className="flex-1 space-y-2 text-sm">
            <span>当前账号</span>
            <select aria-label="当前账号" className={selectClass} value={catalog?.account_id || ""}
              disabled={busy || !catalog?.accounts.length} onChange={(e) => void load(e.target.value)}>
              {!catalog?.accounts.length && <option value="">请先导入正常的网页账号</option>}
              {catalog?.accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
            </select>
          </label>
          <Button disabled={busy || !catalog?.account_id} onClick={() => void refresh()}>
            {busy ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            刷新当前账号模型
          </Button>
        </div>
        <p className="text-xs text-stone-500">
          最近成功刷新：{catalog?.updated_at ? new Date(catalog.updated_at).toLocaleString("zh-CN") : "尚未刷新"}
          {catalog ? ` · ${catalog.models.length} 个上游模型` : ""}
        </p>
        {error && <p role="alert" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">{error}</p>}
        <div className="space-y-3 rounded-xl border border-stone-200 p-4">
          <label className="block space-y-2 text-sm">
            <span>全局默认生图模型</span>
            <select aria-label="全局默认生图模型" className={selectClass} value={selected}
              disabled={busy || !catalog} onChange={(e) => setSelected(e.target.value)}>
              {selectedMissing && <option value={selected}>{selected}（不在当前账号目录）</option>}
              {options.map((model) => <option key={model} value={model}>{model}</option>)}
            </select>
          </label>
          <p className="text-xs leading-6 text-amber-800">
            web-image/ 前缀表示使用该上游模型请求生图，是候选入口，不代表已验证生图权限。
            普通聊天继续使用不带此前缀的模型 ID。目录刷新不保证新模型支持生图、指定原生尺寸或更快生成。
          </p>
          <Button onClick={() => void save()} disabled={busy || !catalog || selectedMissing || !selected}>
            <Save className="size-4" />保存默认模型
          </Button>
        </div>
        {catalog && catalog.models.length > 0 && (
          <div className="max-h-72 overflow-auto rounded-xl border border-stone-200">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-stone-100"><tr>
                <th className="p-3">上游 / 聊天模型 ID</th><th className="p-3">生图候选 ID（未验证）</th>
              </tr></thead>
              <tbody>{catalog.models.map((model) => <tr key={model.id} className="border-t border-stone-100">
                <td className="break-all p-3 font-mono">{model.id}</td>
                <td className="break-all p-3 font-mono">web-image/{model.id}</td>
              </tr>)}</tbody>
            </table>
          </div>
        )}
        {!catalog && !busy && <Button variant="outline" onClick={() => void load()}>重新读取目录</Button>}
      </CardContent>
    </Card>
  );
}
