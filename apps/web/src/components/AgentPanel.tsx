import { FormEvent, PointerEvent as ReactPointerEvent, useMemo, useState } from "react";
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
import { sendMockAgentMessage } from "../services/mockAgent";
import { useStoryStore } from "../store/useStoryStore";
import type { AgentMessage } from "../types";

export function AgentPanel() {
  const [input, setInput] = useState("");
  const plan = useStoryStore((state) => state.plan);
  const selectedId = useStoryStore((state) => state.selectedMilestoneId);
  const messages = useStoryStore((state) => state.agentMessages);
  const status = useStoryStore((state) => state.agentStatus);
  const collapsed = useStoryStore((state) => state.agentPanelCollapsed);
  const width = useStoryStore((state) => state.agentPanelWidth);
  const proposal = useStoryStore((state) => state.proposal);
  const history = useStoryStore((state) => state.history);
  const addMessage = useStoryStore((state) => state.addMessage);
  const setStatus = useStoryStore((state) => state.setAgentStatus);
  const setCollapsed = useStoryStore((state) => state.setAgentPanelCollapsed);
  const setWidth = useStoryStore((state) => state.setAgentPanelWidth);
  const setProposal = useStoryStore((state) => state.setProposal);
  const toggleOperation = useStoryStore((state) => state.toggleProposalOperation);
  const selectAll = useStoryStore((state) => state.selectAllProposalOperations);
  const applyProposal = useStoryStore((state) => state.applyProposal);
  const rejectProposal = useStoryStore((state) => state.rejectProposal);
  const undo = useStoryStore((state) => state.undo);
  const selected = useMemo(
    () => plan.milestones.find((milestone) => milestone.id === selectedId) ?? plan.milestones[0],
    [plan.milestones, selectedId],
  );

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
    if (!content || status === "thinking") return;
    const message: AgentMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
    };
    addMessage(message);
    setInput("");
    setStatus("thinking");
    try {
      const response = await sendMockAgentMessage(content, selected);
      addMessage(response.message);
      if (response.proposal) setProposal(response.proposal);
      setStatus("idle");
    } catch {
      setStatus("error");
    }
  };

  if (collapsed) {
    return (
      <aside className="agent-panel agent-panel-collapsed" aria-label="故事 Agent 已折叠">
        <button className="agent-expand" onClick={() => setCollapsed(false)} aria-label="展开故事 Agent">
          <Sparkle size={22} weight="duotone" />
          <CaretDoubleLeft size={18} />
        </button>
      </aside>
    );
  }

  return (
    <aside className="agent-panel" aria-label="故事 Agent">
      <div className="agent-resizer" onPointerDown={handleResizeStart} aria-hidden="true" />
      <header className="agent-header">
        <div><Sparkle size={23} weight="duotone" /><strong>故事 Agent</strong></div>
        <div className="agent-header-actions">
          <button className="icon-button" aria-label="固定面板"><PushPin size={18} /></button>
          <button className="icon-button" onClick={() => setCollapsed(true)} aria-label="折叠故事 Agent"><CaretDoubleRight size={19} /></button>
        </div>
      </header>

      <div className="scope-row">
        <span>当前：</span><button>第一卷</button><button>弧线 01</button><button>{selected.title}</button>
      </div>

      <div className="agent-scroll-region">
        <section className="message-list" aria-live="polite">
          {messages.slice(-5).map((message) => (
            <article className={`message message-${message.role}`} key={message.id}>
              <div className="message-avatar">
                {message.role === "user" ? <img src="/assets/nightwatch-avatar.png" alt="你" /> : <Sparkle size={18} weight="duotone" />}
              </div>
              <div><header><strong>{message.role === "user" ? "你" : "故事 Agent"}</strong><time>{message.timestamp}</time></header><p>{message.content}</p></div>
            </article>
          ))}
          {status === "thinking" && (
            <article className="message message-assistant"><div className="message-avatar"><Sparkle size={18} /></div><div><header><strong>故事 Agent</strong></header><p className="thinking-copy">正在检查规划约束与下游影响…</p></div></article>
          )}
        </section>

        <section className="quick-actions" aria-label="AI 快捷操作">
          <button onClick={() => void submit(undefined, "请重排当前里程碑的节奏，并给出可审查的修改提案。") }><ArrowsInLineHorizontal size={16} />重排节奏</button>
          <button onClick={() => void submit(undefined, "请检查当前里程碑的逻辑与边界，不要直接修改。") }><ShieldCheck size={16} />检查逻辑</button>
          <button onClick={() => void submit(undefined, "请补全当前里程碑缺失的依赖，并列出影响。") }><GitBranch size={16} />补全依赖</button>
        </section>

        {proposal && (
          <section className={`proposal-card proposal-${proposal.status}`} aria-label="AI 修改提案">
            <header><div><Sparkle size={17} /><span>AI 建议修改</span></div><span className="proposal-tag">节奏优化</span></header>
            <h3>{proposal.targetTitle}</h3>
            <p className="proposal-reason">{proposal.reason}</p>
            <div className="operation-list">
              {proposal.operations.map((operation) => (
                <button
                  className={`operation-row${operation.selected ? " is-selected" : ""}`}
                  key={operation.id}
                  onClick={() => proposal.status === "pending" && toggleOperation(operation.id)}
                  disabled={proposal.status !== "pending"}
                >
                  <span className="operation-check">{operation.selected && <Check size={13} weight="bold" />}</span>
                  <span>{operation.label}</span>
                  <del>{operation.before}章</del><span>→</span><ins>{operation.after}章</ins>
                </button>
              ))}
            </div>
            <div className="impact-title">影响评估</div>
            <div className="impact-list">
              {proposal.impacts.map((impact) => <span key={impact.id}><LinkSimple size={13} />{impact.label}</span>)}
            </div>
            {proposal.status === "pending" ? (
              <div className="proposal-actions">
                <button className="text-button" onClick={selectAll}><Checks size={16} />全选</button>
                <button className="accept-button" onClick={applyProposal}><Check size={17} />接受选中</button>
                <button className="reject-button" onClick={rejectProposal}><X size={17} />拒绝</button>
              </div>
            ) : (
              <div className={`proposal-result ${proposal.status}`}>
                {proposal.status === "accepted" ? "修改已应用，可随时撤销" : "提案已拒绝，规划未改变"}
                <button onClick={() => setProposal({ ...proposal, status: "pending" })}>继续调整</button>
              </div>
            )}
          </section>
        )}
      </div>

      <form className="agent-composer" onSubmit={(event) => void submit(event)}>
        <textarea value={input} onChange={(event) => setInput(event.target.value)} placeholder="描述你想调整的规划…" aria-label="给故事 Agent 发送消息" />
        <div className="composer-actions">
          <div><button type="button" className="icon-button" aria-label="添加附件"><Paperclip size={18} /></button><button type="button" className="icon-button" aria-label="引用契约"><BookBookmark size={18} /></button></div>
          <button className="send-button" disabled={!input.trim() || status === "thinking"} type="submit"><PaperPlaneTilt size={18} weight="fill" />发送</button>
        </div>
      </form>
      <div className="agent-footnote">
        <span>AI 操作均需人工确认后应用</span>
        <button onClick={undo} disabled={!history.length}><ArrowCounterClockwise size={16} />撤销</button>
      </div>
    </aside>
  );
}
