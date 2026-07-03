from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterator, Optional

from student_memory_rules import (
    EARLY_OBSERVATION_STAGE,
    build_coach_memory_rule,
)

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError:
    BaseModel = Field = ValidationError = None

try:
    import nest_asyncio

    nest_asyncio.apply()
except ImportError:
    pass


PROJECT_ENDPOINT = os.getenv(
    "AZURE_AI_PROJECT_ENDPOINT",
    "https://teachagent-xumuchi-20260614.services.ai.azure.com/api/projects/proj-default",
)
MODEL_DEPLOYMENT = os.getenv("AZURE_AI_MODEL_DEPLOYMENT", "gpt-4o-mini")
COACH_AGENT_VERSION = "2026-06-28-adaptive-granularity"

DEFAULT_ROLE = "数学辅导教练"
DEFAULT_EXTRA_RULE = "语气亲切，适合中小学生，用词通俗易懂，避免使用专业术语。"
DEFAULT_MAX_TURNS = 8
MAX_TURN_CAP = int(os.getenv("COACH_AGENT_MAX_TURN_CAP", "12"))
DEFAULT_MAX_TOKENS = int(os.getenv("COACH_AGENT_MAX_TOKENS", "520"))
FINAL_PUNCTUATION = ("。", "？", "！", ".", "?", "!")
EMPTY_REPLY_REPAIR_MAX_TOKENS = 220
FORMING_PATTERN_STAGE = "forming_pattern"
VAGUE_COACH_PHRASES = (
    "结合一下",
    "结合起来",
    "整理一下",
    "继续想",
    "继续想想",
    "联系起来",
    "联立试试",
    "再想想",
    "看看怎么继续",
)
STRUCTURED_OUTPUT_MODEL_PREFIXES = (
    "gpt-5.1-codex",
    "gpt-5.1",
    "gpt-5-pro",
    "gpt-5-codex",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "codex-mini",
    "o3-pro",
    "o3-mini",
    "o1",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.1-nano",
    "gpt-4.1-mini",
    "o4-mini",
    "o3",
)


class ErrorType(str, Enum):
    CONCEPT_GAP = "concept_gap"
    MISREADING = "misreading"
    CALCULATION = "calculation"
    MISSING_STRATEGY = "missing_strategy"
    CARELESS = "careless"

    @classmethod
    def list_values(cls) -> list[str]:
        return [item.value for item in cls]


class ReplyQuality(str, Enum):
    EMPTY = "empty"
    WEAK = "weak"
    GOOD = "good"


class TeachingMode(str, Enum):
    SOCRATIC_STANDARD = "socratic_standard"
    SOCRATIC_LIGHT = "socratic_light"
    DIRECT_EXPLAIN = "direct_explain"


@dataclass(frozen=True)
class CoachStrategy:
    mode: TeachingMode
    trap: str
    prompt: str

    def as_dict(self) -> dict[str, str]:
        return {
            "mode": self.mode.value,
            "trap": self.trap,
            "prompt": self.prompt,
        }

    def as_prompt_block(self) -> str:
        return (
            f"教学模式：{self.mode.value}\n"
            f"学生可能卡点：{self.trap}\n"
            f"本轮策略话术：{self.prompt}"
        )


@dataclass(frozen=True)
class CoachTurnRecord:
    turn_index: int
    student_reply: str
    coach_reply: str
    reply_analysis: "ReplyAnalysis"


@dataclass
class CoachSession:
    problem_text: str
    error_type: ErrorType
    role_name: str = DEFAULT_ROLE
    student_profile: str = ""
    student_memory_profile: dict[str, Any] | None = None
    student_memory_context: str = ""
    extra_rule: str = DEFAULT_EXTRA_RULE
    max_turns: int = DEFAULT_MAX_TURNS
    initial_student_reply: str = ""
    handoff_context: str = ""
    diagnosis_strategy_hint: CoachStrategy | None = None
    turn_index: int = 0
    consecutive_stuck_turns: int = 0
    last_student_reply: str = ""
    last_coach_reply: str = ""
    last_reply_analysis: "ReplyAnalysis | None" = None
    established_points: list[str] = field(default_factory=list)
    turn_records: list[CoachTurnRecord] = field(default_factory=list)
    done: bool = False
    stop_reason: str = "continue"
    messages: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ReplyAnalysis:
    quality: ReplyQuality
    understands: bool
    completed: bool
    reason: str
    source: str = "fallback_heuristic"

    def as_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality.value,
            "understands": self.understands,
            "completed": self.completed,
            "reason": self.reason,
            "source": self.source,
        }


if BaseModel is not None:

    class ReplyAnalysisSchema(BaseModel):
        quality: ReplyQuality = Field(
            description="学生回答质量，只能是 empty、weak、good 三者之一。"
        )
        understands: bool = Field(
            description="学生是否真正理解当前题目的关键思路。"
        )
        completed: bool = Field(
            description="学生这一轮是否已经把当前题目所需的关键回答说完整。"
        )
        reason: str = Field(description="一句中文理由，说明判定依据。")

else:
    ReplyAnalysisSchema = None


@dataclass(frozen=True)
class CoachResponse:
    content: str
    reply_quality: ReplyQuality
    strategy: CoachStrategy
    turn_index: int
    stuck_turns: int
    done: bool
    stop_reason: str
    reply_analysis: ReplyAnalysis

    def as_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "reply_quality": self.reply_quality.value,
            "strategy": self.strategy.as_dict(),
            "strategy_mode": self.strategy.mode.value,
            "strategy_trap": self.strategy.trap,
            "strategy_prompt": self.strategy.prompt,
            "turn_index": self.turn_index,
            "stuck_turns": self.stuck_turns,
            "done": self.done,
            "stop_reason": self.stop_reason,
            "reply_analysis": self.reply_analysis.as_dict(),
        }


