import type { IconProps } from "@phosphor-icons/react";
import type { ComponentType } from "react";
import { BookOpen, ChartBar, CloudArrowUp, FilmStrip, House, PenNib, ShieldCheck } from "@phosphor-icons/react";

const pageMap: Record<string, { title: string; description: string; icon: ComponentType<IconProps> }> = {
  overview: { title: "作品总览", description: "查看作品进度、今日任务与待处理风险。", icon: House },
  canon: { title: "Canon 设定库", description: "管理作者锁定的世界观、人物、规则与动态实体。", icon: BookOpen },
  writing: { title: "章节写作", description: "按章节契约生成、复核和修订候选正文。", icon: PenNib },
  quality: { title: "质量中心", description: "集中处理逻辑、节奏、角色与伏笔问题。", icon: ShieldCheck },
  state: { title: "故事状态", description: "追踪人物、物品、能力、事件和知识状态。", icon: ChartBar },
  automation: { title: "自动托管", description: "安排每日写作任务并查看可恢复的运行记录。", icon: CloudArrowUp },
  drama: { title: "短剧制作", description: "从小说创建可追踪的短剧改编项目。", icon: FilmStrip },
};

export function PlaceholderPage({ page }: { page: keyof typeof pageMap }) {
  const data = pageMap[page];
  const Icon = data.icon;
  return (
    <div className="placeholder-page">
      <div className="placeholder-kicker"><Icon size={22} weight="duotone" />模块已进入产品蓝图</div>
      <h1>{data.title}</h1><p>{data.description}</p>
      <div className="placeholder-rule" />
      <p className="placeholder-note">本轮先验证全局应用外壳和故事规划闭环；你仍然可以在右侧与故事 Agent 对话，并保留会话状态。</p>
    </div>
  );
}
