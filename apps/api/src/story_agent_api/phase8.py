from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select

from .model_provider import ModelProviderError, OpenAICompatibleModelProvider
from .models import (
    CanonDocument,
    CanonGenerationProposal,
    ModelRun,
    Plan,
    PlanGenerationProposal,
    PlanNode,
    StoryBudget,
)
from .schemas import (
    ArchitectureProposalDecision,
    CanonDraftUpdate,
    PlanGenerationRequest,
    StoryBrief,
)
from .services import StoryError, dumps, loads


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        raw = raw.rsplit("```", 1)[0].strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model response is not a JSON object")
    value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response is not a JSON object")
    return value


VOLUMES = [
    (1, 1, 100, "雾城旧宅"),
    (2, 101, 220, "夜巡司裂痕"),
    (3, 221, 360, "失名之市"),
    (4, 361, 500, "河灯无岸"),
    (5, 501, 650, "七城夜路"),
    (6, 651, 820, "无昼之年"),
    (7, 821, 1000, "最后一盏灯"),
]

FIRST_BEATS = [
    {
        "chapterNumber": 1,
        "title": "午夜多出的档案袋",
        "objective": "建立沈砚、雾城旧档案馆和异常来信；沈砚只确认档案袋不应存在。",
        "completionConditions": ["沈砚发现一份没有入库记录的旧档案袋", "档案袋中的来信指向槐安巷十七号"],
        "hooks": ["来信收件人写着沈砚全名，但邮戳早于他来到雾城的时间"],
        "foreshadows": ["FOG-OLD-HOUSE-LETTER"],
        "requiredCharacters": ["沈砚", "老周"],
        "forbidden": ["不得进入旧宅", "不得获得巡夜灯", "不得解释夜巡司", "不得确认童年真相"],
    },
    {
        "chapterNumber": 2,
        "title": "不存在的门牌",
        "objective": "沈砚通过公开档案和城市旧图验证槐安巷十七号被人为删除。",
        "completionConditions": ["公开系统与纸质底册出现可验证矛盾", "沈砚决定夜间实地确认街巷位置"],
        "hooks": ["旧图背面出现一行刚刚变湿的手写门牌号"],
        "foreshadows": ["ARCHIVE-DELETED-ADDRESS"],
        "requiredCharacters": ["沈砚", "白芷"],
        "forbidden": ["不得进入旧宅内部", "不得知道无脸纸童身份", "不得升级为识祟"],
    },
    {
        "chapterNumber": 3,
        "title": "灯照旧路",
        "objective": "沈砚首次进入夜雾，巡夜灯只显示一条已经存在的旧路。",
        "completionConditions": ["沈砚确认夜雾会改变街道路径", "巡夜灯第一次被动显路并产生轻微记忆代价"],
        "hooks": ["灯光尽头站着一个没有五官的纸童"],
        "foreshadows": ["PATROL-LAMP-MEMORY-COST"],
        "requiredCharacters": ["沈砚", "老周"],
        "forbidden": ["巡夜灯不得消灭怪异", "不得无代价连续使用", "不得进入识祟阶段"],
    },
    {
        "chapterNumber": 4,
        "title": "纸人不看人",
        "objective": "沈砚通过观察确认纸童只在没有被活人直接目视时移动。",
        "completionConditions": ["纸童移动规则获得至少两次可验证证据", "沈砚利用规则脱离当前危险"],
        "hooks": ["纸童没有追来，却把一张写着沈砚童年小名的纸片留在路口"],
        "foreshadows": ["FACELESS-PAPER-CHILD"],
        "requiredCharacters": ["沈砚", "无脸纸童"],
        "forbidden": ["不得确认纸童善恶", "不得确认纸童身份", "不得正面消灭纸童"],
    },
    {
        "chapterNumber": 5,
        "title": "被遗忘的一句话",
        "objective": "沈砚发现自己遗忘了一句与母亲有关的话，确认巡夜灯会吞噬温暖记忆。",
        "completionConditions": ["记忆代价通过具体生活细节体现", "沈砚在知道风险后仍决定继续调查"],
        "hooks": ["档案馆地下库房传来原本不该存在的第四声铜铃"],
        "foreshadows": ["SHEN-YAN-CHILDHOOD-GAP", "FOURTH-BELL"],
        "requiredCharacters": ["沈砚", "白芷", "老周"],
        "forbidden": ["不得恢复完整童年记忆", "不得公开夜巡司组织架构", "不得完成第一卷主谜"],
    },
]


AUTHORITATIVE_CANON_BOUNDARIES = """## 长篇硬边界台账（系统权威）

> 本节由系统依据用户确认的长篇预算生成，优先级高于 AI 描述性文本。任何章节契约、候选正文和后续提案都不得改变这些窗口。

### 七卷边界

1. 第1—100章《雾城旧宅》
2. 第101—220章《夜巡司裂痕》
3. 第221—360章《失名之市》
4. 第361—500章《河灯无岸》
5. 第501—650章《七城夜路》
6. 第651—820章《无昼之年》
7. 第821—1000章《最后一盏灯》

### 第一卷能力预算

- 第1—10章：沈砚从普通人进入“见雾”，只能察觉异常，不能主动干预。
- 第11—40章：学习并验证规则，最早第20章、目标第30—40章进入“识祟”。
- 第41—89章：稳定识祟能力、积累证据并训练，不得提前进入执灯。
- 第90—100章：仅在证据、训练、明确代价三项条件全部满足后进入“执灯”。
- 第一卷不得进入“立契”；十几章内不得完成整卷升级或主要真相。

### 法器状态与获得窗口

| 法器 | 分类 | 获得/使用窗口 | 初始持有人 | 规则与代价 | 初始状态 |
|---|---|---|---|---|---|
| 巡夜灯 | 巡器 | 第3—5章获得临时使用权；第3章只能被动显示既存路径 | 老周保管、沈砚临时使用 | 不消灭怪异；每次点亮吞噬一段温暖记忆；主动固定路径须达到执灯 | 完好；初始可记录使用3次 |
| 镇纸钉 | 巡器 | 最早第8章，目标第8—15章获得 | 夜巡司保管，满足纸人规则证据后移交 | 只能短暂固定已识别规则；使用后规则反弹；24小时内不可重复 | 完好；初始1枚1次 |
| 潮湿账页 | 巡器 | 最早第18章，目标第20—30章获得 | 旧宅外围封存物，取得后由沈砚保管 | 只记录已遭遇异常与不完整线索；不能直接给出答案；阅读会混淆一段近期记忆 | 潮湿但未损坏；页数与可读次数逐章记录 |

遗物是单一规则、风险较低的异常遗留物；巡器是经夜巡司处理且必须记录次数和代价的工具；封物能力较强但持续携带诅咒；祟核是异常源头，绝不能作为普通装备使用。

### 分层揭示窗口

- 无脸纸童：第4章只允许观察其移动规则和存在痕迹；第43—60章揭示身份第一层；第370章前不得确认完整身份、声音、动机及其与沈砚童年的完整关系。
- 沈砚童年：第5章只呈现一句话被遗忘的记忆代价；第92—100章揭示童年真相第一层；第580章前不得完整复述核心事件；完整真相只能在后续卷逐层回收。
- 夜巡司：第一卷只允许接触外围人员、程序与相互矛盾的记录；第400章前不得给出组织阴谋全貌。
- 雾源：第一卷只允许验证局部夜雾规则；最终卷前不得解释真正源头。

### 第一批章节契约

1. 第1章《午夜多出的档案袋》：建立沈砚、档案馆和异常来信，不进入旧宅、不获得巡夜灯。
2. 第2章《不存在的门牌》：验证槐安巷十七号被正式档案删除，不进入旧宅内部。
3. 第3章《灯照旧路》：首次进入夜雾，巡夜灯只显示既存路径并产生轻微记忆代价。
4. 第4章《纸人不看人》：只验证无脸纸童的移动规则，不揭示身份。
5. 第5章《被遗忘的一句话》：确认巡夜灯的记忆代价，沈砚在知情后决定继续调查。

### 文风与单章约束

- 现代中式规则怪谈、悬疑调查、克制成长；规则必须能由行动和证据验证。
- 每章只消耗当前 ChapterBeat 与当前剧情预算，不得直接完成后续故事弧。
- 每章结尾保留具体钩子；不得用无代价升级、旁白直接揭谜或纯战力消灭怪异解决冲突。
"""