def ensure_azure_cli_on_path() -> Optional[str]:
    """Make AzureCliCredential work in Jupyter kernels launched outside a shell."""
    for cli_dir in ("/opt/homebrew/bin", "/usr/local/bin"):
        path = os.environ.get("PATH", "")
        if cli_dir not in path:
            os.environ["PATH"] = path + os.pathsep + cli_dir if path else cli_dir
    return shutil.which("az")


def diagnose_environment() -> dict[str, str | None]:
    """Small notebook helper for checking the runtime before calling Azure."""
    ensure_azure_cli_on_path()
    return {
        "coach_agent_version": COACH_AGENT_VERSION,
        "az_path": shutil.which("az"),
        "project_endpoint": PROJECT_ENDPOINT,
        "model_deployment": MODEL_DEPLOYMENT,
        "structured_outputs_supported": str(supports_structured_outputs(MODEL_DEPLOYMENT)),
    }


def supports_structured_outputs(model_name: str) -> bool:
    normalized = model_name.strip().lower()
    return any(normalized.startswith(prefix) for prefix in STRUCTURED_OUTPUT_MODEL_PREFIXES)


def normalize_error_type(error_type: ErrorType | str | None) -> ErrorType:
    if isinstance(error_type, ErrorType):
        return error_type
    try:
        return ErrorType(str(error_type))
    except ValueError:
        return ErrorType.CONCEPT_GAP


def analyze_student_reply(reply: str) -> ReplyQuality:
    """Local fallback when the model-based analysis tool is unavailable."""
    if not isinstance(reply, str):
        return ReplyQuality.EMPTY

    normalized = reply.strip().lower()
    empty_exact = {"？", "?", "无", "空"}
    empty_markers = ["不会", "不知道", "没思路", "不清楚", "忘了"]
    if (
        not normalized
        or normalized in empty_exact
        or any(marker in normalized for marker in empty_markers)
    ):
        return ReplyQuality.EMPTY

    progress_points = extract_progress_points(reply)
    if progress_points:
        return ReplyQuality.GOOD

    good_markers = [
        "先",
        "因为",
        "所以",
        "条件",
        "中间量",
        "公式",
        "第一步",
        "第二步",
        "=",
        "解得",
        "推导",
        "计算",
        "写出",
        "代入",
        "相减",
        "相加",
        "消去",
        "移项",
        "化简",
        "比较",
    ]
    if len(normalized) > 5 and any(marker in normalized for marker in good_markers):
        return ReplyQuality.GOOD

    partial_progress_markers = [
        "可以先",
        "应该先",
        "下一步",
        "先求",
        "先看",
        "把它",
        "两个式子",
        "这一项",
        "后一项",
        "前一项",
    ]
    if len(normalized) >= 8 and any(marker in normalized for marker in partial_progress_markers):
        return ReplyQuality.WEAK

    return ReplyQuality.WEAK


def infer_completed_from_reply(reply: str) -> bool:
    if not isinstance(reply, str):
        return False
    normalized = reply.strip().lower()
    if not normalized:
        return False
    completion_markers = [
        "所以",
        "因此",
        "答案",
        "结果",
        "等于",
        "最后",
        "解得",
    ]
    return len(normalized) > 8 and any(marker in normalized for marker in completion_markers)


def canonicalize_progress_text(text: str) -> str:
    return " ".join(str(text or "").replace("\n", " ").split()).strip().lower()


def extract_progress_points(text: str) -> list[str]:
    normalized = " ".join(str(text or "").replace("\r", "\n").split())
    if not normalized:
        return []

    raw_parts = [
        part.strip(" ，。；;、")
        for part in re.split(r"[。\n；;!?！？]", normalized)
    ]
    points: list[str] = []
    for part in raw_parts:
        candidate = part.strip()
        if len(candidate) < 6 or len(candidate) > 120:
            continue
        if not any(marker in candidate for marker in ("=", "得", "所以", "因此", "可得", "则", "说明")):
            continue
        if candidate.startswith(("我觉得", "我不会", "不知道", "是不是")) and "=" not in candidate:
            continue
        points.append(candidate)
        if len(points) >= 4:
            break
    return points


def merge_established_points(
    existing_points: list[str],
    new_points: list[str],
) -> list[str]:
    merged = list(existing_points)
    seen = {canonicalize_progress_text(item) for item in existing_points if item.strip()}
    for point in new_points:
        normalized = canonicalize_progress_text(point)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(point.strip())
    return merged[-8:]


def build_recent_history_block(session: CoachSession) -> str:
    if not session.turn_records:
        return "无历史轮次。"
    lines: list[str] = []
    for record in session.turn_records[-3:]:
        lines.append(f"- 第 {record.turn_index} 轮学生：{record.student_reply.strip() or '无回答'}")
        lines.append(f"- 第 {record.turn_index} 轮 coach：{record.coach_reply.strip() or '无回复'}")
    return "\n".join(lines)


def build_established_points_block(
    session: CoachSession,
    current_student_reply: str,
) -> tuple[str, str]:
    current_points = extract_progress_points(current_student_reply)
    merged_points = merge_established_points(session.established_points, current_points)
    latest_point = current_points[-1] if current_points else (merged_points[-1] if merged_points else "")
    if not merged_points:
        return "暂无。", latest_point
    block = "\n".join(f"- {point}" for point in merged_points[-6:])
    return block, latest_point


def is_stuck_reply(reply_analysis: ReplyAnalysis) -> bool:
    if reply_analysis.completed:
        return False
    if reply_analysis.quality == ReplyQuality.GOOD and reply_analysis.understands:
        return False
    return reply_analysis.quality in {ReplyQuality.EMPTY, ReplyQuality.WEAK} or not reply_analysis.understands


def compute_next_stuck_turns(
    session: CoachSession,
    reply_analysis: ReplyAnalysis,
) -> int:
    if not is_stuck_reply(reply_analysis):
        return 0
    return session.consecutive_stuck_turns + 1


def describe_granularity_level(stuck_turns: int) -> str:
    if stuck_turns <= 0:
        return "正常提示"
    if stuck_turns == 1:
        return "具体提示"
    return "破局提示"


