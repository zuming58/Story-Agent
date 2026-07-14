import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle,
  Flask,
  Key,
  LinkSimple,
  Plus,
  ShieldWarning,
  SlidersHorizontal,
  Trash,
} from "@phosphor-icons/react";
import { api, ApiClientError } from "../api/client";
import type { ModelConfig, ModelProvider, ModelRole, ProviderConnectionTest } from "../types";

const roleLabels: Record<ModelRole, string> = {
  architect: "建筑师",
  planner: "规划师",
  chinese_writer: "中文写手",
  fact_extractor: "事实抽取",
  logic_reviewer: "逻辑审稿",
  continuity_reviewer: "连续性审稿",
  story_editor: "故事编辑",
  style_reviewer: "文风审稿",
  reviser: "修订器",
  embedding: "Embedding",
};

function statusText(status?: ProviderConnectionTest["status"]) {
  switch (status) {
    case "success": return "连接成功";
    case "missing_api_key": return "缺少密钥";
    case "auth_failed": return "鉴权失败";
    case "timeout": return "连接超时";
    case "credential_unavailable": return "Credential Manager 不可用";
    case "invalid_response": return "响应异常";
    case "network_error": return "网络错误";
    default: return "未测试";
  }
}

function errorMessage(error: unknown) {
  if (error instanceof ApiClientError) return error.payload.message;
  return error instanceof Error ? error.message : "操作失败。";
}

