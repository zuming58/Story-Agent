import { Archive, SlidersHorizontal } from "@phosphor-icons/react";
import { useSearchParams } from "react-router-dom";
import { ModelSettingsPage } from "./ModelSettingsPage";
import { SafetyAuditPage } from "./SafetyAuditPage";

export function SettingsHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") === "safety" ? "safety" : "models";
  const selectTab = (next: "models" | "safety") => setSearchParams(next === "models" ? {} : { tab: next }, { replace: true });
  return <div className="settings-hub">
    <nav className="settings-tabs" aria-label="系统设置分栏">
      <button className={tab === "models" ? "is-active" : ""} onClick={() => selectTab("models")}><SlidersHorizontal />模型配置</button>
      <button className={tab === "safety" ? "is-active" : ""} onClick={() => selectTab("safety")}><Archive />安全审计</button>
    </nav>
    <div className="settings-tab-body">{tab === "models" ? <ModelSettingsPage /> : <SafetyAuditPage />}</div>
  </div>;
}