def build_granularity_rules(
    error_type: ErrorType,
    stuck_turns: int,
) -> str:
    common_rules = [
        f"连续未推进轮次：{stuck_turns}",
        f"当前引导颗粒度：{describe_granularity_level(stuck_turns)}",
    ]
    if stuck_turns <= 0:
        common_rules.extend(
            [
                "本轮仍然要只推进当前题的一步，不要泛泛而谈。",
                "至少点出一个明确对象，例如中间量、式子、条件或计算位置。",
            ]
        )
    elif stuck_turns == 1:
        common_rules.extend(
            [
                "学生上一轮没有真正推进，本轮提示必须更具体。",
                "必须出现一个可执行动作动词，例如“先写出… / 设出… / 代入… / 相减… / 比较… / 移项…”。",
                "禁止只说“结合一下”“整理一下”“继续想想”“把两个式子联系起来”这类空泛话术。",
            ]
        )
    else:
        common_rules.extend(
            [
                "学生已经连续卡住，本轮必须给破局提示，而不是继续重复方向性提醒。",
                "你可以直接点明下一步要写出的式子、中间量或要做的唯一操作，但仍不要把整题最终答案整段讲完。",
                "回复里必须明确写出“先……再……”或“把……写出来，然后……”这样的动作链。",
                "禁止使用空泛提示，例如“结合条件”“整理一下”“联立试试”“想想怎么继续”。",
            ]
        )

    type_rules = {
        ErrorType.MISSING_STRATEGY: "如果是缺少思路，优先直接点明下一步该抓哪个中间量，或该先写出哪两个对象/式子，再说明要做什么操作。",
        ErrorType.CONCEPT_GAP: "如果是概念漏洞，先用一句最短解释补概念，再立刻点名这个概念在题里的具体落点。",
        ErrorType.CALCULATION: "如果是计算失误，直接指出要核对的那一步代入、移项或化简，不要重讲整题。",
        ErrorType.MISREADING: "如果是读题偏差，直接引用或转述被忽略的条件，并问这个条件具体限制了什么。",
        ErrorType.CARELESS: "如果是粗心失误，直接指出最该检查的一处符号、范围或抄写位置。",
    }
    common_rules.append(type_rules[error_type])
    return "\n".join(f"- {rule}" for rule in common_rules)


def build_reply_analysis_prompt(session: CoachSession, student_reply: str) -> str:
    schema_text = get_reply_analysis_schema_text()
    return f"""
你是 coachagent 的学生理解度分析工具，只负责判断学生是否真的理解当前题目。

请根据题目、错因和学生最新回答，输出严格 JSON，不要输出 Markdown、解释或其他文字。
必须只输出一个 JSON 对象，第一字符是 {{，最后字符是 }}。
不要输出 ```json，不要输出前缀说明，不要输出多余换行。
quality 必须由你直接判断，不要依赖固定关键词机械分类。

JSON Schema：
{schema_text}

判定标准：
- quality 只能填写 empty、weak、good 三者之一。
- empty：学生没有给出有效思路，例如不会、不知道、空回答。
- weak：学生给出了一点方向，但缺少关键步骤、理由或存在明显不确定。
- good：学生只要说出了正确的关键下一步、关键中间式、关键变形动作，哪怕还没收尾，也优先判为 good。
- completed 只能填写 true 或 false。
- completed=true：学生这一轮已经把当前题目需要的关键回答说完整，当前题目可以收尾。
- completed=false：学生方向虽对，但这道题还没有答完整，下一轮应继续补全当前题目，不能跳到变式。
- 不要把“已经给出正确关键式子，但还没讲完”误判成 weak。

输出示例 1：
{{"quality":"empty","understands":false,"completed":false,"reason":"学生只说不会，没有给出有效步骤。"}}

输出示例 2：
{{"quality":"good","understands":true,"completed":false,"reason":"学生说出了正确第一步，但还没完成整题关键收尾。"}}

输出示例 3：
{{"quality":"good","understands":true,"completed":true,"reason":"学生已经说清关键步骤并给出完整结果。"}}

【题目】
{session.problem_text}

【学生错误类型】
{session.error_type.value}

【学生画像】
{session.student_profile.strip() or "无额外学生画像。"}

【学生最新回答】
{student_reply.strip() or "无回答"}
""".strip()


