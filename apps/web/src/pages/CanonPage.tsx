import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpenText, Check, CheckCircle, CirclesThreePlus, GitDiff,
  LockKey, MagicWand, Plus, ShieldCheck, Sparkle, TreeStructure, WarningCircle, X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiClientError } from "../api/client";
import { TrialReadinessPanel } from "../components/TrialReadinessPanel";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import { useStoryStore } from "../store/useStoryStore";

type CanonTab = "core" | "entities" | "rules" | "relations" | "changes";

function jsonText(value: unknown) { return JSON.stringify(value ?? {}, null, 2); }
function lines(value: string) { return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean); }
function parseObject(value: string) {
  const parsed = JSON.parse(value || "{}");
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("属性必须是 JSON object。");
  return parsed as Record<string, unknown>;
}
function displayError(error: unknown) {
  if (error instanceof ApiClientError) return `${error.payload.code}：${error.payload.message}`;
  return error instanceof Error ? error.message : "操作失败。";
}

export function CanonPage() {
  const { project } = useStoryWorkspace();
  const client = useQueryClient();
  const setNotice = useStoryStore((state) => state.setNotice);
  const setAgentContext = useStoryStore((state) => state.setAgentContext);
  const [tab, setTab] = useState<CanonTab>("core");
  const [coreText, setCoreText] = useState("");
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedRuleId, setSelectedRuleId] = useState<string | null>(null);
  const [entityForm, setEntityForm] = useState({ name: "", entityTypeId: "", aliases: "", attributes: "{}", reason: "" });
  const [ruleForm, setRuleForm] = useState({ code: "", category: "general", statement: "", severity: "medium", constraint: "{}", reason: "" });
  const [selectedRelationId, setSelectedRelationId] = useState<string | null>(null);
  const [relationForm, setRelationForm] = useState({ subjectEntityId: "", predicate: "", objectEntityId: "", objectValue: "", reason: "" });
  const [lockOpen, setLockOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [brief, setBrief] = useState({
    title: project?.title?.replace(/·正式试写$/, "") ?? "夜巡人",
    genre: "现代中式规则怪谈、悬疑调查、克制成长",
    premise: "沈砚在雾城调查夜雾与夜巡司，同时追查自己被删除的童年记忆。",
    tone: "克制、悬疑、具体、可视化",
    forbidden: "十几章内完成整卷升级\n无代价连续使用能力\n提前揭示无脸纸童与童年真相",
  });

  const canonQuery = useQuery({ queryKey: ["canon", project?.id], queryFn: () => api.canon(project!.id), enabled: Boolean(project) });
  const architectureQuery = useQuery({ queryKey: ["canon-generation-proposals", project?.id], queryFn: () => api.canonGenerationProposals(project!.id), enabled: Boolean(project) });
  const canon = canonQuery.data;
  const architectureProposals = Array.isArray(architectureQuery.data) ? architectureQuery.data : [];
  const pendingArchitecture = architectureProposals.find((item) => item.status === "pending") ?? null;
  const root = canon?.documents.find((item) => item.id === "story-core") ?? canon?.documents[0];
  const selectedEntity = canon?.entities.find((item) => item.id === selectedEntityId) ?? null;
  const selectedRule = canon?.rules.find((item) => item.id === selectedRuleId) ?? null;
  const selectedRelation = canon?.relations.find((item) => item.id === selectedRelationId) ?? null;
  const entityNames = useMemo(() => new Map(canon?.entities.map((item) => [item.id, item.canonicalName]) ?? []), [canon?.entities]);
  const diagnostics = useMemo(() => {
    if (!canon) return [];
    const results: string[] = [];
    const unlinked = canon.entities.filter((entity) => !canon.relations.some((relation) => relation.subjectEntityId === entity.id || relation.objectEntityId === entity.id));
    const emptyAttributes = canon.entities.filter((entity) => Object.keys(entity.attributes).length === 0);
    const emptyConstraints = canon.rules.filter((rule) => Object.keys(rule.constraintJson).length === 0);
    if (!canon.entities.length) results.push("尚未识别人物、地点、物品或能力实体");
    if (unlinked.length) results.push(`${unlinked.length} 个实体尚未建立关系`);
    if (emptyAttributes.length) results.push(`${emptyAttributes.length} 个实体缺少结构化属性`);
    if (emptyConstraints.length) results.push(`${emptyConstraints.length} 条规则缺少机器可检约束`);
    return results;
  }, [canon]);
  const dirtyCore = Boolean(root && coreText !== root.contentMarkdown);

  useEffect(() => { if (root) setCoreText(root.contentMarkdown); }, [root?.id, root?.revision]);
  useEffect(() => {
    if (!selectedEntity) return;
    setEntityForm({ name: selectedEntity.canonicalName, entityTypeId: selectedEntity.entityTypeId, aliases: selectedEntity.aliases.join("\n"), attributes: jsonText(selectedEntity.attributes), reason: "" });
  }, [selectedEntity?.id, selectedEntity?.revision]);
  useEffect(() => {
    if (!selectedRule) return;
    setRuleForm({ code: selectedRule.ruleCode, category: selectedRule.category, statement: selectedRule.statement, severity: selectedRule.severity, constraint: jsonText(selectedRule.constraintJson), reason: "" });
  }, [selectedRule?.id, selectedRule?.revision]);
  useEffect(() => {
    if (!selectedRelation) return;
    setRelationForm({
      subjectEntityId: selectedRelation.subjectEntityId,
      predicate: selectedRelation.predicate,
      objectEntityId: selectedRelation.objectEntityId ?? "",
      objectValue: selectedRelation.objectValue == null ? "" : String(selectedRelation.objectValue),
      reason: "",
    });
  }, [selectedRelation?.id, selectedRelation?.revision]);
  useEffect(() => {
    const labels = ["Canon 设定库", tab === "core" ? "故事核心" : tab === "entities" ? selectedEntity?.canonicalName ?? "实体" : tab === "rules" ? selectedRule?.ruleCode ?? "规则" : tab === "relations" ? "关系" : "变更申请"];
    setAgentContext(labels);
    return () => setAgentContext([]);
  }, [tab, selectedEntity?.canonicalName, selectedRule?.ruleCode, setAgentContext]);

  const refresh = async () => {
    if (!project) return;
    await Promise.all([
      client.invalidateQueries({ queryKey: ["canon", project.id] }),
      client.invalidateQueries({ queryKey: ["canon-generation-proposals", project.id] }),
      client.invalidateQueries({ queryKey: ["trial-readiness", project.id] }),
      client.invalidateQueries({ queryKey: ["audits", project.id] }),
    ]);
  };
  const mutation = useMutation({ mutationFn: async (action: () => Promise<unknown>) => action(), onSuccess: async () => { setError(null); await refresh(); }, onError: (cause) => setError(displayError(cause)) });
  const run = (label: string, action: () => Promise<unknown>) => mutation.mutateAsync(action).then(() => setNotice(label));

  const generateArchitecture = async () => {
    if (!project || project.projectKind === "demo") return;
    await run("故事架构提案已生成，请检查完整性后应用。", async () => {
      await api.createCanonGenerationProposal(project.id, {
        title: brief.title,
        mode: "long-form",
        targetChapters: 1000,
        genre: brief.genre,
        premise: brief.premise,
        tone: brief.tone,
        worldPreferences: ["现代雾城", "局部夜雾", "怪异必须依靠规则与代价处理"],
        progressionPreset: "restrained-explicit",
        romance: "弱感情线，不喧宾夺主",
        forbiddenContent: lines(brief.forbidden),
        referenceTraits: ["信息差恐怖", "规则可验证", "能力存在明确代价"],
      });
      await architectureQuery.refetch();
    });
  };

  const decideArchitecture = async (apply: boolean) => {
    if (!pendingArchitecture) return;
    await run(apply ? "Canon 架构提案已应用到正式草稿。" : "Canon 架构提案已拒绝。", async () => {
      if (apply) await api.applyCanonGenerationProposal(pendingArchitecture.id, pendingArchitecture.revision);
      else await api.rejectCanonGenerationProposal(pendingArchitecture.id, pendingArchitecture.revision);
      await architectureQuery.refetch();
    });
  };

  const saveCore = async () => {
    if (!project || !root) return;
    if (canon?.locked) {
      await run("Canon 核心变更申请已创建，等待确认。", () => api.createCanonChangeRequest(project.id, {
        targetKind: "document", targetId: root.id, reason: "人工修订故事核心", impactSummary: "可能影响后续契约、检索与连续性检查", afterJson: { contentMarkdown: coreText },
      }));
      setTab("changes");
    } else {
      await run("故事核心草稿已保存。", () => api.updateCanonDraft(project.id, { documents: [{ id: root.id, title: root.title, kind: root.kind, contentMarkdown: coreText }] }));
    }
  };

  const analyze = async () => {
    if (!project || !root || canon?.locked) return;
    if (dirtyCore) await api.updateCanonDraft(project.id, { documents: [{ id: root.id, title: root.title, kind: root.kind, contentMarkdown: coreText }] });
    await run("AI 已把故事核心拆解为实体、关系和规则草稿。", () => api.analyzeCanon(project.id, coreText, root.title));
  };

  const saveEntity = async () => {
    if (!project) return;
    let attributes: Record<string, unknown>;
    try { attributes = parseObject(entityForm.attributes); } catch (cause) { setError(displayError(cause)); return; }
    if (canon?.locked && selectedEntity) {
      await run("实体变更申请已创建。", () => api.createCanonChangeRequest(project.id, {
        targetKind: "entity", targetId: selectedEntity.id, reason: entityForm.reason || "修订实体设定", impactSummary: "将触发 Canon 与上下文索引更新", afterJson: { aliasesJson: lines(entityForm.aliases), attributesJson: attributes },
      }));
      setTab("changes");
      return;
    }
    await run(selectedEntity ? "实体设定已更新。" : "实体已加入 Canon 草稿。", () => api.updateCanonDraft(project.id, { entities: [{ entityTypeId: entityForm.entityTypeId, canonicalName: entityForm.name, aliasesJson: lines(entityForm.aliases), attributesJson: attributes, sourceDocumentId: root?.id }] }));
  };

  const saveRule = async () => {
    if (!project) return;
    let constraint: Record<string, unknown>;
    try { constraint = parseObject(ruleForm.constraint); } catch (cause) { setError(displayError(cause)); return; }
    if (canon?.locked && selectedRule) {
      await run("规则变更申请已创建。", () => api.createCanonChangeRequest(project.id, {
        targetKind: "rule", targetId: selectedRule.id, reason: ruleForm.reason || "修订世界规则", impactSummary: "可能影响章节硬规则与质量门", afterJson: { statement: ruleForm.statement, severity: ruleForm.severity, constraintJson: constraint },
      }));
      setTab("changes");
      return;
    }
    await run(selectedRule ? "规则已更新。" : "规则已加入 Canon 草稿。", () => api.updateCanonDraft(project.id, { rules: [{ ruleCode: ruleForm.code, category: ruleForm.category, statement: ruleForm.statement, severity: ruleForm.severity, constraintJson: constraint, sourceDocumentId: root?.id }] }));
  };

  const saveRelation = async () => {
    if (!project) return;
    const objectValue = relationForm.objectEntityId ? undefined : relationForm.objectValue;
    if (canon?.locked && selectedRelation) {
      await run("关系变更申请已创建。", () => api.createCanonChangeRequest(project.id, {
        targetKind: "relation", targetId: selectedRelation.id, reason: relationForm.reason || "修订实体关系",
        impactSummary: "可能改变人物、物品或组织间的连续性约束",
        afterJson: { predicate: relationForm.predicate, objectValueJson: objectValue },
      }));
      setTab("changes");
      return;
    }
    if (canon?.locked) return;
    await run(selectedRelation ? "关系草稿已更新。" : "关系已加入 Canon 草稿。", () => api.updateCanonDraft(project.id, { relations: [{ id: selectedRelation?.id, subjectEntityId: relationForm.subjectEntityId, predicate: relationForm.predicate, objectEntityId: relationForm.objectEntityId || undefined, objectValueJson: objectValue, sourceDocumentId: root?.id }] }));
    setSelectedRelationId(null);
    setRelationForm({ subjectEntityId: "", predicate: "", objectEntityId: "", objectValue: "", reason: "" });
  };

  if (!project) return <div className="connection-state"><strong>请先选择作品</strong></div>;
  if (canonQuery.isLoading || !canon || !root) return <div className="canon-page"><div className="connection-state"><strong>正在读取 Canon 设定库…</strong></div></div>;

  return <div className="canon-page">
    <header className="canon-heading">
      <div><span className="workbench-kicker"><TreeStructure /> CANON VAULT</span><h1>Canon 设定库</h1><p>把作者设定转成可锁定、可检查、可变更追踪的故事权威。</p></div>
      <div className="canon-heading-actions"><span className={canon.locked ? "canon-locked" : "canon-draft"}>{canon.locked ? <LockKey /> : <Sparkle />}{canon.locked ? "正式 Canon 已锁定" : "草稿可编辑"}</span>{!canon.locked && <button className="gold-action" onClick={() => setLockOpen(true)}><LockKey />锁定 Canon</button>}</div>
    </header>

    {!canon.locked && <section className="story-architect-panel">
      <header><div><MagicWand /><strong>故事架构器</strong><span>从一句创意生成完整 Canon 候选，不会直接锁定正式设定</span></div><em>ARCHITECT</em></header>
      {project.projectKind === "demo" ? <div className="architect-demo-warning"><WarningCircle />当前是示例项目，禁止真实付费生成。请切换到“夜巡人·正式试写”。</div> : <>
        <div className="story-brief-grid">
          <label><span>作品名</span><input value={brief.title} onChange={(event) => setBrief({ ...brief, title: event.target.value })} /></label>
          <label><span>类型方向</span><input value={brief.genre} onChange={(event) => setBrief({ ...brief, genre: event.target.value })} /></label>
          <label className="wide"><span>一句话故事内核</span><textarea value={brief.premise} onChange={(event) => setBrief({ ...brief, premise: event.target.value })} /></label>
          <label><span>叙事基调</span><input value={brief.tone} onChange={(event) => setBrief({ ...brief, tone: event.target.value })} /></label>
          <label><span>禁止事项（每行一条）</span><textarea value={brief.forbidden} onChange={(event) => setBrief({ ...brief, forbidden: event.target.value })} /></label>
        </div>
        {!pendingArchitecture && <footer><p>固定采用 1000 章七卷、夜巡六阶、四级法器和克制升级预算。</p><button className="gold-action" disabled={mutation.isPending || brief.premise.length < 20} onClick={() => void generateArchitecture()}><Sparkle />{mutation.isPending ? "正在生成并自动检查…" : "生成完整故事架构"}</button></footer>}
        {pendingArchitecture && <div className="architecture-proposal-card">
          <div className="architecture-proposal-summary"><div><strong>Canon 候选提案</strong><span>REV {pendingArchitecture.revision}</span></div><b className={pendingArchitecture.readiness.ready ? "is-ready" : "is-blocked"}>{pendingArchitecture.readiness.ready ? "完整性通过" : "存在阻断项"}</b></div>
          <div className="architecture-check-grid">{pendingArchitecture.readiness.checks.map((check) => <span key={check.code} className={check.status === "ready" ? "is-ready" : "is-blocked"}>{check.status === "ready" ? <CheckCircle /> : <WarningCircle />}{check.detail}</span>)}</div>
          <details><summary>预览完整 Canon Markdown</summary><pre>{pendingArchitecture.contentMarkdown}</pre></details>
          <footer><button disabled={mutation.isPending} onClick={() => void decideArchitecture(false)}><X />拒绝</button><button className="gold-action" disabled={!pendingArchitecture.readiness.ready || mutation.isPending} onClick={() => void decideArchitecture(true)}><Check />应用到 Canon 草稿</button></footer>
        </div>}
      </>}
    </section>}

    <nav className="canon-tabs">{([
      ["core", "故事核心", BookOpenText], ["entities", `实体 ${canon.entities.length}`, CirclesThreePlus], ["rules", `规则 ${canon.rules.length}`, ShieldCheck], ["relations", `关系 ${canon.relations.length}`, TreeStructure], ["changes", `变更 ${canon.changeRequests.filter((item) => item.status === "pending").length}`, GitDiff],
    ] as const).map(([value, label, Icon]) => <button key={value} className={tab === value ? "is-active" : ""} onClick={() => setTab(value)}><Icon />{label}</button>)}</nav>

    <div className="canon-layout">
      <main className="canon-main">
        {tab === "core" && <section className="canon-core-panel">
          <header><div><BookOpenText /><strong>{root.title}</strong></div><span>REV {root.revision}</span></header>
          <textarea aria-label="故事核心 Markdown" value={coreText} onChange={(event) => setCoreText(event.target.value)} className="canon-editor" spellCheck={false} />
          <footer><span className={dirtyCore ? "dirty" : "saved"}>{dirtyCore ? "有未保存修改" : "已与 SQLite 同步"}</span><div><button onClick={() => void saveCore()} disabled={!dirtyCore || mutation.isPending}><Check />{canon.locked ? "提交变更申请" : "保存草稿"}</button>{!canon.locked && <button className="gold-action" onClick={() => void analyze()} disabled={!coreText.trim() || mutation.isPending}><MagicWand />AI 分析并结构化</button>}</div></footer>
        </section>}

        {tab === "entities" && <section className="canon-structured-grid">
          <aside className="canon-object-list"><header><strong>实体目录</strong>{!canon.locked && <button onClick={() => { setSelectedEntityId(null); setEntityForm({ name: "", entityTypeId: canon.entityTypes[0]?.id ?? "", aliases: "", attributes: "{}", reason: "" }); }}><Plus />新增</button>}</header>{canon.entities.map((entity) => <button key={entity.id} className={selectedEntityId === entity.id ? "is-selected" : ""} onClick={() => setSelectedEntityId(entity.id)}><span>{entity.canonicalName}</span><small>{canon.entityTypes.find((type) => type.id === entity.entityTypeId)?.displayName ?? "未分类"}</small></button>)}</aside>
          <div className="canon-object-editor"><header><div><CirclesThreePlus /><strong>{selectedEntity ? selectedEntity.canonicalName : "新增实体"}</strong></div>{selectedEntity && <span>REV {selectedEntity.revision}</span>}</header>
            <div className="canon-form"><label><span>规范名称</span><input value={entityForm.name} disabled={Boolean(selectedEntity)} onChange={(event) => setEntityForm({ ...entityForm, name: event.target.value })} /></label><label><span>实体类型</span><select value={entityForm.entityTypeId} disabled={Boolean(selectedEntity)} onChange={(event) => setEntityForm({ ...entityForm, entityTypeId: event.target.value })}>{canon.entityTypes.map((type) => <option key={type.id} value={type.id}>{type.displayName}</option>)}</select></label><label><span>别名（每行一个）</span><textarea value={entityForm.aliases} onChange={(event) => setEntityForm({ ...entityForm, aliases: event.target.value })} /></label><label><span>结构化属性 JSON</span><textarea className="json-editor" value={entityForm.attributes} onChange={(event) => setEntityForm({ ...entityForm, attributes: event.target.value })} /></label>{canon.locked && <label><span>变更原因</span><input value={entityForm.reason} onChange={(event) => setEntityForm({ ...entityForm, reason: event.target.value })} placeholder="锁定后必须说明修改原因" /></label>}<button className="gold-action" disabled={!entityForm.name || !entityForm.entityTypeId || (canon.locked && !selectedEntity) || mutation.isPending} onClick={() => void saveEntity()}>{canon.locked ? "提交实体变更" : selectedEntity ? "保存实体" : "加入草稿"}</button></div>
          </div>
        </section>}

        {tab === "rules" && <section className="canon-structured-grid">
          <aside className="canon-object-list"><header><strong>规则目录</strong>{!canon.locked && <button onClick={() => { setSelectedRuleId(null); setRuleForm({ code: "", category: "general", statement: "", severity: "medium", constraint: "{}", reason: "" }); }}><Plus />新增</button>}</header>{canon.rules.map((rule) => <button key={rule.id} className={selectedRuleId === rule.id ? "is-selected" : ""} onClick={() => setSelectedRuleId(rule.id)}><span>{rule.ruleCode}</span><small>{rule.category} · {rule.severity}</small></button>)}</aside>
          <div className="canon-object-editor"><header><div><ShieldCheck /><strong>{selectedRule ? selectedRule.ruleCode : "新增规则"}</strong></div>{selectedRule && <span>REV {selectedRule.revision}</span>}</header><div className="canon-form"><label><span>规则编码</span><input value={ruleForm.code} disabled={Boolean(selectedRule)} onChange={(event) => setRuleForm({ ...ruleForm, code: event.target.value })} /></label><div className="canon-form-row"><label><span>分类</span><input value={ruleForm.category} disabled={canon.locked} onChange={(event) => setRuleForm({ ...ruleForm, category: event.target.value })} /></label><label><span>严重度</span><select value={ruleForm.severity} onChange={(event) => setRuleForm({ ...ruleForm, severity: event.target.value })}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="blocker">blocker</option></select></label></div><label><span>规则说明</span><textarea value={ruleForm.statement} onChange={(event) => setRuleForm({ ...ruleForm, statement: event.target.value })} /></label><label><span>约束 JSON</span><textarea className="json-editor" value={ruleForm.constraint} onChange={(event) => setRuleForm({ ...ruleForm, constraint: event.target.value })} /></label>{canon.locked && <label><span>变更原因</span><input value={ruleForm.reason} onChange={(event) => setRuleForm({ ...ruleForm, reason: event.target.value })} /></label>}<button className="gold-action" disabled={!ruleForm.code || !ruleForm.statement || (canon.locked && !selectedRule) || mutation.isPending} onClick={() => void saveRule()}>{canon.locked ? "提交规则变更" : selectedRule ? "保存规则" : "加入草稿"}</button></div></div>
        </section>}

        {tab === "relations" && <section className="canon-relations-panel"><header><div><TreeStructure /><strong>实体关系网</strong></div><span>{canon.relations.length} 条</span></header>{(!canon.locked || selectedRelation) && <div className="relation-builder"><select aria-label="关系主语" value={relationForm.subjectEntityId} disabled={Boolean(selectedRelation)} onChange={(event) => setRelationForm({ ...relationForm, subjectEntityId: event.target.value })}><option value="">选择主语实体</option>{canon.entities.map((entity) => <option key={entity.id} value={entity.id}>{entity.canonicalName}</option>)}</select><input aria-label="关系谓词" value={relationForm.predicate} onChange={(event) => setRelationForm({ ...relationForm, predicate: event.target.value })} placeholder="关系，例如：隶属于" /><select aria-label="关系宾语实体" value={relationForm.objectEntityId} disabled={Boolean(selectedRelation)} onChange={(event) => setRelationForm({ ...relationForm, objectEntityId: event.target.value })}><option value="">使用文本宾语</option>{canon.entities.map((entity) => <option key={entity.id} value={entity.id}>{entity.canonicalName}</option>)}</select>{!relationForm.objectEntityId && <input aria-label="关系文本宾语" value={relationForm.objectValue} onChange={(event) => setRelationForm({ ...relationForm, objectValue: event.target.value })} placeholder="文本宾语" />}{canon.locked && <input aria-label="关系变更原因" value={relationForm.reason} onChange={(event) => setRelationForm({ ...relationForm, reason: event.target.value })} placeholder="说明变更原因" />}<button className="gold-action" disabled={!relationForm.subjectEntityId || !relationForm.predicate || (!relationForm.objectEntityId && !relationForm.objectValue)} onClick={() => void saveRelation()}>{canon.locked ? <GitDiff /> : selectedRelation ? <Check /> : <Plus />}{canon.locked ? "提交关系变更" : selectedRelation ? "保存关系" : "添加关系"}</button></div>}<div className="relation-list">{canon.relations.map((relation) => <article key={relation.id} className={selectedRelationId === relation.id ? "is-selected" : ""} onClick={() => setSelectedRelationId(relation.id)}><span>{entityNames.get(relation.subjectEntityId) ?? "未知实体"}</span><i>{relation.predicate}</i><strong>{relation.objectEntityId ? entityNames.get(relation.objectEntityId) : String(relation.objectValue ?? "—")}</strong></article>)}{!canon.relations.length && <div className="canon-empty">AI 分析或人工添加后，人物、物品、组织和能力体系之间的关系会显示在这里。</div>}</div></section>}

        {tab === "changes" && <section className="canon-changes-panel"><header><div><GitDiff /><strong>锁定后变更申请</strong></div><span>未经确认不会修改正式 Canon</span></header><div className="change-request-list">{canon.changeRequests.map((request) => <article key={request.id} className={`change-request request-${request.status}`}><header><div><strong>{request.reason}</strong><span>{request.targetKind} · {request.targetId}</span></div><em>{request.status}</em></header><p>{request.impactSummary || "未填写影响说明"}</p><details><summary><GitDiff />查看字段差异</summary><div className="change-diff"><pre>{jsonText(request.beforeJson)}</pre><pre>{jsonText(request.afterJson)}</pre></div></details>{request.status === "pending" && <footer><button onClick={() => void run("变更申请已拒绝。", () => api.rejectCanonChangeRequest(project.id, request.id, request.revision))}><X />拒绝</button><button className="gold-action" onClick={() => void run("Canon 变更已应用并重建检索索引。", () => api.applyCanonChangeRequest(project.id, request.id, request.revision))}><Check />接受并应用</button></footer>}</article>)}{!canon.changeRequests.length && <div className="canon-empty">Canon 锁定后的修改会先进入这里，正式设定不会被静默覆盖。</div>}</div></section>}
      </main>
      <aside className="canon-side"><TrialReadinessPanel compact /><section className="canon-stat-card"><header><Sparkle /><strong>结构化覆盖</strong></header><dl><div><dt>实体类型</dt><dd>{canon.entityTypes.length}</dd></div><div><dt>实体</dt><dd>{canon.entities.length}</dd></div><div><dt>关系</dt><dd>{canon.relations.length}</dd></div><div><dt>硬规则</dt><dd>{canon.rules.length}</dd></div></dl></section><section className="canon-diagnostics"><header><WarningCircle /><strong>AI 分析诊断</strong></header>{diagnostics.length ? diagnostics.map((item) => <p key={item}><WarningCircle />{item}</p>) : <p className="is-clear"><CheckCircle />结构化字段与关系未发现明显缺口</p>}</section></aside>
    </div>
    {error && <div className="toast-notice error" role="alert"><WarningCircle />{error}<button onClick={() => setError(null)}><X /></button></div>}

    <Dialog.Root open={lockOpen} onOpenChange={setLockOpen}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="canon-lock-dialog"><Dialog.Title><LockKey />锁定正式 Canon</Dialog.Title><Dialog.Description>锁定后，人物、规则、关系和故事核心将成为章节生成的权威边界。后续修改必须通过带差异的变更申请。</Dialog.Description><div className="lock-summary"><span><CheckCircle />{canon.entities.length} 个实体</span><span><CheckCircle />{canon.rules.length} 条规则</span><span><CheckCircle />{canon.relations.length} 条关系</span></div><footer><Dialog.Close asChild><button>继续检查</button></Dialog.Close><button className="gold-action" onClick={() => { setLockOpen(false); void run("Canon 已锁定，章节契约现在可以生成。", () => api.lockCanon(project.id, root.revision)); }}><LockKey />确认锁定</button></footer></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
