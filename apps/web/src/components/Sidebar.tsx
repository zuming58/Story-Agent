import {
  Bell,
  BookOpen,
  ChartBar,
  CloudArrowUp,
  FilmStrip,
  House,
  PenNib,
  Question,
  SlidersHorizontal,
  ShareNetwork,
  ShieldCheck,
} from "@phosphor-icons/react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Link, useLocation } from "react-router-dom";

const navigation = [
  { to: "/overview", label: "作品总览", icon: House },
  { to: "/canon", label: "Canon", icon: BookOpen },
  { to: "/planning", label: "故事规划", icon: ShareNetwork },
  { to: "/writing", label: "章节写作", icon: PenNib },
  { to: "/quality", label: "质量中心", icon: ShieldCheck },
  { to: "/state", label: "故事状态", icon: ChartBar },
  { to: "/automation", label: "自动托管", icon: CloudArrowUp },
  { to: "/settings", label: "模型设置", icon: SlidersHorizontal },
  { to: "/drama", label: "短剧制作", icon: FilmStrip },
];

export function Sidebar() {
  const location = useLocation();
  return (
    <aside className="sidebar" aria-label="主导航">
      <div className="brand-mark">
        <img src="/assets/nightwatch-compass.png" alt="夜巡人罗盘标识" />
      </div>
      <nav className="nav-list">
        {navigation.map((item) => {
          const Icon = item.icon;
          return (
            <Tooltip.Root key={item.to}>
              <Tooltip.Trigger asChild>
                <Link
                  className={`nav-item${location.pathname === item.to ? " is-active" : ""}`}
                  to={item.to}
                >
                  <Icon size={26} weight="duotone" aria-hidden="true" />
                  <span>{item.label}</span>
                </Link>
              </Tooltip.Trigger>
              <Tooltip.Portal>
                <Tooltip.Content className="tooltip-content" side="right" sideOffset={8}>
                  {item.label}
                </Tooltip.Content>
              </Tooltip.Portal>
            </Tooltip.Root>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <button className="icon-button" aria-label="帮助中心"><Question size={22} /></button>
        <button className="icon-button has-dot" aria-label="通知"><Bell size={22} /></button>
        <img className="user-avatar" src="/assets/nightwatch-avatar.png" alt="当前用户头像" />
      </div>
    </aside>
  );
}