def get_reply_analysis_schema_text() -> str:
    if ReplyAnalysisSchema is None:
        return json.dumps(
            {
                "type": "object",
                "properties": {
                    "quality": {
                        "type": "string",
                        "enum": ["empty", "weak", "good"],
                    },
                    "understands": {"type": "boolean"},
                    "completed": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["quality", "understands", "completed", "reason"],
                "additionalProperties": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(
        ReplyAnalysisSchema.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )


def extract_json_object(raw_text: str) -> str | None:
    text = raw_text.strip()
    if not text:
        return None
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def parse_reply_analysis(raw_text: str) -> ReplyAnalysis | None:
    json_text = extract_json_object(raw_text)
    if json_text is None:
        return None

    if ReplyAnalysisSchema is not None:
        try:
            parsed = ReplyAnalysisSchema.model_validate_json(json_text)
            return ReplyAnalysis(
                quality=parsed.quality,
                understands=parsed.understands,
                completed=parsed.completed,
                reason=parsed.reason.strip() or "模型未给出理由。",
                source="ai_tool_text_json_validated",
            )
        except ValidationError:
            pass

    parsed_dict = parse_reply_analysis_dict(json_text)
    if parsed_dict is None:
        return None

    quality, understands, completed, reason = parsed_dict
    return ReplyAnalysis(
        quality=quality,
        understands=understands,
        completed=completed,
        reason=reason,
        source="ai_tool_text_json_basic",
    )


def parse_reply_analysis_dict(
    json_text: str,
) -> tuple[ReplyQuality, bool, bool, str] | None:
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None

    try:
        quality = ReplyQuality(str(data["quality"]).strip())
    except (KeyError, ValueError):
        return None

    raw_understands = data.get("understands", quality == ReplyQuality.GOOD)
    if isinstance(raw_understands, bool):
        understands = raw_understands
    elif isinstance(raw_understands, str):
        understands = raw_understands.strip().lower() in {"true", "yes", "是", "懂了"}
    else:
        understands = bool(raw_understands)

    raw_completed = data.get("completed", False)
    if isinstance(raw_completed, bool):
        completed = raw_completed
    elif isinstance(raw_completed, str):
        completed = raw_completed.strip().lower() in {"true", "yes", "是", "完成了"}
    else:
        completed = bool(raw_completed)

    reason = str(data.get("reason", "")).strip() or "模型未给出理由。"
    return quality, understands, completed, reason


def build_reply_analysis_fallback(
    fallback_quality: ReplyQuality,
    reason: str,
    *,
    completed: bool = False,
) -> ReplyAnalysis:
    return ReplyAnalysis(
        quality=fallback_quality,
        understands=fallback_quality == ReplyQuality.GOOD,
        completed=completed,
        reason=reason,
    )


def get_coach_strategy(
    error_type: ErrorType | str,
    reply_quality: ReplyQuality | str,
    *,
    turn_index: int = 0,
    total_turns: int = DEFAULT_MAX_TURNS,
    understands: bool | None = None,
    completed: bool = False,
    stuck_turns: int = 0,
) -> CoachStrategy:
    error_type = normalize_error_type(error_type)
    quality = ReplyQuality(reply_quality)
    is_final_turn = turn_index + 1 >= total_turns

    base_strategies = {
        ErrorType.MISSING_STRATEGY: CoachStrategy(
            mode=TeachingMode.SOCRATIC_STANDARD,
            trap="学生知道局部知识，但不会先确定中间目标。",
            prompt="先帮学生把问题拆小，只追问一个关键中间量。",
        ),
        ErrorType.MISREADING: CoachStrategy(
            mode=TeachingMode.SOCRATIC_LIGHT,
            trap="学生跳过限制条件，直接套用熟悉方法。",
            prompt="提醒学生回到题干，找出被忽略的限制条件。",
        ),
        ErrorType.CALCULATION: CoachStrategy(
            mode=TeachingMode.SOCRATIC_LIGHT,
            trap="学生能建模，但计算链条不稳定。",
            prompt="让学生只核对当前一步计算，不要一次讲完整题。",
        ),
        ErrorType.CARELESS: CoachStrategy(
            mode=TeachingMode.DIRECT_EXPLAIN,
            trap="学生不是知识点缺失，而是缺少检查流程。",
            prompt="直接指出应检查的位置，并给一个可复用的检查方法。",
        ),
        ErrorType.CONCEPT_GAP: CoachStrategy(
            mode=TeachingMode.DIRECT_EXPLAIN,
            trap="学生缺少必要概念，继续追问会放大挫败。",
            prompt="先解释核心概念，再把概念放回题目里。",
        ),
    }

    strategy = base_strategies[error_type]
    if understands is None:
        understands = quality == ReplyQuality.GOOD

    if stuck_turns >= 2 and not completed:
        prompt = {
            ErrorType.MISSING_STRATEGY: "学生已经连续卡在关键步骤。不要再给抽象方向，必须直接点明下一步该写出的中间量或两个式子，再说明要做的一个操作，最后只问一个最小验证问题。",
            ErrorType.CONCEPT_GAP: "学生连续没有推进。先用一句话补当前缺的概念，再立刻指向题里要套用它的具体位置，最后只问一个极短验证问题。",
            ErrorType.CALCULATION: "学生连续没有推进。直接指出要检查的那一行计算或代入，不要重讲整题，最后只让他复核这一小步。",
            ErrorType.MISREADING: "学生连续没有推进。直接指出被忽略的条件或求解对象，并让他只回答这个条件限制了什么。",
            ErrorType.CARELESS: "学生连续没有推进。直接指出最需要复查的一处符号、范围或抄写位置，再让他自己核对这一处。",
        }[error_type]
        mode = (
            TeachingMode.DIRECT_EXPLAIN
            if error_type in {ErrorType.CONCEPT_GAP, ErrorType.CARELESS} or is_final_turn
            else TeachingMode.SOCRATIC_LIGHT
        )
        return replace(strategy, mode=mode, prompt=prompt)

    if quality == ReplyQuality.GOOD:
        mode = (
            TeachingMode.DIRECT_EXPLAIN
            if is_final_turn
            else TeachingMode.SOCRATIC_LIGHT
        )
        prompt = (
            "学生已掌握且当前题已答完整。最后一轮请简短总结关键步骤，并给一个变式练习方向。"
            if completed and is_final_turn
            else (
                "学生已经把当前题说完整。先简短肯定，再用一句话总结，不要重复展开。"
                if completed
                else "学生方向基本正确，但当前题还没答完整。先肯定，再只追问当前题缺的那一步，不要给变式。"
            )
        )
        return replace(strategy, mode=mode, prompt=prompt)

    if quality == ReplyQuality.EMPTY:
        mode = (
            TeachingMode.DIRECT_EXPLAIN
            if error_type in {ErrorType.CONCEPT_GAP, ErrorType.CARELESS} or is_final_turn
            else TeachingMode.SOCRATIC_LIGHT
        )
        prompt = (
            "学生完全没思路。先给一个很小但可执行的起点，要明确说出下一步先写什么或先做什么，不要直接给完整答案。"
            if mode != TeachingMode.DIRECT_EXPLAIN
            else "学生仍然没思路。直接讲清当前关键步骤，并明确点名要写的式子或对象，再立刻给一个极短验证问题。"
        )
        return replace(strategy, mode=mode, prompt=prompt)

    if quality == ReplyQuality.WEAK and understands:
        mode = (
            TeachingMode.DIRECT_EXPLAIN
            if is_final_turn
            else TeachingMode.SOCRATIC_LIGHT
        )
        prompt = (
            "学生方向基本对，但表达还不完整。最后一轮请补全关键步骤并收尾。"
            if is_final_turn
            else "学生方向基本对，但还不够完整。用一个短追问逼近完整解法，并把缺的那一步说得足够具体。"
        )
        return replace(strategy, mode=mode, prompt=prompt)

    if quality == ReplyQuality.WEAK and is_final_turn:
        return replace(
            strategy,
            mode=TeachingMode.DIRECT_EXPLAIN,
            prompt="已到最后一轮。直接补清关键思路，再给一个最小验证问题收尾。",
        )

    return strategy


def build_student_memory_context(student_memory_profile: dict[str, Any] | None) -> str:
    if not isinstance(student_memory_profile, dict) or not student_memory_profile:
        return ""
    return build_coach_memory_rule(student_memory_profile).context_text


def build_student_memory_strategy_note(
    strategy: CoachStrategy,
    session: CoachSession,
) -> str:
    profile = session.student_memory_profile
    if not isinstance(profile, dict) or not profile:
        return ""
    return build_coach_memory_rule(profile).strategy_note


def apply_student_memory_bias(
    strategy: CoachStrategy,
    session: CoachSession,
) -> CoachStrategy:
    note = build_student_memory_strategy_note(strategy, session)
    if not note:
        return strategy
    if note in strategy.prompt:
        return strategy
    return replace(strategy, prompt=f"{strategy.prompt}{note}")


def build_system_instructions(
    role_name: str = DEFAULT_ROLE,
    extra_rule: str = DEFAULT_EXTRA_RULE,
) -> str:
    return f"""
你是{role_name}，负责根据学生错因做短轮次数学辅导。

执行规则：
1. 本地程序会提供 reply_quality、completed 和 coach_strategy，你必须严格按它们回复。
2. empty/weak 时不要直接给最终答案，先给一个关键提示，再问一个学生能回答的小问题。
3. good 时可以总结思路，但只有 completed=true 时才允许收尾或给变式。
4. 如果 completed=false，即使 good，也只能继续补全当前题，不能跳到变式。
5. 每轮输出一个完整回答，控制在 200 个中文字符以内。
6. 回答必须完整，不要以冒号、逗号、顿号、列表开头或半句话结束。
7. 最后一句必须用句号、问号或感叹号收尾。

额外规则：{extra_rule}
""".strip()


def build_turn_prompt(
    session: CoachSession,
    student_reply: str,
    reply_analysis: ReplyAnalysis,
    strategy: CoachStrategy,
) -> str:
    next_stuck_turns = compute_next_stuck_turns(session, reply_analysis)
    recent_history_block = build_recent_history_block(session)
    established_points_block, latest_point = build_established_points_block(
        session,
        student_reply,
    )
    first_turn_focus = (
        "优先承接诊断阶段最后一句学生回答，只围绕当前真实卡点推进，不要回退到学生已经会的步骤。"
        if session.turn_index == 0 and session.handoff_context.strip()
        else ""
    )
    diagnosis_strategy_block = (
        f"\n【诊断阶段建议策略】\n{session.diagnosis_strategy_hint.as_prompt_block()}"
        if session.turn_index == 0 and session.diagnosis_strategy_hint is not None
        else ""
    )
    student_memory_block = (
        (
            "\n【学生长期记忆辅助信息】\n"
            f"{session.student_memory_context}\n"
            "使用规则：这只是辅助偏好，不要覆盖当前题的本轮诊断；如果冲突，以当前题当前轮的真实卡点为主。"
        )
        if session.turn_index == 0 and session.student_memory_context.strip()
        else ""
    )
    first_turn_rule = (
        "这是第一轮 coach 回复，必须把开场、判断和下一步引导说完整。"
        if session.turn_index == 0 and not first_turn_focus
        else f"这是第一轮 coach 回复，必须把开场、判断和下一步引导说完整。{first_turn_focus}"
        if session.turn_index == 0
        else "这是后续轮次，承接前文，不要重复开场。"
    )
    profile = session.student_profile.strip() or "无额外学生画像。"
    granularity_block = build_granularity_rules(
        session.error_type,
        next_stuck_turns,
    )
    latest_point_rule = (
        f"学生最新已经明确写出了这个关键步骤：{latest_point}。你必须直接沿着这一步继续推进，不能回头让学生重复写它。"
        if latest_point
        else "如果学生最新回答里已经出现关键式子或中间结果，你必须从那一步继续推进，不能回头重复追问。"
    )

    return f"""
【题目】
{session.problem_text}

【学生画像】
{profile}

【学生错误类型】
{session.error_type.value}

【最近几轮真实对话进展】
{recent_history_block}

【已经确认学生会的步骤 / 已写出的关键式子】
{established_points_block}

【学生最新回答】
{student_reply.strip() or "无回答"}
{diagnosis_strategy_block}
{student_memory_block}

【学生理解度分析工具结果】
回答质量：{reply_analysis.quality.value}
是否理解：{"是" if reply_analysis.understands else "否"}
是否答完整：{"是" if reply_analysis.completed else "否"}
判定来源：{reply_analysis.source}
判定理由：{reply_analysis.reason}
教学模式：{strategy.mode.value}
本轮策略话术：{strategy.prompt}

【引导颗粒度升级规则】
{granularity_block}

【回复要求】
{first_turn_rule}
额外规则：{session.extra_rule}
承接规则：{latest_point_rule}
不要重复规则：如果某个式子、结论或中间量已经出现在“已经确认学生会的步骤”里，就不要再问“你能不能写出它”。下一问必须是它后面的直接一步。
请只输出 coach 对学生说的话，不要输出分析过程、字段名或 JSON。
输出一个完整回答，控制在 200 个中文字符以内，结尾用句号、问号或感叹号。
如果“是否答完整”为“否”，你这一轮只能补全当前题，不能给变式练习。
如果连续未推进轮次大于等于 1，本轮必须给出可执行的关键步骤提示，不能只给方向性提醒。
""".strip()


def looks_complete(text: str) -> bool:
    return text.strip().endswith(FINAL_PUNCTUATION)


def is_vague_guidance(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    has_action = any(
        marker in normalized
        for marker in ("先", "再", "写出", "设", "代入", "相减", "相加", "比较", "移项", "令")
    )
    if has_action:
        return False
    return any(phrase in normalized for phrase in VAGUE_COACH_PHRASES)


def repair_vague_guidance(
    session: CoachSession,
    reply_analysis: ReplyAnalysis,
    strategy: CoachStrategy,
) -> str | None:
    if session.consecutive_stuck_turns + 1 < 2:
        return None
    if session.error_type == ErrorType.MISSING_STRATEGY:
        return (
            "你现在先别想整题结论。先把题里现成的两个式子写出来，例如当前这一项和下一项各自对应的式子，然后只做一个动作：把它们相减或改写成同一种形式。你先说这一步你准备写哪两个式子？"
        )
    if session.error_type == ErrorType.CONCEPT_GAP:
        return (
            "我们先只补当前题缺的那个概念，再立刻放回题里。你先说出这里要用的定义或公式名称，我再带你接下一步。"
        )
    if session.error_type == ErrorType.CALCULATION:
        return (
            "这轮先不重讲整题，只核对当前这一步。请你把刚才代入或化简的那一行单独写出来，我们只检查这一行。"
        )
    if session.error_type == ErrorType.MISREADING:
        return (
            "先停一下，回到题干。请你只找出题里真正要求你求的对象，或者最容易被忽略的限制条件。"
        )
    if session.error_type == ErrorType.CARELESS:
        return (
            "这轮先只检查一个地方：最容易抄错或符号错的那一行。你先把那一行单独写出来。"
        )
    if reply_analysis.completed:
        return "你的思路快完整了。你把最后缺的那一步明确写出来，我们就能收尾。"
    return None


def should_extend_session(
    session: CoachSession,
    reply_analysis: ReplyAnalysis,
) -> bool:
    if reply_analysis.completed:
        return False
    if session.max_turns >= MAX_TURN_CAP:
        return False
    if reply_analysis.quality == ReplyQuality.GOOD:
        return True
    if reply_analysis.quality == ReplyQuality.WEAK and reply_analysis.understands:
        return True
    return False


class FoundryCoachAgent:
    """Notebook-friendly CoachAgent backed by Azure AI Foundry chat completions."""

    def __init__(
        self,
        project_endpoint: str = PROJECT_ENDPOINT,
        model_deployment: str = MODEL_DEPLOYMENT,
        *,
        use_default_credential: bool = False,
        use_ai_reply_analyzer: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = 0.2,
    ) -> None:
        ensure_azure_cli_on_path()
        try:
            from azure.ai.projects import AIProjectClient
            from azure.identity import AzureCliCredential, DefaultAzureCredential
        except ImportError as exc:
            raise ImportError(
                "Missing Azure SDK packages. In Jupyter run: "
                "%pip install -U azure-ai-projects azure-identity openai nest_asyncio pydantic"
            ) from exc

        credential = (
            DefaultAzureCredential()
            if use_default_credential
            else AzureCliCredential()
        )
        project = AIProjectClient(endpoint=project_endpoint, credential=credential)
        self.client = project.get_openai_client()
        self.model_deployment = model_deployment
        self.use_ai_reply_analyzer = use_ai_reply_analyzer
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.last_response: CoachResponse | None = None

    def create_session(
        self,
        *,
        problem_text: str,
        error_type: ErrorType | str = ErrorType.CONCEPT_GAP,
        role_name: str = DEFAULT_ROLE,
        student_profile: str = "",
        student_memory_profile: dict[str, Any] | None = None,
        extra_rule: str = DEFAULT_EXTRA_RULE,
        max_turns: int = DEFAULT_MAX_TURNS,
        initial_student_reply: str = "",
        handoff_context: str = "",
        diagnosis_strategy_hint: CoachStrategy | None = None,
    ) -> CoachSession:
        error_type = normalize_error_type(error_type)
        system_prompt = build_system_instructions(role_name, extra_rule)
        messages = [{"role": "system", "content": system_prompt}]
        student_memory_context = build_student_memory_context(student_memory_profile)
        if student_memory_context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "【学生长期记忆辅助画像】\n"
                        f"{student_memory_context}\n"
                        "使用规则：这是辅助偏好，不要压过当前题当前轮的真实诊断。"
                    ),
                }
            )
        if handoff_context.strip():
            messages.append({"role": "system", "content": handoff_context.strip()})
        return CoachSession(
            problem_text=problem_text,
            error_type=error_type,
            role_name=role_name,
            student_profile=student_profile,
            student_memory_profile=student_memory_profile,
            student_memory_context=student_memory_context,
            extra_rule=extra_rule,
            max_turns=max(1, min(max_turns, MAX_TURN_CAP)),
            initial_student_reply=initial_student_reply.strip(),
            handoff_context=handoff_context.strip(),
            diagnosis_strategy_hint=diagnosis_strategy_hint,
            messages=messages,
        )

    def start(
        self,
        session: CoachSession,
        student_reply: str | None = None,
    ) -> CoachResponse:
        initial_reply = student_reply
        if initial_reply is None:
            initial_reply = session.initial_student_reply.strip() or "我不会"
        return self.reply(initial_reply, session=session)

    def reply(
        self,
        student_reply: str,
        *,
        session: CoachSession,
        max_tokens: int | None = None,
        ensure_complete: bool = True,
    ) -> CoachResponse:
        reply_analysis, strategy, messages = self._prepare_turn(student_reply, session)
        content = self._complete(messages, max_tokens=max_tokens)

        if ensure_complete and not looks_complete(content):
            content = self._complete_unfinished_reply(messages, content)

        return self._finalize_turn(session, messages, content, reply_analysis, strategy)

    def stream_reply(
        self,
        student_reply: str,
        *,
        session: CoachSession,
        max_tokens: int | None = None,
        ensure_complete: bool = True,
    ) -> Iterator[str]:
        reply_analysis, strategy, messages = self._prepare_turn(student_reply, session)
        parts: list[str] = []
        stream = self.client.chat.completions.create(
            model=self.model_deployment,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
            stream=True,
        )

        for event in stream:
            if not event.choices:
                continue
            text = getattr(event.choices[0].delta, "content", None)
            if not text:
                continue
            parts.append(text)
            yield text

        content = "".join(parts).strip()
        if ensure_complete and not looks_complete(content):
            continuation = self._complete_unfinished_reply(messages, content)
            extra = continuation[len(content) :].lstrip()
            if extra:
                yield extra
            content = continuation

        self._finalize_turn(session, messages, content, reply_analysis, strategy)

    def print_stream_reply(
        self,
        student_reply: str,
        *,
        session: CoachSession,
        max_tokens: int | None = None,
    ) -> CoachResponse:
        for chunk in self.stream_reply(
            student_reply,
            session=session,
            max_tokens=max_tokens,
        ):
            print(chunk, end="", flush=True)
        print()
        if self.last_response is None:
            raise RuntimeError("No response was produced.")
        return self.last_response

    def _prepare_turn(
        self,
        student_reply: str,
        session: CoachSession,
    ) -> tuple[ReplyAnalysis, CoachStrategy, list[dict[str, str]]]:
        if session.done:
            raise RuntimeError(f"Session already ended: {session.stop_reason}")

        reply_analysis = self.analyze_student_reply_tool(student_reply, session=session)
        strategy = get_coach_strategy(
            session.error_type,
            reply_analysis.quality,
            turn_index=session.turn_index,
            total_turns=session.max_turns,
            understands=reply_analysis.understands,
            completed=reply_analysis.completed,
            stuck_turns=compute_next_stuck_turns(session, reply_analysis),
        )
        strategy = apply_student_memory_bias(strategy, session)
        session.last_student_reply = student_reply.strip()

        turn_prompt = build_turn_prompt(
            session=session,
            student_reply=student_reply,
            reply_analysis=reply_analysis,
            strategy=strategy,
        )
        messages = session.messages + [{"role": "user", "content": turn_prompt}]
        return reply_analysis, strategy, messages

    def analyze_student_reply_tool(
        self,
        student_reply: str,
        *,
        session: CoachSession,
    ) -> ReplyAnalysis:
        heuristic_quality = analyze_student_reply(student_reply)
        fallback = build_reply_analysis_fallback(
            heuristic_quality,
            "使用本地 fallback 规则判定。",
            completed=infer_completed_from_reply(student_reply),
        )
        if not self.use_ai_reply_analyzer:
            return fallback

        try:
            if supports_structured_outputs(self.model_deployment):
                structured = self._analyze_student_reply_structured(
                    student_reply,
                    session=session,
                )
                if structured is not None:
                    return structured
            else:
                json_mode = self._analyze_student_reply_json_mode(
                    student_reply,
                    session=session,
                )
                if json_mode is not None:
                    return json_mode
        except Exception as exc:
            repaired = self._repair_reply_analysis_json(
                build_reply_analysis_prompt(session, student_reply),
                str(exc),
            )
            if repaired is not None:
                return repaired
            return replace(fallback, reason=self._build_ai_analysis_error_reason(exc))

        prompt = build_reply_analysis_prompt(session, student_reply)
        try:
            raw = self._complete(
                [{"role": "user", "content": prompt}],
                max_tokens=180,
                temperature=0.0,
            )
        except Exception as exc:
            repaired = self._repair_reply_analysis_json(prompt, str(exc))
            if repaired is not None:
                return repaired
            return replace(fallback, reason=self._build_ai_analysis_error_reason(exc))
        parsed = parse_reply_analysis(raw)
        if parsed is None:
            repaired = self._repair_reply_analysis_json(prompt, raw)
            if repaired is not None:
                return repaired
        if parsed is not None:
            return parsed
        return replace(
            fallback,
            reason=(
                "模型输出不是可解析的 JSON，已使用本地 fallback。"
            ),
        )

    def _build_ai_analysis_error_reason(self, exc: Exception) -> str:
        if not supports_structured_outputs(self.model_deployment):
            return (
                "当前 deployment 不支持 Azure 官方 structured outputs，"
                f"AI 分析调用失败，已使用本地 fallback：{type(exc).__name__}"
            )
        return f"AI 分析工具调用失败，使用本地 fallback：{type(exc).__name__}"

    def _analyze_student_reply_structured(
        self,
        student_reply: str,
        *,
        session: CoachSession,
    ) -> ReplyAnalysis | None:
        if ReplyAnalysisSchema is None:
            return None

        beta_chat = getattr(getattr(self.client, "beta", None), "chat", None)
        completions = getattr(beta_chat, "completions", None)
        parse_fn = getattr(completions, "parse", None)
        if parse_fn is None:
            return None

        prompt = build_reply_analysis_prompt(session, student_reply)
        response = parse_fn(
            model=self.model_deployment,
            messages=[
                {
                    "role": "system",
                    "content": "你必须严格输出与 response_format 完全匹配的对象。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=180,
            temperature=0.0,
            response_format=ReplyAnalysisSchema,
        )

        message = response.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            refusal = getattr(message, "refusal", None)
            if refusal:
                raise ValueError(f"structured parse refusal: {refusal}")
            raise ValueError("structured parse returned no parsed object")
        return ReplyAnalysis(
            quality=parsed.quality,
            understands=parsed.understands,
            completed=parsed.completed,
            reason=parsed.reason.strip() or "模型未给出理由。",
            source="ai_tool_pydantic_parse",
        )

    def _analyze_student_reply_json_mode(
        self,
        student_reply: str,
        *,
        session: CoachSession,
    ) -> ReplyAnalysis | None:
        prompt = build_reply_analysis_prompt(session, student_reply)
        response = self.client.chat.completions.create(
            model=self.model_deployment,
            messages=[
                {
                    "role": "system",
                    "content": "你必须只输出一个合法 JSON 对象，不能输出任何解释。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=180,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = parse_reply_analysis(raw)
        if parsed is None:
            return None
        return replace(parsed, source="ai_tool_json_mode")

    def _repair_reply_analysis_json(
        self,
        original_prompt: str,
        raw_output: str,
    ) -> ReplyAnalysis | None:
        repair_prompt = f"""
把下面的坏输出修复成一个严格 JSON。
只保留 quality、understands、completed、reason 四个字段。
quality 只能是 empty、weak、good；understands/completed 必须是布尔值。
不要输出 Markdown，不要解释。
原始任务：{original_prompt}
错误输出：{raw_output or "无输出"}
""".strip()
        try:
            repaired_raw = self._complete(
                [{"role": "user", "content": repair_prompt}],
                max_tokens=180,
                temperature=0.0,
            )
        except Exception:
            return None
        repaired = parse_reply_analysis(repaired_raw)
        if repaired is None:
            return None
        return replace(repaired, source="ai_tool_text_json_repaired")

    def _complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model_deployment,
            messages=[
                {
                    "role": "system",
                    "content": "你必须只输出目标内容本身，不能输出空字符串。",
                }
            ]
            + messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature if temperature is None else temperature,
        )
        return (response.choices[0].message.content or "").strip()

    def _complete_unfinished_reply(
        self,
        messages: list[dict[str, str]],
        content: str,
    ) -> str:
        continuation_messages = messages + [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    "你的上一条 coach 回复没有完整结束。"
                    "请只补齐结尾，不要重复前文，最后用完整标点收尾。"
                ),
            },
        ]
        continuation = self._complete(continuation_messages, max_tokens=180)
        if not continuation:
            return content
        if continuation.startswith(content):
            return continuation.strip()
        return (content.rstrip() + continuation).strip()

    def _repair_empty_coach_reply(
        self,
        messages: list[dict[str, str]],
        student_reply: str,
        strategy: CoachStrategy,
        reply_analysis: ReplyAnalysis,
    ) -> str:
        repair_prompt = (
            "你上一条 coach 回复为空。"
            "请重写为 2-3 句完整中文，只输出对学生说的话，结尾必须有标点。"
        )
        repaired = self._complete(
            messages + [{"role": "user", "content": repair_prompt}],
            max_tokens=EMPTY_REPLY_REPAIR_MAX_TOKENS,
            temperature=0.0,
        ).strip()
        if repaired:
            return repaired

        if reply_analysis.quality == ReplyQuality.EMPTY:
            return "我们先不急着做完整题。先看原方程里最先能求出来的量是什么？"
        if reply_analysis.completed:
            return "你的思路已经基本完整了。请你再用一句话把最后结果说完整，好吗？"
        if strategy.mode == TeachingMode.DIRECT_EXPLAIN:
            return "这一步先抓当前题最关键的中间量，再把它代回去。你先试着说出这一步应该求什么？"
        return "你的方向是对的，但这题还没说完整。你把下一步该写什么再补一句，好吗？"

    def _finalize_turn(
        self,
        session: CoachSession,
        messages: list[dict[str, str]],
        content: str,
        reply_analysis: ReplyAnalysis,
        strategy: CoachStrategy,
    ) -> CoachResponse:
        safe_content = content.strip()
        if not safe_content:
            safe_content = self._repair_empty_coach_reply(
                messages,
                messages[-1]["content"] if messages else "",
                strategy,
                reply_analysis,
            )
        if not looks_complete(safe_content):
            safe_content = self._complete_unfinished_reply(messages, safe_content)
        if not safe_content:
            safe_content = "我们先把当前题补完整。你先说说下一步最关键的是哪一步？"
        if is_vague_guidance(safe_content):
            repaired_vague = repair_vague_guidance(session, reply_analysis, strategy)
            if repaired_vague:
                safe_content = repaired_vague

        session.messages = messages + [{"role": "assistant", "content": safe_content}]
        session.consecutive_stuck_turns = compute_next_stuck_turns(session, reply_analysis)
        session.last_reply_analysis = reply_analysis
        current_student_reply = session.last_student_reply.strip()
        session.established_points = merge_established_points(
            session.established_points,
            extract_progress_points(current_student_reply),
        )
        session.last_coach_reply = safe_content
        session.turn_records.append(
            CoachTurnRecord(
                turn_index=session.turn_index + 1,
                student_reply=current_student_reply,
                coach_reply=safe_content,
                reply_analysis=reply_analysis,
            )
        )
        session.turn_records = session.turn_records[-6:]
        session.turn_index += 1

        is_final_turn = session.turn_index >= session.max_turns
        if is_final_turn and should_extend_session(session, reply_analysis):
            session.max_turns = min(session.max_turns + 2, MAX_TURN_CAP)
            is_final_turn = False
        if reply_analysis.completed:
            session.done = True
            session.stop_reason = "student_understood"
        elif is_final_turn:
            session.done = True
            session.stop_reason = "max_turns"
        else:
            session.done = False
            session.stop_reason = "continue"

        response = CoachResponse(
            content=safe_content,
            reply_quality=reply_analysis.quality,
            strategy=strategy,
            turn_index=session.turn_index,
            stuck_turns=session.consecutive_stuck_turns,
            done=session.done,
            stop_reason=session.stop_reason,
            reply_analysis=reply_analysis,
        )
        self.last_response = response
        return response


def create_default_agent(**kwargs: Any) -> FoundryCoachAgent:
    return FoundryCoachAgent(**kwargs)


def notebook_demo(stream: bool = False) -> CoachResponse:
    agent = create_default_agent()
    session = agent.create_session(
        problem_text="已知 x+2=5，求 3x-1 的值。",
        error_type=ErrorType.MISSING_STRATEGY,
        student_profile="学生会基础方程，但经常不知道先算什么。",
    )
    if stream:
        return agent.print_stream_reply("我不会。", session=session)
    return agent.reply("我不会。", session=session)


if __name__ == "__main__":
    print(diagnose_environment())
    print("在 notebook 中导入 FoundryCoachAgent 后创建 session 再测试。")
