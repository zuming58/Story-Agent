import { FormEvent, PointerEvent as ReactPointerEvent, useEffect, useMemo, useState } from "react";
import {
  ArrowCounterClockwise,
  ArrowsInLineHorizontal,
  BookBookmark,
  CaretDoubleLeft,
  CaretDoubleRight,
  Check,
  Checks,
  GitBranch,
  LinkSimple,
  PaperPlaneTilt,
  Paperclip,
  PushPin,
  ShieldCheck,
  Sparkle,
  X,
} from "@phosphor-icons/react";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import { useStoryStore } from "../store/useStoryStore";

function displayTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export function AgentPanel() {
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const { plan, selected, session, proposal, audits, sendMessage, applyProposal, rejectProposal, undo } = useStoryWorkspace();
  const collapsed = useStoryStore((state) => state.agentPanelCollapsed);
  const width = useStoryStore((state) => state.agentPanelWidth);
  const setCollapsed = useStoryStore((state) => state.setAgentPanelCollapsed);
  const setWidth = useStoryStore((state) => state.setAgentPanelWidth);
  const [selectedOperations, setSelectedOperations] = useState<Set<string>>(new Set());

  useEffect(() => {
    setSelectedOperations(new Set(proposal?.operations.filter((item) => item.selected).map((item) => item.id) ?? []));
  }, [proposal?.id, proposal?.status]);

  const reversible = useMemo(() => audits.find((item) => item.payload.reversible === true), [audits]);

  const handleResizeStart = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startWidth = width;
    const move = (pointerEvent: globalThis.PointerEvent) => setWidth(startWidth + startX - pointerEvent.clientX);
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  };

  const submit = async (event?: FormEvent, quickPrompt?: string) => {
    event?.preventDefault();
    const content = (quickPrompt ?? input).trim();
    if (!content || thinking || !selected) return;
    setInput("");
    setThinking(true);
    try { await sendMessage(content); } finally { setThinking(false); }
  };

  const toggleOperation = (id: string) => setSelectedOperations((current) => {
    const next = new Set(current);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  if (collapsed) {
    return (
      <aside className="agent-panel agent-panel-collapsed" aria-label="故事 Agent 已折叠">
        <button className="agent-expand" onClick={() => setCollapsed(false)} aria-label="展开故事 Agent">
          <Sparkle size={22} weight="duotone" /><CaretDoubleLeft size={18} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="agent-panel" aria-label="故事 Agent">
      <div className="agent-resizer" onPointerDown={handleResizeStart} aria-hidden="true" />
      <header className="agent-header">
        <div><Sparkle size={23} weight="duotone" /><strong>故事 Agent</strong></div>
        <div className="agent-header-actions"><button className="icon-button" aria-label="固定面板"><PushPin size={18} /></button><button className="icon-button" onClick={() => setCollapsed(true)} aria-label="折叠故事 Agent"><CaretDoubleRight size={19} /></button></div>
      </header>
      <div className="scope-row"><span>当前：</span><button>{plan?.volumeTitle ?? "当前作品"}</button><button>{plan?.arcTitle ?? "当前弧线"}</button>{selected && <button>{selected.title}</button>}</div>

      <div className="agent-scroll-region">
        <section className="message-list" aria-live="polite">
          {(session?.messages ?? []).slice(-6).map((message) => (
            <article className={`message message-${message.role}`} key={message.id}>
              <div className="message-avatar">{message.role === "user" ? <img src="/assets/nightwatch-avatar.png" alt="你" /> : <Sparkle size={18} weight="duotone" />}</div>
              <div><header><strong>{message.role === "user" ? "你" : "故事 Agent"}</strong><time>{displayTime(message.timestamp)}</time></header><p>{message.content}</p></div>
            </article>
          ))}
          {thinking && <article className="message message-assistant"><div className="message-avatar"><Sparkle size={18} /></div><div><header><strong>故事 Agent</strong></header><p className="thinking-copy">正在检查规划数据库与下游影响…</p></div></article>}
        </section>

        <section className="quick-actions" aria-label="AI 快捷操作">
          <button onClick={() => void submit(undefined, "请重排当前里程碑的节奏，并给出可审查的修改提案。") }><ArrowsInLineHorizontal size={16} />重排节奏</button>
          <button onClick={() => void submit(undefined, "请检查当前里程碑的逻辑与边界，不要直接修改。") }><ShieldCheck size={16} />检查逻辑</button>
          <button onClick={() => void submit(undefined, "请补全当前里程碑缺失的依赖，并列出影响。") }><GitBranch size={16} />补全依赖</button>
        </section>

        {proposal && (
          <section className={`proposal-card proposal-${proposal.status}`} aria-label="AI 修改提案">
            <header><div><Sparkle size={17} /><span>AI 建议修改</span></div><span className="proposal-tag">SQLite 已记录</span></header>
            <h3>{proposal.targetTitle}</h3><p className="proposal-reason">{proposal.reason}</p>
            <div className="operation-list">
              {proposal.operations.map((operation) => {
                const checked = selectedOperations.has(operation.id);
                return <button className={`operation-row${checked ? " is-selected" : ""}`} key={operation.id} onClick={() => proposal.status === "pending" && toggleOperation(operation.id)} disabled={proposal.status !== "pending"}>
                  <span className="operation-check">{checked && <Check size={13} weight="bold" />}</span><span>{operation.label}</span><del>{operation.before}章</del><span>→</span><ins>{operation.after}章</ins>
                </button>;
              })}
            </div>
            <div className="impact-title">影响评估</div><div className="impact-list">{proposal.impacts.map((impact) => <span key={impact.id}><LinkSimple size={13} />{impact.label}</span>)}</div>
            {proposal.status === "pending" ? <div className="proposal-actions">
              <button className="text-button" onClick={() => setSelectedOperations(new Set(proposal.operations.map((item) => item.id)))}><Checks size={16} />全选</button>
              <button className="accept-button" onClick={() => void applyProposal([...selectedOperations])} disabled={!selectedOperations.size}><Check size={17} />接受选中</button>
              <button className="reject-button" onClick={() => void rejectProposal()}><X size={17} />拒绝</button>
            </div> : <div className={`proposal-result ${proposal.status}`}>{proposal.status === "accepted" ? "修改已应用并写入审计" : "提案已拒绝，规划未改变"}</div>}
          </section>
        )}
      </div>

      <form className="agent-composer" onSubmit={(event) => void submit(event)}>
        <textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="描述你想调整的规划…" aria-label="给故事 Agent 发送消息" />
        <div className="composer-actions"><div><button type="button" className="icon-button" aria-label="添加附件"><Paperclip size={18} /></button><button type="button" className="icon-button" aria-label="引用契约"><BookBookmark size={18} /></button></div><button className="send-button" disabled={!input.trim() || thinking} type="submit"><PaperPlaneTilt size={18} weight="fill" />发送</button></div>
      </form>
      <div className="agent-footnote"><span>正式修改写入 SQLite 审计日志</span><button onClick={() => void undo()} disabled={!reversible}><ArrowCounterClockwise size={16} />撤销</button></div>
    </aside>
  );
}
