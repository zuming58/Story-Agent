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

  useEffect(() => {
    const media = window.matchMedia("(max-width: 1179px)");
    const update = () => {
      if (media.matches) setCollapsed(true);
    };
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [setCollapsed]);

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
    </div>
  );
}
