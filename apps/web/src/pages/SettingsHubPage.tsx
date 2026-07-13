import { useState } from "react";
import { Archive, SlidersHorizontal } from "@phosphor-icons/react";
import { ModelSettingsPage } from "./ModelSettingsPage";
import { SafetyAuditPage } from "./SafetyAuditPage";

export function SettingsHubPage() {
  const [tab, setTab] = useState<"models" | "safety">("models");
  return <div className="settings-hub">
    <nav className="settings-tabs" aria-label="系统设置分栏">
      <button className={tab === "models" ? "is-active" : ""} onClick={() => setTab("models")}><SlidersHorizontal />模型配置</button>
      <button className={tab === "safety" ? "is-active" : ""} onClick={() => setTab("safety")}><Archive />安全审计</button>
    </nav>
    <div className="settings-tab-body">{tab === "models" ? <ModelSettingsPage /> : <SafetyAuditPage />}</div>
  </div>;
}
