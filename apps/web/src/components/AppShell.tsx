import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import { useStoryStore } from "../store/useStoryStore";
import { AgentPanel } from "./AgentPanel";
import { Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { TopBar } from "./TopBar";

export function AppShell() {
  const collapsed = useStoryStore((state) => state.agentPanelCollapsed);
  const width = useStoryStore((state) => state.agentPanelWidth);
  const setCollapsed = useStoryStore((state) => state.setAgentPanelCollapsed);
  const notice = useStoryStore((state) => state.notice);
  const setNotice = useStoryStore((state) => state.setNotice);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1179px)");
    const update = () => {
      if (media.matches) setCollapsed(true);
    };
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [setCollapsed]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 2800);
    return () => window.clearTimeout(timer);
  }, [notice, setNotice]);

  return (
    <div
      className={`app-shell${collapsed ? " agent-is-collapsed" : ""}`}
      style={{ "--agent-panel-width": `${collapsed ? 48 : width}px` } as React.CSSProperties}
    >
      <Sidebar />
      <section className="workspace-shell">
        <TopBar />
        <main className="route-viewport"><Outlet /></main>
        <StatusBar />
      </section>
      <AgentPanel />
      {notice && <div className="toast-notice" role="status">{notice}</div>}
    </div>
  );
}