def _remove_model_timing_claims(markdown: str) -> str:
    """Remove model-authored chapter schedules before adding the ledger.

    Creative sections may describe the world and systems, but chapter numbers
    belong exclusively to the deterministic budget ledger.  Removing whole
    Markdown lines keeps a plausible model phrase from becoming a second source
    of truth that contradicts the planning database.
    """

    timing = re.compile(r"(?:第\s*)?\d+\s*(?:[—–~-]|至)\s*\d+\s*章|第\s*\d+\s*章")
    return "\n".join(line for line in markdown.splitlines() if not timing.search(line)).strip()


class Phase8Service:
    def __init__(self, service: Any):
        self.service = service

    def recover_interrupted_generations(self) -> None:
        """Keep completed blueprint sections and make an interrupted request resumable."""

        for project in self.service.list_projects():
            with self.service.db.project_write(project.id, project.folder_path) as session:
                rows = session.scalars(
                    select(CanonGenerationProposal).where(CanonGenerationProposal.status == "generating")
                ).all()
                for row in rows:
                    row.status = "failed"
                    row.revision += 1
                    row.readiness_json = dumps({"ready": False, "checks": [{
                        "code": "CANON_GENERATION_INTERRUPTED",
                        "status": "blocked",
                        "detail": "服务中断；已完成分段保留，下一次生成请求将从检查点继续。",
                    }]})
                    row.updated_at = _now()

    # ------------------------------------------------------------------
    # Model and proposal helpers
    # ------------------------------------------------------------------
    def _complete_role(
        self,
        project: Any,
        role: str,
        messages: list[dict[str, str]],
        request_id: str,
        *,
        response_json: bool = False,
        run_role: str | None = None,
        max_output_tokens: int | None = None,
        max_retries: int | None = None,
        stream_response: bool = False,
    ) -> tuple[str, str]:
        resolved = self.service._resolve_role_model(role)
        if not resolved:
            raise StoryError(409, "MODEL_ROLE_NOT_CONFIGURED", f"{role} 角色尚未绑定模型。")
        provider_row = resolved["provider"]
        model = resolved["model"]
        if not provider_row.api_key_ref:
            raise StoryError(409, "MODEL_API_KEY_MISSING", f"{role} 角色没有可用密钥。")
        try:
            api_key = self.service.secret_store.get_secret(provider_row.api_key_ref)
        except Exception as exc:
            raise StoryError(503, "CREDENTIAL_STORE_UNAVAILABLE", "无法读取系统凭据。") from exc
        if not api_key:
            raise StoryError(409, "MODEL_API_KEY_MISSING", f"{role} 角色没有可用密钥。")
        run_id = str(uuid4())
        started = time.perf_counter()
        with self.service.db.project_write(project.id, project.folder_path) as session:
            session.add(ModelRun(
                id=run_id,
                session_id=None,
                role=run_role or role,
                provider_id=provider_row.id,
                provider_name=provider_row.name,
                model_config_id=model.id,
                model_id=model.model_id,
                status="running",
                request_id=request_id,
                retry_count=0,
                started_at=_now(),
            ))
        client = OpenAICompatibleModelProvider(
            provider_row.base_url,
            api_key,
            provider_row.timeout_seconds,
            provider_row.max_retries if max_retries is None else max(0, min(max_retries, 1)),
        )
        payload: dict[str, Any] = {
            "model": model.model_id,
            "messages": messages,
            "temperature": min(float(model.temperature), 0.35),
            "max_tokens": min(model.max_output_tokens, max_output_tokens or 8192, 8192),
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}
        try:
            result = asyncio.run(client.complete_chat_streaming(payload) if stream_response else client.complete_chat(payload))
        except ModelProviderError as exc:
            partial = client.last_result
            with self.service.db.project_write(project.id, project.folder_path) as session:
                row = session.get(ModelRun, run_id)
                if row:
                    row.status = "failed"
                    row.error_code = exc.code
                    row.diagnostic_json = dumps({"message": exc.message, "partialLength": len(partial.text or "")})
                    row.prompt_tokens = partial.prompt_tokens
                    row.completion_tokens = partial.completion_tokens
                    row.total_tokens = partial.total_tokens
                    row.duration_ms = int((time.perf_counter() - started) * 1000)
                    row.retry_count = partial.retry_count
                    row.ended_at = _now()
            raise StoryError(502, f"MODEL_{exc.code.upper()}", exc.message) from exc
        estimated = 0.0
        if model.input_price_per_million is not None and model.output_price_per_million is not None:
            estimated = (
                (result.prompt_tokens or 0) * model.input_price_per_million
                + (result.completion_tokens or 0) * model.output_price_per_million
            ) / 1_000_000
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(ModelRun, run_id)
            if row:
                row.status = "succeeded"
                row.prompt_tokens = result.prompt_tokens
                row.completion_tokens = result.completion_tokens
                row.total_tokens = result.total_tokens
                row.estimated_cost = estimated
                row.duration_ms = int((time.perf_counter() - started) * 1000)
                row.retry_count = result.retry_count
                row.ended_at = _now()
        return result.text, run_id

    def _canon_revision(self, project: Any) -> int:
        with self.service.db.project(project.id, project.folder_path) as session:
            doc = session.get(CanonDocument, "story-core")
            return doc.revision if doc else 1

    def _canon_checks(self, markdown: str, structured: dict[str, Any]) -> dict[str, Any]:
        requirements = [
            ("CORE", ("故事内核", "一句话")),
            ("WORLD", ("世界", "时代", "地域")),
            ("CHARACTERS", ("人物", "主角")),
            ("ORGANIZATIONS", ("组织", "夜巡司")),
            ("PROGRESSION", ("见雾", "识祟", "执灯", "立契", "巡界", "守夜")),
            ("UPGRADE_COST", ("升级条件", "代价")),
            ("ARTIFACTS", ("遗物", "巡器", "封物", "祟核", "巡夜灯", "镇纸钉", "潮湿账页")),
            # “硬”是规则的约束属性，不应依赖模型逐字写出“硬规则”。
            # 结构化规则数量和 constraintJson 会在下方继续执行确定性校验。
            ("RULES", ("怪异", "规则")),
            ("KNOWLEDGE", ("知识边界", "关系")),
            ("LONG_PLAN", ("七卷边界", "第821—1000章", "最后一盏灯")),
            ("REVEAL_LOCKS", ("分层揭示窗口", "第43—60章", "第92—100章", "第370章前")),
            ("FIRST_BEATS", ("午夜多出的档案袋", "不存在的门牌", "灯照旧路", "纸人不看人", "被遗忘的一句话")),
            ("STYLE", ("文风", "每章只消耗当前 ChapterBeat")),
        ]
        checks: list[dict[str, Any]] = []
        for code, terms in requirements:
            ok = all(term in markdown for term in terms)
            checks.append({"code": f"CANON_{code}", "status": "ready" if ok else "blocked", "detail": "已覆盖" if ok else f"缺少：{'/'.join(terms)}"})

        fixed_boundaries = [
            ("CANON_LAMP_WINDOW", "第3—5章获得临时使用权"),
            ("CANON_NAIL_WINDOW", "目标第8—15章获得"),
            ("CANON_LEDGER_WINDOW", "目标第20—30章获得"),
            ("CANON_PAPER_CHILD_LAYER", "第43—60章揭示身份第一层"),
            ("CANON_CHILDHOOD_LAYER", "第92—100章揭示童年真相第一层"),
            ("CANON_FIRST_VOLUME_LIMIT", "第一卷不得进入“立契”"),
        ]
        checks.extend({
            "code": code,
            "status": "ready" if marker in markdown else "blocked",
            "detail": "权威台账已固定" if marker in markdown else f"缺少权威边界：{marker}",
        } for code, marker in fixed_boundaries)
        entities = structured.get("entities", [])
        rules = structured.get("rules", [])
        relations = structured.get("relations", [])
        structural = [
            ("CANON_STRUCTURED_ENTITIES", len(entities) >= 8, f"结构化实体 {len(entities)} 个"),
            ("CANON_STRUCTURED_RULES", len(rules) >= 8, f"结构化规则 {len(rules)} 条"),
            ("CANON_STRUCTURED_RELATIONS", len(relations) >= 4, f"结构化关系 {len(relations)} 条"),
        ]
        checks.extend({"code": code, "status": "ready" if ok else "blocked", "detail": detail} for code, ok, detail in structural)
        return {"ready": all(item["status"] == "ready" for item in checks), "checks": checks}

    @staticmethod
    def _baseline_structure() -> dict[str, Any]:
        entity_specs = [
            ("沈砚", "person"), ("白芷", "person"), ("老周", "person"), ("无脸纸童", "person"),
            ("雾城", "location"), ("槐安巷十七号", "location"), ("雾城旧档案馆", "location"),
            ("夜巡司", "organization"), ("巡夜灯", "item"), ("镇纸钉", "item"), ("潮湿账页", "item"),
            ("见雾", "ability"), ("识祟", "ability"), ("执灯", "ability"), ("立契", "ability"),
            ("巡界", "ability"), ("守夜", "ability"), ("被删除的童年记忆", "foreshadow"),
        ]
        entities = [
            {
                "canonicalName": name,
                "entityTypeName": kind,
                "aliasesJson": [],
                "attributesJson": {"name": name},
            }
            for name, kind in entity_specs
        ]
        relations = [
            {"subjectCanonicalName": "沈砚", "predicate": "调查", "objectCanonicalName": "夜巡司"},
            {"subjectCanonicalName": "沈砚", "predicate": "追查", "objectCanonicalName": "被删除的童年记忆"},
            {"subjectCanonicalName": "夜巡司", "predicate": "活动于", "objectCanonicalName": "雾城"},
            {"subjectCanonicalName": "老周", "predicate": "保管", "objectCanonicalName": "巡夜灯"},
            {"subjectCanonicalName": "沈砚", "predicate": "临时使用", "objectCanonicalName": "巡夜灯"},
            {"subjectCanonicalName": "无脸纸童", "predicate": "出现于", "objectCanonicalName": "槐安巷十七号"},
        ]
        rule_specs = [
            ("RANK-SEE-FOG", "progression", "见雾只能察觉异常，不能主动干预。"),
            ("RANK-KNOW-HAUNT", "progression", "识祟只能辨认局部规则，最早第20章且目标第30—40章进入。"),
            ("RANK-HOLD-LAMP", "progression", "执灯必须在第90—100章满足证据、训练、代价三条件后进入。"),
            ("FIRST-VOLUME-NO-CONTRACT", "progression", "第一卷不得进入立契，十几章内不得完成整卷升级。"),
            ("ITEM-LAMP", "item", "巡夜灯第3—5章仅获得临时使用权；第3章只能被动显示既存路径并付出记忆代价。"),
            ("ITEM-NAIL", "item", "镇纸钉最早第8章、目标第8—15章获得，且只能固定已识别规则。"),
            ("ITEM-LEDGER", "item", "潮湿账页最早第18章、目标第20—30章获得，不能直接给出答案。"),
            ("REVEAL-PAPER-CHILD", "reveal", "无脸纸童第43—60章只揭示身份第一层，第370章前不得确认完整身份。"),
            ("REVEAL-CHILDHOOD", "reveal", "童年真相第92—100章只揭示第一层，第580章前不得完整复述核心事件。"),
            ("RULE-NO-BRUTE-FORCE", "world", "怪异不能依靠纯战力消灭，必须识别规则、付出代价并处理后果。"),
            ("RULE-CHAPTER-BUDGET", "pacing", "每章只能消耗当前 ChapterBeat 和当前剧情预算。"),
            ("RULE-KNOWLEDGE", "knowledge", "人物只能使用其亲历、被告知或正式检索获得的信息。"),
        ]
        rules = [
            {"ruleCode": code, "category": category, "statement": statement, "severity": "high", "constraintJson": {"hard": True}}
            for code, category, statement in rule_specs
        ]
        return {"entities": entities, "relations": relations, "rules": rules}

    def _extract_structure(self, project: Any, markdown: str, request_id: str) -> tuple[dict[str, Any], str | None]:
        """Extract creative additions and merge them with user-approved facts.

        The required ranks, artifacts and reveal windows are deterministic; the
        analyzer only adds creative people, places and relationships.  This
        keeps a verbose reasoning model from redefining the authoritative
        ledger and keeps the JSON response deliberately small.
        """

        creative_source = markdown.split("## 长篇硬边界台账", 1)[0].strip()
        last_error: Exception | None = None
        for attempt, limit in enumerate((5000, 2500)):
            try:
                text, run_id = self._complete_role(project, "architect", [
                    {"role": "system", "content": (
                        "你是 Canon 分析器。只返回一个精简 JSON object，字段只能是 entities、relations、rules，"
                        "总长度不得超过1200个中文字符。只抽取输入中有明确依据、且不在系统硬边界台账中的创意补充。"
                        "entities 最多6项，每项只用 canonicalName、entityTypeName、aliasesJson、attributesJson；"
                        "entityTypeName 只能是 person、location、organization、item、ability、intel、foreshadow、time_point。"
                        "relations 最多4项，每项只用 subjectCanonicalName、predicate、objectCanonicalName。"
                        "rules 最多4项，每项只用 ruleCode、category、statement、severity、constraintJson。"
                        "不要安排章节数字，不要重新定义六阶、法器获得窗口或真相揭示窗口。"
                    )},
                    {"role": "user", "content": creative_source[:limit]},
                    *([{"role": "system", "content": "上次输出过长或无效；本次每个数组最多2项，确保 JSON 完整闭合。"}] if attempt else []),
                ], request_id, response_json=True, run_role="architect:proposal-analysis")
                extra = _json_object(text)
                return self._merge_structure(self._baseline_structure(), extra), run_id
            except (StoryError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
        if isinstance(last_error, StoryError):
            raise last_error
        raise StoryError(422, "CANON_ANALYSIS_INVALID", "Canon 分析器连续两次未返回合法精简 JSON。") from last_error

    @staticmethod
    def _merge_structure(baseline: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        allowed_types = {"person", "location", "organization", "item", "ability", "intel", "foreshadow", "time_point"}
        entities = list(baseline["entities"])
        names = {item["canonicalName"] for item in entities}
        for raw in extra.get("entities", []) if isinstance(extra.get("entities", []), list) else []:
            name = str(raw.get("canonicalName") or "").strip() if isinstance(raw, dict) else ""
            kind = str(raw.get("entityTypeName") or "").strip() if isinstance(raw, dict) else ""
            if not name or name in names or kind not in allowed_types:
                continue
            attrs = raw.get("attributesJson") if isinstance(raw.get("attributesJson"), dict) else {}
            attrs["name"] = name
            entities.append({"canonicalName": name, "entityTypeName": kind, "aliasesJson": raw.get("aliasesJson", []), "attributesJson": attrs})
            names.add(name)

        relations = list(baseline["relations"])
        for raw in extra.get("relations", []) if isinstance(extra.get("relations", []), list) else []:
            if not isinstance(raw, dict):
                continue
            subject = str(raw.get("subjectCanonicalName") or "").strip()
            obj = str(raw.get("objectCanonicalName") or "").strip()
            predicate = str(raw.get("predicate") or "").strip()
            if subject in names and obj in names and predicate:
                relations.append({"subjectCanonicalName": subject, "predicate": predicate, "objectCanonicalName": obj})

        rules = list(baseline["rules"])
        codes = {item["ruleCode"] for item in rules}
        for raw in extra.get("rules", []) if isinstance(extra.get("rules", []), list) else []:
            if not isinstance(raw, dict):
                continue
            code = str(raw.get("ruleCode") or "").strip()
            statement = str(raw.get("statement") or "").strip()
            if not code or code in codes or not statement:
                continue
            rules.append({
                "ruleCode": code, "category": str(raw.get("category") or "general"),
                "statement": statement, "severity": str(raw.get("severity") or "medium"),
                "constraintJson": raw.get("constraintJson") if isinstance(raw.get("constraintJson"), dict) else {},
            })
            codes.add(code)
        return {"entities": entities, "relations": relations, "rules": rules}

    # ------------------------------------------------------------------
    # Canon proposals
    # ------------------------------------------------------------------
    def create_canon_proposal(self, project_id: str, brief: StoryBrief, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        if project.project_kind != "standard":
            raise StoryError(409, "DEMO_PROJECT_WRITE_BLOCKED", "请在正式作品中生成 Canon。")
        brief_json = dumps(brief.model_dump(mode="json", by_alias=True))
        base_revision = self._canon_revision(project)
        now = _now()
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.scalar(
                select(CanonGenerationProposal)
                .where(
                    CanonGenerationProposal.project_id == project.id,
                    CanonGenerationProposal.status == "failed",
                    CanonGenerationProposal.brief_json == brief_json,
                    CanonGenerationProposal.base_revision == base_revision,
                )
                .order_by(CanonGenerationProposal.updated_at.desc())
                .limit(1)
            )
            if row:
                checkpoint = loads(row.structured_json) or {}
                sections = checkpoint.get("generationSections", {}) if isinstance(checkpoint, dict) else {}
                if not isinstance(sections, dict):
                    sections = {}
                row.status = "generating"
                row.revision += 1
                row.updated_at = now
            else:
                sections = {}
                row = CanonGenerationProposal(
                    id=str(uuid4()), project_id=project.id, base_revision=base_revision, status="generating",
                    brief_json=brief_json, content_markdown=f"# 《{brief.title}》Story Core",
                    structured_json=dumps({"generationSections": sections}),
                    readiness_json=dumps({"ready": False, "checks": [{
                        "code": "CANON_GENERATION_IN_PROGRESS", "status": "blocked", "detail": "Canon 正在分段生成。",
                    }]}),
                    model_run_id=None, revision=1, created_at=now, updated_at=now,
                )
                session.add(row)
            session.flush()
            proposal_id = row.id
        prompt = {
            **brief.model_dump(mode="json", by_alias=True),
            "fixedDecisions": {
                "direction": "现代中式规则怪谈、悬疑调查、克制成长",
                "protagonist": "沈砚",
                "city": "雾城",
                "coreConflict": "调查夜雾与夜巡司，同时追查被删除的童年记忆",
                "ranks": ["见雾", "识祟", "执灯", "立契", "巡界", "守夜"],
                "artifactGrades": ["遗物", "巡器", "封物", "祟核"],
                "firstArtifacts": ["巡夜灯", "镇纸钉", "潮湿账页"],
                "volumeRanges": VOLUMES,
                "firstVolumeProgression": ["1-10普通人到见雾", "11-40达到识祟", "41-89稳定与训练", "90-100满足三条件后执灯"],
                "artifactWindows": ["巡夜灯3-5章临时使用", "镇纸钉8-15章获得", "潮湿账页20-30章获得"],
                "layeredReveals": ["无脸纸童身份第一层43-60章", "童年真相第一层92-100章", "完整真相后续卷再揭示"],
            },
        }
        blueprint_sections = [
            (
                "core",
                "输出 Canon 的第一部分 Markdown，1800 个中文字符以内。只写：一句话故事内核、类型主题、时代地域、世界边界、怪异机制、主要人物、组织与人物知识边界。",
            ),
            (
                "systems",
                "输出 Canon 的第二部分 Markdown，1800 个中文字符以内。只写：六阶等级的能力边界、升级条件与代价，四类法器的规则，以及巡夜灯/镇纸钉/潮湿账页的功能、次数、代价和损坏状态。不要安排任何获得章节或揭示章节；巡夜灯允许未达识祟者被动看见既存路径，但主动固定路径必须达到执灯。",
            ),
        ]
        markdown_parts: list[str] = [f"# 《{brief.title}》Story Core"]
        model_run_id: str | None = None
        try:
            for section_name, instruction in blueprint_sections:
                part = str(sections.get(section_name) or "").strip()
                if not part:
                    part, model_run_id = self._complete_role(project, "architect", [
                        {"role": "system", "content": (
                            "你是长篇小说总架构师。只输出指定部分的中文 Markdown，不要解释、不要 JSON、不要重复其他部分。"
                            "参考作品只能提取抽象叙事特征，不得模仿原文。规则必须可检查且互不矛盾。"
                            + instruction
                        )},
                        {"role": "user", "content": dumps(prompt)},
                    ], request_id, run_role=f"architect:story-blueprint-{section_name}")
                    part = _remove_model_timing_claims(part)
                    sections[section_name] = part
                    with self.service.db.project_write(project.id, project.folder_path) as session:
                        checkpoint_row = session.get(CanonGenerationProposal, proposal_id)
                        if checkpoint_row:
                            checkpoint_row.content_markdown = "\n\n".join([f"# 《{brief.title}》Story Core", *sections.values()])
                            checkpoint_row.structured_json = dumps({"generationSections": sections})
                            checkpoint_row.model_run_id = model_run_id
                            checkpoint_row.updated_at = _now()
                markdown_parts.append(part)
        except StoryError as exc:
            self._fail_canon_generation(project, proposal_id, exc)
            raise
        markdown_parts.append(AUTHORITATIVE_CANON_BOUNDARIES)
        markdown = "\n\n".join(markdown_parts)
        try:
            structured, final_run_id = self._extract_structure(project, markdown, request_id)
        except StoryError as exc:
            self._fail_canon_generation(project, proposal_id, exc, sections=sections)
            raise
        readiness = self._canon_checks(markdown, structured)
        if not readiness["ready"]:
            missing = [item["code"] for item in readiness["checks"] if item["status"] == "blocked"]
            repaired, repair_run = self._complete_role(project, "architect", [
                {"role": "system", "content": "只输出补充缺项的 Markdown 小节，1200 个中文字符以内。不要重复完整 Canon，不要改变固定等级、法器和卷范围。"},
                {"role": "user", "content": dumps({"missing": missing, "fixedDecisions": prompt["fixedDecisions"]})},
            ], request_id, run_role="architect:story-blueprint-repair")
            markdown = f"{markdown}\n\n## 自动完整性补充\n{repaired.strip()}"
            structured, final_run_id = self._extract_structure(project, markdown, request_id)
            readiness = self._canon_checks(markdown, structured)
            model_run_id = repair_run or final_run_id or model_run_id
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(CanonGenerationProposal, proposal_id)
            if not row:
                raise StoryError(404, "CANON_PROPOSAL_NOT_FOUND", "Canon 生成检查点不存在。")
            row.status = "pending"
            row.content_markdown = markdown
            row.structured_json = dumps(structured)
            row.readiness_json = dumps(readiness)
            row.model_run_id = final_run_id or model_run_id
            row.revision += 1
            row.updated_at = _now()
            session.flush()
            return self._canon_proposal_dict(row)

    def _fail_canon_generation(
        self,
        project: Any,
        proposal_id: str,
        error: StoryError,
        *,
        sections: dict[str, Any] | None = None,
    ) -> None:
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(CanonGenerationProposal, proposal_id)
            if not row:
                return
            checkpoint = loads(row.structured_json) or {}
            if sections is not None:
                checkpoint = {"generationSections": sections}
            row.status = "failed"
            row.structured_json = dumps(checkpoint)
            row.readiness_json = dumps({"ready": False, "checks": [{
                "code": error.code, "status": "blocked", "detail": error.message,
            }]})
            row.revision += 1
            row.updated_at = _now()

    def list_canon_proposals(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._canon_proposal_dict(row) for row in session.scalars(
                select(CanonGenerationProposal).where(CanonGenerationProposal.project_id == project.id).order_by(CanonGenerationProposal.created_at.desc())
            ).all()]

    def canon_readiness(self, project_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        canon = self.service.phase4.get_canon(project.id)
        markdown = canon["documents"][0]["contentMarkdown"] if canon["documents"] else ""
        structured = {"entities": canon["entities"], "relations": canon["relations"], "rules": canon["rules"]}
        # Legacy fixed validation is only the explicit night-watch template.
        # All other projects use the generic StoryBrief-driven Canon contract.
        result = self._canon_checks(markdown, structured) if any(term in markdown for term in ("夜巡人", "沈砚", "雾城")) else self.service.phase13._generic_canon_checks(markdown, structured)
        result["revision"] = canon["documents"][0]["revision"] if canon["documents"] else 1
        return result

    def apply_canon_proposal(self, proposal_id: str, decision: ArchitectureProposalDecision, request_id: str) -> dict[str, Any]:
        project = self._project_for_canon_proposal(proposal_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(CanonGenerationProposal, proposal_id)
            if not row:
                raise StoryError(404, "CANON_PROPOSAL_NOT_FOUND", "Canon 提案不存在。")
            if row.status != "pending":
                raise StoryError(409, "CANON_PROPOSAL_NOT_PENDING", "Canon 提案已经处理。")
            if row.revision != decision.expected_revision:
                raise StoryError(409, "CANON_PROPOSAL_REVISION_CONFLICT", "Canon 提案 revision 冲突。", {"currentRevision": row.revision})
            doc = session.get(CanonDocument, "story-core")
            current_revision = doc.revision if doc else 1
            if current_revision != row.base_revision:
                raise StoryError(409, "CANON_REVISION_CONFLICT", "Canon 已在提案生成后发生变化。", {"currentRevision": current_revision})
            structured = loads(row.structured_json) or {}
            incubation_metadata = loads(row.brief_json) or {} if row.brief_json else {}
            incubation = incubation_metadata.get("incubation") is True
            if incubation:
                self.service.phase13.assert_canon_proposal_upstream(session, row)
            # Readiness is derived data. Recompute it at the write boundary so
            # a proposal cannot be accepted or rejected because a stored
            # validator snapshot predates the current deterministic rules.
            readiness = self.service.phase13._generic_canon_checks(row.content_markdown, structured, incubation_metadata.get("brief")) if incubation else self._canon_checks(row.content_markdown, structured)
            row.readiness_json = dumps(readiness)
            if not readiness.get("ready"):
                raise StoryError(409, "CANON_PROPOSAL_INCOMPLETE", "Canon 提案未通过完整性检查。", readiness)
            now = _now()
            self.service.phase4._upsert_document(session, {
                "id": "story-core", "title": f"{project.title} Story Core", "kind": "story-core", "contentMarkdown": row.content_markdown,
            }, now)
            for item in structured.get("entities", []):
                self.service.phase4._upsert_entity(session, item, now)
            for item in structured.get("relations", []):
                self.service.phase4._upsert_relation(session, item, now)
            for item in structured.get("rules", []):
                self.service.phase4._upsert_rule(session, item, now)
            row.status = "applied"
            row.revision += 1
            row.updated_at = now
            row.applied_at = now
            session.add(self.service._audit("canon_generation.applied", "canon_generation_proposal", row.id, {"requestId": request_id}, request_id))
            self.service.phase4._rebuild_retrieval_index(session, project.id, now)
        self.service.phase4._mirror_canon_markdown_safely(project.id, project.folder_path)
        return self.service.phase4.get_canon(project.id)

    def reject_canon_proposal(self, proposal_id: str, decision: ArchitectureProposalDecision, request_id: str) -> dict[str, Any]:
        project = self._project_for_canon_proposal(proposal_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(CanonGenerationProposal, proposal_id)
            if not row:
                raise StoryError(404, "CANON_PROPOSAL_NOT_FOUND", "Canon 提案不存在。")
            if row.status != "pending" or row.revision != decision.expected_revision:
                raise StoryError(409, "CANON_PROPOSAL_REVISION_CONFLICT", "Canon 提案状态或 revision 已变化。")
            row.status = "rejected"
            row.revision += 1
            row.updated_at = _now()
            session.add(self.service._audit("canon_generation.rejected", "canon_generation_proposal", row.id, {"requestId": request_id}, request_id))
            return self._canon_proposal_dict(row)

    # ------------------------------------------------------------------
    # Hierarchical plan proposals
    # ------------------------------------------------------------------
    def create_plan_proposal(self, project_id: str, payload: PlanGenerationRequest, request_id: str) -> dict[str, Any]:
        project = self.service.get_project(project_id)
        if project.project_kind != "standard":
            raise StoryError(409, "DEMO_PROJECT_WRITE_BLOCKED", "请在正式作品中生成规划。")
        canon = self.service.phase4.get_canon(project.id)
        if not canon.get("locked"):
            raise StoryError(409, "CANON_NOT_LOCKED", "必须先锁定 Canon。")
        with self.service.db.project(project.id, project.folder_path) as session:
            plan = session.scalar(select(Plan))
            if not plan or plan.revision != payload.expected_plan_revision:
                raise StoryError(409, "PLAN_REVISION_CONFLICT", "规划 revision 冲突。", {"currentRevision": plan.revision if plan else None})
        story_core = canon["documents"][0]["contentMarkdown"]
        enrichment: dict[str, Any] = {}
        model_run_id: str | None = None
        try:
            text, model_run_id = self._complete_role(project, "planner", [
                {"role": "system", "content": (
                    "你是长篇规划师。只返回 JSON object，字段为 volumeThemes 和 firstVolumeArcs。"
                    "卷范围和标题必须严格沿用输入；只补充每卷核心冲突、必须回收内容，以及第一卷 5-20 章故事弧。"
                    "不得更改前五章固定节拍，不得提前完成终局或升级。"
                )},
                {"role": "user", "content": dumps({"volumes": VOLUMES, "firstBeats": FIRST_BEATS, "canon": story_core})},
            ], request_id, response_json=True, run_role="planner:hierarchical-plan")
            enrichment = _json_object(text)
        except (StoryError, ValueError, json.JSONDecodeError):
            # The fixed range, reveal and beat budgets are authoritative. A
            # planner enrichment failure is visible in validation but does not
            # invent or loosen those safety boundaries.
            enrichment = {}
        plan_payload = self._fixed_plan_payload(enrichment)
        validation = self._validate_plan_payload(plan_payload)
        now = _now()
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = PlanGenerationProposal(
                id=str(uuid4()), project_id=project.id, base_revision=payload.expected_plan_revision,
                status="pending", plan_json=dumps(plan_payload), validation_json=dumps(validation),
                model_run_id=model_run_id, revision=1, created_at=now, updated_at=now,
            )
            session.add(row)
            session.flush()
            return self._plan_proposal_dict(row)

    def list_plan_proposals(self, project_id: str) -> list[dict[str, Any]]:
        project = self.service.get_project(project_id)
        with self.service.db.project(project.id, project.folder_path) as session:
            return [self._plan_proposal_dict(row) for row in session.scalars(
                select(PlanGenerationProposal).where(PlanGenerationProposal.project_id == project.id).order_by(PlanGenerationProposal.created_at.desc())
            ).all()]

    def apply_plan_proposal(self, proposal_id: str, decision: ArchitectureProposalDecision, request_id: str) -> dict[str, Any]:
        project = self._project_for_plan_proposal(proposal_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(PlanGenerationProposal, proposal_id)
            plan = session.scalar(select(Plan))
            if not row or not plan:
                raise StoryError(404, "PLAN_PROPOSAL_NOT_FOUND", "规划提案不存在。")
            if row.status != "pending" or row.revision != decision.expected_revision:
                raise StoryError(409, "PLAN_PROPOSAL_REVISION_CONFLICT", "规划提案状态或 revision 已变化。")
            if plan.revision != row.base_revision:
                raise StoryError(409, "PLAN_REVISION_CONFLICT", "正式规划已在提案生成后变化。", {"currentRevision": plan.revision})
            validation = loads(row.validation_json) or {}
            if not validation.get("valid"):
                raise StoryError(409, "PLAN_PROPOSAL_INVALID", "规划提案未通过校验。", validation)
            data = loads(row.plan_json) or {}
            now = _now()
            plan.book_title = project.title
            plan.volume_title = "第一卷：雾城旧宅"
            plan.arc_title = "故事弧 01：旧宅来信"
            plan.chapter_start = 1
            plan.chapter_end = project.total_chapters
            plan.revision += 1
            session.execute(delete(PlanNode).where(PlanNode.plan_id == plan.id))
            session.execute(delete(StoryBudget).where(StoryBudget.project_id == project.id))
            for node in data["nodes"]:
                session.add(PlanNode(
                    id=node["id"], plan_id=plan.id, title=node["title"], type=node["type"],
                    target_chapter=node["targetChapter"], range_min=node["rangeMin"], range_max=node["rangeMax"],
                    importance=node.get("importance", 3), note=node.get("note", ""),
                    prerequisites_json=dumps(node.get("prerequisites", [])),
                    completion_conditions_json=dumps(node.get("completionConditions", [])),
                    foreshadows_json=dumps(node.get("foreshadows", [])), contracts_json=dumps(node.get("contracts", [])),
                    chapter_beats_json=dumps(node.get("chapterBeats", [])), pace=node.get("pace", "smooth"), revision=1,
                ))
            for budget in data["budgets"]:
                session.add(StoryBudget(
                    id=str(uuid4()), project_id=project.id, code=budget["code"], category=budget["category"],
                    title=budget["title"], earliest_chapter=budget["earliestChapter"],
                    target_min=budget["targetMin"], target_max=budget["targetMax"], latest_chapter=budget["latestChapter"],
                    prerequisites_json=dumps(budget.get("prerequisites", [])), metadata_json=dumps(budget.get("metadata", {})),
                    status="planned", revision=1, created_at=now, updated_at=now,
                ))
            row.status = "applied"
            row.revision += 1
            row.updated_at = now
            row.applied_at = now
            session.add(self.service._audit("plan_generation.applied", "plan_generation_proposal", row.id, {"requestId": request_id}, request_id))
        return self.service.get_plan(project.id)

    def reject_plan_proposal(self, proposal_id: str, decision: ArchitectureProposalDecision, request_id: str) -> dict[str, Any]:
        project = self._project_for_plan_proposal(proposal_id)
        with self.service.db.project_write(project.id, project.folder_path) as session:
            row = session.get(PlanGenerationProposal, proposal_id)
            if not row or row.status != "pending" or row.revision != decision.expected_revision:
                raise StoryError(409, "PLAN_PROPOSAL_REVISION_CONFLICT", "规划提案状态或 revision 已变化。")
            row.status = "rejected"
            row.revision += 1
            row.updated_at = _now()
            session.add(self.service._audit("plan_generation.rejected", "plan_generation_proposal", row.id, {"requestId": request_id}, request_id))
            return self._plan_proposal_dict(row)

    # ------------------------------------------------------------------
    # Serialization and deterministic plan safety
    # ------------------------------------------------------------------
    def _fixed_plan_payload(self, enrichment: dict[str, Any]) -> dict[str, Any]:
        themes = {int(item.get("number", 0)): item for item in enrichment.get("volumeThemes", []) if isinstance(item, dict)}
        nodes: list[dict[str, Any]] = []
        for number, start, end, title in VOLUMES:
            theme = themes.get(number, {})
            nodes.append({
                "id": f"volume-{number}", "title": f"第{number}卷：{title}", "type": "卷",
                "targetChapter": end, "rangeMin": start, "rangeMax": end, "importance": 5,
                "note": str(theme.get("coreConflict") or f"完成《{title}》的阶段冲突，不提前消耗后续卷真相。"),
                "prerequisites": [] if number == 1 else [f"第{number - 1}卷正式完成"],
                "completionConditions": [str(theme.get("mustResolve") or f"回收第{number}卷承诺并建立下一卷冲突")],
                "foreshadows": [], "contracts": [f"VOLUME-{number:02d}"], "chapterBeats": [], "pace": "smooth",
            })
        nodes.extend([
            {
                "id": "arc-01-opening", "title": "旧宅来信与首次见雾", "type": "故事弧", "targetChapter": 10,
                "rangeMin": 1, "rangeMax": 10, "importance": 5,
                "note": "只建立异常、调查动机和见雾阶段，不解释夜巡司与童年真相。",
                "prerequisites": ["作品 Canon 已锁定"], "completionConditions": ["沈砚确认夜雾真实存在", "沈砚进入见雾阶段"],
                "foreshadows": ["旧宅来信", "无脸纸童", "童年记忆缺口"], "contracts": ["ARC-OPENING-01"],
                "chapterBeats": FIRST_BEATS, "pace": "slow",
            },
            {
                "id": "arc-02-learning", "title": "规则学习与纸人追踪", "type": "故事弧", "targetChapter": 40,
                "rangeMin": 11, "rangeMax": 40, "importance": 4,
                "note": "逐步掌握识祟，不得揭示纸童身份。", "prerequisites": ["沈砚进入见雾阶段"],
                "completionConditions": ["沈砚达到识祟", "建立纸人规则证据链"], "foreshadows": ["潮湿账页"],
                "contracts": ["ARC-LEARNING-02"], "chapterBeats": [], "pace": "smooth",
            },
            {
                "id": "arc-03-investigation", "title": "旧宅与夜巡司外围调查", "type": "故事弧", "targetChapter": 89,
                "rangeMin": 41, "rangeMax": 89, "importance": 4,
                "note": "稳定能力并收集升级证据，不得提前执灯。", "prerequisites": ["达到识祟"],
                "completionConditions": ["取得升级所需证据与训练"], "foreshadows": ["夜巡司立场分裂"],
                "contracts": ["ARC-INVESTIGATION-03"], "chapterBeats": [], "pace": "smooth",
            },
            {
                "id": "arc-04-volume-finale", "title": "旧宅真相第一层", "type": "故事弧", "targetChapter": 100,
                "rangeMin": 90, "rangeMax": 100, "importance": 5,
                "note": "只揭开第一层真相并完成执灯升级，保留全书根谜。", "prerequisites": ["证据、训练与代价三个升级条件满足"],
                "completionConditions": ["沈砚进入执灯", "第一卷承诺完成"], "foreshadows": ["被删除的童年记录"],
                "contracts": ["ARC-FINALE-04"], "chapterBeats": [], "pace": "fast",
            },
        ])
        budgets = [
            {"code": "RANK-SEE-FOG", "category": "rank", "title": "进入见雾", "earliestChapter": 3, "targetMin": 5, "targetMax": 10, "latestChapter": 10, "prerequisites": ["首次接触夜雾", "承担巡夜灯代价"]},
            {"code": "RANK-KNOW-HAUNT", "category": "rank", "title": "进入识祟", "earliestChapter": 20, "targetMin": 30, "targetMax": 40, "latestChapter": 40, "prerequisites": ["完成规则证据链", "通过训练"]},
            {"code": "RANK-HOLD-LAMP", "category": "rank", "title": "进入执灯", "earliestChapter": 90, "targetMin": 95, "targetMax": 100, "latestChapter": 100, "prerequisites": ["证据", "训练", "明确代价"]},
            {"code": "ITEM-PATROL-LAMP", "category": "item", "title": "获得巡夜灯使用权", "earliestChapter": 3, "targetMin": 3, "targetMax": 5, "latestChapter": 5, "prerequisites": ["老周在场"]},
            {"code": "ITEM-PAPER-NAIL", "category": "item", "title": "获得镇纸钉", "earliestChapter": 8, "targetMin": 8, "targetMax": 15, "latestChapter": 15, "prerequisites": ["确认纸人规则"]},
            {"code": "ITEM-WET-LEDGER", "category": "item", "title": "获得潮湿账页", "earliestChapter": 18, "targetMin": 20, "targetMax": 30, "latestChapter": 30, "prerequisites": ["进入旧宅外围"]},
            {"code": "REVEAL-PAPER-CHILD", "category": "reveal", "title": "无脸纸童身份第一层", "earliestChapter": 43, "targetMin": 45, "targetMax": 60, "latestChapter": 60, "prerequisites": ["纸人规则证据链完整"]},
            {"code": "REVEAL-CHILDHOOD", "category": "reveal", "title": "童年真相第一层", "earliestChapter": 92, "targetMin": 95, "targetMax": 100, "latestChapter": 100, "prerequisites": ["潮湿账页与失踪名册互证"]},
        ]
        return {"bookTitle": "夜巡人", "totalChapters": 1000, "volumes": [
            {"number": n, "start": s, "end": e, "title": t} for n, s, e, t in VOLUMES
        ], "nodes": nodes, "budgets": budgets}

    def _validate_plan_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        volumes = data.get("volumes", [])
        expected = [{"number": n, "start": s, "end": e, "title": t} for n, s, e, t in VOLUMES]
        if volumes != expected:
            errors.append({"code": "PLAN_VOLUME_RANGES_INVALID", "message": "七卷范围必须连续覆盖 1-1000。"})
        beat_nodes = [node for node in data.get("nodes", []) if node.get("chapterBeats")]
        beats = beat_nodes[0]["chapterBeats"] if beat_nodes else []
        if [item.get("chapterNumber") for item in beats] != [1, 2, 3, 4, 5]:
            errors.append({"code": "PLAN_FIRST_BEATS_MISSING", "message": "必须精确覆盖第 1-5 章。"})
        for budget in data.get("budgets", []):
            values = [budget.get("earliestChapter"), budget.get("targetMin"), budget.get("targetMax"), budget.get("latestChapter")]
            if not all(isinstance(value, int) for value in values) or values != sorted(values):
                errors.append({"code": "PLAN_BUDGET_RANGE_INVALID", "message": f"剧情预算 {budget.get('code')} 范围非法。"})
        return {"valid": not errors, "errors": errors}

    def _project_for_canon_proposal(self, proposal_id: str):
        for project in self.service.list_projects():
            with self.service.db.project(project.id, project.folder_path) as session:
                if session.get(CanonGenerationProposal, proposal_id):
                    return project
        raise StoryError(404, "CANON_PROPOSAL_NOT_FOUND", "Canon 提案不存在。")

    def _project_for_plan_proposal(self, proposal_id: str):
        for project in self.service.list_projects():
            with self.service.db.project(project.id, project.folder_path) as session:
                if session.get(PlanGenerationProposal, proposal_id):
                    return project
        raise StoryError(404, "PLAN_PROPOSAL_NOT_FOUND", "规划提案不存在。")

    @staticmethod
    def _canon_proposal_dict(row: CanonGenerationProposal) -> dict[str, Any]:
        return {
            "id": row.id, "projectId": row.project_id, "baseRevision": row.base_revision, "status": row.status,
            "brief": loads(row.brief_json) or {}, "contentMarkdown": row.content_markdown,
            "structured": loads(row.structured_json) or {}, "readiness": loads(row.readiness_json) or {},
            "modelRunId": row.model_run_id, "revision": row.revision, "createdAt": row.created_at,
            "updatedAt": row.updated_at, "appliedAt": row.applied_at,
        }

    @staticmethod
    def _plan_proposal_dict(row: PlanGenerationProposal) -> dict[str, Any]:
        return {
            "id": row.id, "projectId": row.project_id, "baseRevision": row.base_revision, "status": row.status,
            "plan": loads(row.plan_json) or {}, "validation": loads(row.validation_json) or {},
            "modelRunId": row.model_run_id, "revision": row.revision, "createdAt": row.created_at,
            "updatedAt": row.updated_at, "appliedAt": row.applied_at,
        }