export function ModelSettingsPage() {
  const client = useQueryClient();
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(null);
  const [providerForm, setProviderForm] = useState({
    name: "自定义 OpenAI 兼容 Provider",
    baseUrl: "https://",
    timeoutSeconds: 30,
    maxRetries: 1,
    apiKey: "",
  });
  const [providerEdit, setProviderEdit] = useState({
    name: "",
    baseUrl: "",
    timeoutSeconds: 30,
    maxRetries: 1,
    apiKey: "",
  });
  const [modelForm, setModelForm] = useState({
    modelId: "",
    displayName: "",
    temperature: 0.7,
    maxOutputTokens: 2048,
    supportsReasoning: false,
    inputPricePerMillion: "",
    outputPricePerMillion: "",
  });
  const [testResult, setTestResult] = useState<ProviderConnectionTest | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const providersQuery = useQuery({ queryKey: ["model-providers"], queryFn: api.modelProviders, retry: 1 });
  const providers = providersQuery.data ?? [];
  const selectedProvider = providers.find((item) => item.id === selectedProviderId) ?? providers[0] ?? null;
  const modelsQuery = useQuery({
    queryKey: ["provider-models", selectedProvider?.id],
    queryFn: () => api.providerModels(selectedProvider!.id),
    enabled: Boolean(selectedProvider),
  });
  const bindingsQuery = useQuery({ queryKey: ["role-bindings"], queryFn: api.roleBindings, retry: 1 });
  const models = modelsQuery.data ?? [];
  const bindings = bindingsQuery.data ?? [];

  useEffect(() => {
    if (!selectedProviderId && providers.length) setSelectedProviderId(providers[0].id);
  }, [providers, selectedProviderId]);

  useEffect(() => {
    if (!selectedProvider) return;
    setProviderEdit({
      name: selectedProvider.name,
      baseUrl: selectedProvider.baseUrl,
      timeoutSeconds: selectedProvider.timeoutSeconds,
      maxRetries: selectedProvider.maxRetries,
      apiKey: "",
    });
  }, [selectedProvider?.id, selectedProvider?.updatedAt]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 3200);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const allModels = useMemo(() => {
    const byId = new Map<string, ModelConfig>();
    for (const model of models) byId.set(model.id, model);
    for (const binding of bindings) if (binding.model) byId.set(binding.model.id, binding.model);
    return [...byId.values()].sort((a, b) => a.displayName.localeCompare(b.displayName, "zh-CN"));
  }, [models, bindings]);

  const refreshSettings = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["model-providers"] }),
      client.invalidateQueries({ queryKey: ["provider-models"] }),
      client.invalidateQueries({ queryKey: ["role-bindings"] }),
    ]);
  };

  const deepseekMutation = useMutation({
    mutationFn: api.createDeepSeekPreset,
    onSuccess: async (provider) => {
      await refreshSettings();
      setSelectedProviderId(provider.id);
      setNotice("已创建 DeepSeek 官方预设。");
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const createProviderMutation = useMutation({
    mutationFn: api.createModelProvider,
    onSuccess: async (provider) => {
      setProviderForm((current) => ({ ...current, apiKey: "" }));
      await refreshSettings();
      setSelectedProviderId(provider.id);
      setNotice(provider.hasApiKey ? "Provider 已保存，密钥输入已清空。" : "Provider 已保存。");
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const updateProviderMutation = useMutation({
    mutationFn: ({ provider, edit }: { provider: ModelProvider; edit: typeof providerEdit }) => api.updateModelProvider(provider.id, {
      name: edit.name.trim(),
      baseUrl: edit.baseUrl.trim(),
      timeoutSeconds: Number(edit.timeoutSeconds),
      maxRetries: Number(edit.maxRetries),
      isEnabled: provider.isEnabled,
      ...(edit.apiKey.trim() ? { apiKey: edit.apiKey.trim() } : {}),
    }),
    onSuccess: async () => {
      setProviderEdit((current) => ({ ...current, apiKey: "" }));
      await refreshSettings();
      setNotice("Provider 已更新，密钥输入已清空。");
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const createModelMutation = useMutation({
    mutationFn: (provider: ModelProvider) => api.createProviderModel(provider.id, {
      modelId: modelForm.modelId.trim(),
      displayName: modelForm.displayName.trim() || modelForm.modelId.trim(),
      temperature: Number(modelForm.temperature),
      maxOutputTokens: Number(modelForm.maxOutputTokens),
      supportsReasoning: modelForm.supportsReasoning,
      isEnabled: true,
      inputPricePerMillion: modelForm.inputPricePerMillion === "" ? null : Number(modelForm.inputPricePerMillion),
      outputPricePerMillion: modelForm.outputPricePerMillion === "" ? null : Number(modelForm.outputPricePerMillion),
    }),
    onSuccess: async () => {
      setModelForm({ modelId: "", displayName: "", temperature: 0.7, maxOutputTokens: 2048, supportsReasoning: false, inputPricePerMillion: "", outputPricePerMillion: "" });
      await refreshSettings();
      setNotice("模型配置已保存。");
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const testMutation = useMutation({
    mutationFn: (provider: ModelProvider) => api.testModelProvider(provider.id),
    onSuccess: async (result) => {
      setTestResult(result);
      await client.invalidateQueries({ queryKey: ["model-providers"] });
      setNotice(result.message);
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const bindMutation = useMutation({
    mutationFn: ({ role, modelId }: { role: string; modelId: string | null }) => api.updateRoleBinding(role, { modelId }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["role-bindings"] });
      setNotice("角色绑定已保存。");
    },
    onError: (error) => setNotice(errorMessage(error)),
  });
  const deleteProviderMutation = useMutation({
    mutationFn: api.deleteModelProvider,
    onSuccess: async () => {
      setSelectedProviderId(null);
      await refreshSettings();
      setNotice("Provider 已删除，凭据引用已清理。");
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const submitProvider = (event: FormEvent) => {
    event.preventDefault();
    createProviderMutation.mutate({
      name: providerForm.name.trim(),
      baseUrl: providerForm.baseUrl.trim(),
      timeoutSeconds: Number(providerForm.timeoutSeconds),
      maxRetries: Number(providerForm.maxRetries),
      isEnabled: true,
      ...(providerForm.apiKey.trim() ? { apiKey: providerForm.apiKey.trim() } : {}),
    });
  };

  if (providersQuery.isLoading) {
    return <div className="settings-page"><div className="connection-state"><strong>正在加载模型设置…</strong><p>正在读取 Provider、模型和角色绑定。</p></div></div>;
  }

  return (
    <div className="settings-page">
      <header className="settings-heading">
        <div>
          <span className="placeholder-kicker"><SlidersHorizontal size={17} /> 模型与费用设置</span>
          <h1>模型与费用设置</h1>
          <p>管理 OpenAI 兼容 Provider、系统凭据、模型参数和角色路由。</p>
        </div>
        <button className="settings-primary" onClick={() => deepseekMutation.mutate()} disabled={deepseekMutation.isPending}>
          <Plus size={17} /> DeepSeek 预设
        </button>
      </header>

      <div className="settings-grid">
        <section className="settings-panel provider-panel" aria-label="模型供应商">
          <header><strong>Provider</strong><span>{providers.length ? `${providers.length} 个配置` : "空数据"}</span></header>
          <div className="provider-list">
            {providers.map((provider) => (
              <button key={provider.id} className={`provider-row${selectedProvider?.id === provider.id ? " is-selected" : ""}`} onClick={() => { setSelectedProviderId(provider.id); setTestResult(null); }}>
                <span><LinkSimple size={15} />{provider.name}</span>
                <small>{provider.baseUrl}</small>
                <em>{provider.hasApiKey ? `已配置 · ****${provider.apiKeyPreview ?? ""}` : "未配置密钥"}</em>
              </button>
            ))}
            {!providers.length && <div className="settings-empty">尚未配置 Provider。可创建 DeepSeek 预设或自定义中转地址。</div>}
          </div>
          <form className="settings-form" onSubmit={submitProvider}>
            <label><span>名称</span><input aria-label="新增 Provider 名称" value={providerForm.name} onChange={(event) => setProviderForm({ ...providerForm, name: event.target.value })} /></label>
            <label><span>Base URL</span><input aria-label="新增 Provider Base URL" value={providerForm.baseUrl} onChange={(event) => setProviderForm({ ...providerForm, baseUrl: event.target.value })} /></label>
            <div className="settings-form-row">
              <label><span>超时</span><input aria-label="新增 Provider 超时" type="number" min={1} max={300} value={providerForm.timeoutSeconds} onChange={(event) => setProviderForm({ ...providerForm, timeoutSeconds: Number(event.target.value) })} /></label>
              <label><span>重试</span><input aria-label="新增 Provider 重试" type="number" min={0} max={5} value={providerForm.maxRetries} onChange={(event) => setProviderForm({ ...providerForm, maxRetries: Number(event.target.value) })} /></label>
            </div>
            <label><span>API Key</span><input aria-label="新增 Provider API Key" type="password" value={providerForm.apiKey} onChange={(event) => setProviderForm({ ...providerForm, apiKey: event.target.value })} placeholder="保存后不会回显" /></label>
            <button className="settings-primary" disabled={createProviderMutation.isPending || !providerForm.name.trim() || !providerForm.baseUrl.trim()}><Plus size={16} />新增 Provider</button>
          </form>
        </section>

        <section className="settings-panel model-panel" aria-label="模型参数">
          <header><strong>模型参数</strong><span>{selectedProvider?.name ?? "未选择 Provider"}</span></header>
          {selectedProvider ? (
            <>
              <div className="provider-detail">
                <label><span>Provider 名称</span><input aria-label="当前 Provider 名称" value={providerEdit.name} onChange={(event) => setProviderEdit({ ...providerEdit, name: event.target.value })} /></label>
                <label><span>Base URL</span><input aria-label="当前 Provider Base URL" value={providerEdit.baseUrl} onChange={(event) => setProviderEdit({ ...providerEdit, baseUrl: event.target.value })} /></label>
                <div className="settings-form-row">
                  <label><span>超时</span><input aria-label="当前 Provider 超时" type="number" min={1} max={300} value={providerEdit.timeoutSeconds} onChange={(event) => setProviderEdit({ ...providerEdit, timeoutSeconds: Number(event.target.value) })} /></label>
                  <label><span>重试</span><input aria-label="当前 Provider 重试" type="number" min={0} max={5} value={providerEdit.maxRetries} onChange={(event) => setProviderEdit({ ...providerEdit, maxRetries: Number(event.target.value) })} /></label>
                </div>
                <label><span>替换密钥</span><input aria-label="当前 Provider API Key" type="password" value={providerEdit.apiKey} onChange={(event) => setProviderEdit({ ...providerEdit, apiKey: event.target.value })} placeholder={selectedProvider.hasApiKey ? `已配置 ****${selectedProvider.apiKeyPreview ?? ""}` : "未配置"} /></label>
                <div className="settings-actions">
                  <button onClick={() => updateProviderMutation.mutate({ provider: selectedProvider, edit: providerEdit })} disabled={updateProviderMutation.isPending}><Key size={16} />保存密钥/配置</button>
                  <button onClick={() => testMutation.mutate(selectedProvider)} disabled={testMutation.isPending}><Flask size={16} />测试连接</button>
                  <button className="danger" onClick={() => deleteProviderMutation.mutate(selectedProvider.id)} disabled={deleteProviderMutation.isPending}><Trash size={16} />删除</button>
                </div>
                <div className={`connection-result ${(testResult?.ok || selectedProvider.lastTestStatus === "success") ? "success" : (testResult || selectedProvider.lastTestStatus) ? "failed" : ""}`}>
                  {(testResult?.ok || selectedProvider.lastTestStatus === "success") ? <CheckCircle size={17} /> : <ShieldWarning size={17} />}
                  <span>{statusText(testResult?.status ?? selectedProvider.lastTestStatus ?? undefined)}{testResult?.model ? ` · ${testResult.model}` : ""}{selectedProvider.lastTestedAt ? ` · ${new Date(selectedProvider.lastTestedAt).toLocaleString("zh-CN")}` : ""}</span>
                </div>
              </div>

              <div className="model-list">
                {models.map((model) => (
                  <article key={model.id} className="model-row">
                    <div><strong>{model.displayName}</strong><span>{model.modelId}</span></div>
                    <small>温度 {model.temperature} · 输出 {model.maxOutputTokens} · {model.supportsReasoning ? "思考开启" : "思考关闭"} · 价格 {model.inputPricePerMillion ?? "—"}/{model.outputPricePerMillion ?? "—"} 每百万 Token（DeepSeek 预设为 USD）</small>
                  </article>
                ))}
                {!models.length && <div className="settings-empty">该 Provider 尚未配置模型。</div>}
              </div>
              <form className="settings-form compact" onSubmit={(event) => { event.preventDefault(); if (selectedProvider) createModelMutation.mutate(selectedProvider); }}>
                <div className="settings-form-row">
                  <label><span>模型 ID</span><input aria-label="模型 ID" value={modelForm.modelId} onChange={(event) => setModelForm({ ...modelForm, modelId: event.target.value })} placeholder="deepseek-v4-pro" /></label>
                  <label><span>显示名</span><input aria-label="模型显示名" value={modelForm.displayName} onChange={(event) => setModelForm({ ...modelForm, displayName: event.target.value })} /></label>
                </div>
                <div className="settings-form-row">
                  <label><span>输入价 / 百万 Token</span><input aria-label="模型输入价格" type="number" min={0} step={0.01} value={modelForm.inputPricePerMillion} onChange={(event) => setModelForm({ ...modelForm, inputPricePerMillion: event.target.value })} placeholder="可选" /></label>
                  <label><span>输出价 / 百万 Token</span><input aria-label="模型输出价格" type="number" min={0} step={0.01} value={modelForm.outputPricePerMillion} onChange={(event) => setModelForm({ ...modelForm, outputPricePerMillion: event.target.value })} placeholder="可选" /></label>
                </div>
                <div className="settings-form-row">
                  <label><span>温度</span><input aria-label="模型温度" type="number" min={0} max={2} step={0.1} value={modelForm.temperature} onChange={(event) => setModelForm({ ...modelForm, temperature: Number(event.target.value) })} /></label>
                  <label><span>最大输出</span><input aria-label="模型最大输出" type="number" min={1} value={modelForm.maxOutputTokens} onChange={(event) => setModelForm({ ...modelForm, maxOutputTokens: Number(event.target.value) })} /></label>
                </div>
                <label className="settings-check"><input type="checkbox" checked={modelForm.supportsReasoning} onChange={(event) => setModelForm({ ...modelForm, supportsReasoning: event.target.checked })} /><span>启用思考能力标记</span></label>
                <button className="settings-primary" disabled={!modelForm.modelId.trim() || createModelMutation.isPending}><Plus size={16} />新增模型</button>
              </form>
            </>
          ) : <div className="settings-empty">请选择或创建 Provider。</div>}
        </section>

        <section className="settings-panel role-panel" aria-label="角色绑定">
          <header><strong>角色绑定</strong><span>{bindings.filter((item) => item.modelId).length}/{bindings.length}</span></header>
          <div className="role-list">
            {bindings.map((binding) => (
              <label className="role-row" key={binding.role}>
                <span>{roleLabels[binding.role]}</span>
                <select value={binding.modelId ?? ""} onChange={(event) => bindMutation.mutate({ role: binding.role, modelId: event.target.value || null })}>
                  <option value="">未绑定</option>
                  {allModels.map((model) => <option value={model.id} key={model.id}>{model.providerName} / {model.displayName}</option>)}
                </select>
              </label>
            ))}
          </div>
          <div className="settings-diagnostic">
            <strong>错误诊断</strong>
            <p>连接测试只读取 Provider 模型列表，不保存回复正文，不创建 Agent 消息。</p>
            <p>HTTP Base URL 仅允许 localhost 或 127.0.0.1；远端服务必须使用 HTTPS。</p>
          </div>
        </section>
      </div>
      {notice && <div className="toast-notice" role="status">{notice}</div>}
    </div>
  );
}
