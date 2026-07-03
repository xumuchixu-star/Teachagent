from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError:
    BaseModel = Field = ValidationError = None

from coach_agent import (
    DEFAULT_EXTRA_RULE,
    DEFAULT_MAX_TURNS,
    DEFAULT_ROLE,
    ErrorType,
    FoundryCoachAgent,
    MODEL_DEPLOYMENT,
    PROJECT_ENDPOINT,
    ensure_azure_cli_on_path,
    supports_structured_outputs,
)
from diagnosis_agent import (
    DEFAULT_DIAGNOSIS_ROLE,
    DiagnosisResult,
    FoundryDiagnosisAgent,
)


ORCHESTRATOR_VERSION = "2026-06-17-diagnosis-orchestrator-v1"
DEFAULT_CONFIRMATION_ROLE = "数学错因确认助手"
DIRECT_TO_COACH_CONFIDENCE = 0.75
DEFAULT_MAX_CONFIRM_TURNS = 2
DEFAULT_MAX_ORCHESTRATOR_TURNS = 3


@dataclass
class DiagnosisFlowSession:
    problem_text: str
    reference_answer: str
    student_profile: str = ""
    student_memory_profile: dict[str, Any] | None = None
    diagnosis_role_name: str = DEFAULT_DIAGNOSIS_ROLE
    confirmation_role_name: str = DEFAULT_CONFIRMATION_ROLE
    coach_role_name: str = DEFAULT_ROLE
    coach_extra_rule: str = DEFAULT_EXTRA_RULE
    coach_max_turns: int = DEFAULT_MAX_TURNS
    max_confirm_turns: int = DEFAULT_MAX_CONFIRM_TURNS
    max_orchestrator_turns: int = DEFAULT_MAX_ORCHESTRATOR_TURNS
    direct_to_coach_confidence: float = DIRECT_TO_COACH_CONFIDENCE
    original_student_answer: str = ""
    latest_student_reply: str = ""
    diagnosis_history: list[DiagnosisResult] = field(default_factory=list)
    pending_diagnosis: DiagnosisResult | None = None
    pending_question: str | None = None
    phase: str = "initial_diagnosis"
    confirm_turn_index: int = 0
    orchestrator_turn_index: int = 0
    done: bool = False
    stop_reason: str = "continue"
    coach_session: Any | None = None
    messages: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ConfirmationReplyAnalysis:
    stance: Literal["confirm", "reject", "unclear"]
    has_new_reason: bool
    extracted_reason: str
    confidence: float
    reason: str
    source: str = "fallback_heuristic"

    def as_dict(self) -> dict[str, Any]:
        return {
            "stance": self.stance,
            "has_new_reason": self.has_new_reason,
            "extracted_reason": self.extracted_reason,
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(frozen=True)
class OrchestratorResult:
    action: Literal["ask_confirmation", "enter_coach", "continue_confirmation"]
    content: str
    diagnosis: DiagnosisResult | None
    confirmation_analysis: ConfirmationReplyAnalysis | None
    done: bool
    stop_reason: str
    coach_session: Any | None = None
    coach_initial_student_reply: str | None = None
    coach_handoff: str | None = None


if BaseModel is not None:

    class ConfirmationReplySchema(BaseModel):
        stance: Literal["confirm", "reject", "unclear"] = Field(
            description="学生对上一轮候选错因的态度，只能是 confirm、reject、unclear。"
        )
        has_new_reason: bool = Field(
            description="学生是否提供了新的、可用于重新诊断的理由。"
        )
        extracted_reason: str = Field(
            description="如果学生提供了新理由，请用一句中文提炼；否则给空字符串。"
        )
        confidence: float = Field(
            description="本次确认判断的置信度，范围 0 到 1。", ge=0.0, le=1.0
        )
        reason: str = Field(description="一句中文理由，说明为什么这样判断。")

else:
    ConfirmationReplySchema = None


def orchestrator_environment() -> dict[str, str]:
    ensure_azure_cli_on_path()
    return {
        "orchestrator_version": ORCHESTRATOR_VERSION,
        "project_endpoint": PROJECT_ENDPOINT,
        "model_deployment": MODEL_DEPLOYMENT,
        "structured_outputs_supported": str(
            supports_structured_outputs(MODEL_DEPLOYMENT)
        ),
    }


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


def get_confirmation_schema_text() -> str:
    if ConfirmationReplySchema is None:
        return json.dumps(
            {
                "type": "object",
                "properties": {
                    "stance": {
                        "type": "string",
                        "enum": ["confirm", "reject", "unclear"],
                    },
                    "has_new_reason": {"type": "boolean"},
                    "extracted_reason": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                },
                "required": [
                    "stance",
                    "has_new_reason",
                    "extracted_reason",
                    "confidence",
                    "reason",
                ],
                "additionalProperties": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(
        ConfirmationReplySchema.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )


def build_confirmation_system_instruction(
    role_name: str = DEFAULT_CONFIRMATION_ROLE,
) -> str:
    return f"""
你是{role_name}，负责判断学生是在确认上一轮候选错因，还是在反驳并补充新理由。

执行规则：
1. 你不是重新做完整错因诊断，只判断学生对上一轮候选错因的态度。
2. stance 只能是 confirm、reject、unclear 三者之一。
3. 如果学生表达“不是这个原因，我其实是……”这类内容，优先判为 reject。
4. 如果学生基本认可上一轮判断，哪怕没有明确说“对”，也可判为 confirm。
5. 如果学生说得模糊、前后矛盾或无法判断，就判为 unclear。
6. 你只能输出一个 JSON 对象，第一字符必须是 {{，最后字符必须是 }}。
7. 不要输出 ```json，不要输出任何解释、标题、前缀或补充说明。
8. JSON 必须严格包含 stance、has_new_reason、extracted_reason、confidence、reason 五个字段。
""".strip()


def build_confirmation_prompt(
    session: DiagnosisFlowSession,
    diagnosis: DiagnosisResult,
    confirmation_question: str,
    student_reply: str,
) -> str:
    schema_text = get_confirmation_schema_text()
    return f"""
请根据原题、学生原始回答、上一轮候选错因、确认问题和学生最新回复，判断学生是在确认、反驳还是说不清。

输出要求：
- 你必须只输出一个合法 JSON 对象。
- 第一字符必须是 {{，最后字符必须是 }}。
- 不要输出 Markdown 代码块，不要输出任何解释、标题、前缀或附加文字。
- stance 只能填写 confirm、reject、unclear。
- has_new_reason 填 true 或 false。
- extracted_reason 用一句中文提炼新的错误理由；没有就写空字符串。
- confidence 是 0 到 1 的小数。
- reason 要解释判断依据。

JSON Schema：
{schema_text}

【题目】
{session.problem_text.strip() or "未提供题目。"}

【标准答案】
{session.reference_answer.strip() or "未提供标准答案。"}

【学生画像】
{session.student_profile.strip() or "无额外学生画像。"}

【学生原始回答】
{session.original_student_answer.strip() or "无回答"}

【上一轮候选错因】
{diagnosis.error_type.value}

【上一轮诊断理由】
{diagnosis.reason}

【上一轮确认问题】
{confirmation_question.strip() or "无确认问题"}

【学生最新回复】
{student_reply.strip() or "无回答"}
""".strip()


def parse_confirmation_reply(raw_text: str) -> ConfirmationReplyAnalysis | None:
    json_text = extract_json_object(raw_text)
    if json_text is None:
        return None

    if ConfirmationReplySchema is not None:
        try:
            parsed = ConfirmationReplySchema.model_validate_json(json_text)
            return ConfirmationReplyAnalysis(
                stance=parsed.stance,
                has_new_reason=bool(parsed.has_new_reason),
                extracted_reason=parsed.extracted_reason.strip(),
                confidence=max(0.0, min(float(parsed.confidence), 1.0)),
                reason=parsed.reason.strip() or "模型未给出确认判断理由。",
                source="ai_tool_text_json_validated",
            )
        except ValidationError:
            pass

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None

    stance = str(data.get("stance", "")).strip()
    if stance not in {"confirm", "reject", "unclear"}:
        return None

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    return ConfirmationReplyAnalysis(
        stance=stance,
        has_new_reason=bool(data.get("has_new_reason", False)),
        extracted_reason=str(data.get("extracted_reason", "")).strip(),
        confidence=max(0.0, min(confidence, 1.0)),
        reason=str(data.get("reason", "")).strip() or "模型未给出确认判断理由。",
        source="ai_tool_text_json_basic",
    )


def build_confirmation_fallback(student_reply: str) -> ConfirmationReplyAnalysis:
    normalized = student_reply.strip().lower()

    reject_markers = (
        "不是",
        "不对",
        "不太对",
        "并不是",
        "不是这个",
        "我其实",
        "真正原因",
        "问题是",
    )
    confirm_markers = (
        "是的",
        "对",
        "对的",
        "确实",
        "应该是",
        "更像",
        "没错",
        "差不多",
    )

    if any(marker in normalized for marker in reject_markers):
        return ConfirmationReplyAnalysis(
            stance="reject",
            has_new_reason=len(normalized) > 6,
            extracted_reason=student_reply.strip(),
            confidence=0.45,
            reason="学生回复中出现否认语气，并带有补充说明。",
            source="fallback_heuristic",
        )

    if any(marker in normalized for marker in confirm_markers):
        return ConfirmationReplyAnalysis(
            stance="confirm",
            has_new_reason=False,
            extracted_reason="",
            confidence=0.45,
            reason="学生回复中出现认可语气。",
            source="fallback_heuristic",
        )

    return ConfirmationReplyAnalysis(
        stance="unclear",
        has_new_reason=len(normalized) > 8,
        extracted_reason=student_reply.strip() if len(normalized) > 8 else "",
        confidence=0.3,
        reason="学生回复没有明确表现出确认或反驳。",
        source="fallback_heuristic",
    )


class FoundryConfirmationAnalyzer:
    def __init__(
        self,
        diagnosis_agent: FoundryDiagnosisAgent,
        *,
        use_ai_confirmation: bool = True,
    ) -> None:
        self.client = diagnosis_agent.client
        self.model_deployment = diagnosis_agent.model_deployment
        self.use_ai_confirmation = use_ai_confirmation

    def analyze(
        self,
        student_reply: str,
        *,
        session: DiagnosisFlowSession,
        diagnosis: DiagnosisResult,
        confirmation_question: str,
    ) -> ConfirmationReplyAnalysis:
        fallback = build_confirmation_fallback(student_reply)
        if not self.use_ai_confirmation:
            return fallback

        prompt = build_confirmation_prompt(
            session,
            diagnosis,
            confirmation_question,
            student_reply,
        )
        messages = session.messages[:1] + [{"role": "user", "content": prompt}]

        try:
            if supports_structured_outputs(self.model_deployment):
                structured = self._analyze_structured(messages)
                if structured is not None:
                    return structured

            json_mode = self._analyze_json_mode(messages)
            if json_mode is not None:
                return json_mode

            raw = self._complete(messages, max_tokens=220)
            parsed = parse_confirmation_reply(raw)
            if parsed is not None:
                return parsed
        except Exception as exc:
            return ConfirmationReplyAnalysis(
                stance=fallback.stance,
                has_new_reason=fallback.has_new_reason,
                extracted_reason=fallback.extracted_reason,
                confidence=fallback.confidence,
                reason=f"AI 确认判断失败，已使用本地 fallback：{type(exc).__name__}",
                source="fallback_heuristic",
            )

        return ConfirmationReplyAnalysis(
            stance=fallback.stance,
            has_new_reason=fallback.has_new_reason,
            extracted_reason=fallback.extracted_reason,
            confidence=fallback.confidence,
            reason="模型输出不是可解析的 JSON，已使用本地 fallback。",
            source="fallback_heuristic",
        )

    def _analyze_structured(
        self,
        messages: list[dict[str, str]],
    ) -> ConfirmationReplyAnalysis | None:
        if ConfirmationReplySchema is None:
            return None

        beta_chat = getattr(getattr(self.client, "beta", None), "chat", None)
        completions = getattr(beta_chat, "completions", None)
        parse_fn = getattr(completions, "parse", None)
        if parse_fn is None:
            return None

        response = parse_fn(
            model=self.model_deployment,
            messages=messages,
            max_tokens=220,
            temperature=0.0,
            response_format=ConfirmationReplySchema,
        )
        message = response.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            return None

        return ConfirmationReplyAnalysis(
            stance=parsed.stance,
            has_new_reason=bool(parsed.has_new_reason),
            extracted_reason=parsed.extracted_reason.strip(),
            confidence=max(0.0, min(float(parsed.confidence), 1.0)),
            reason=parsed.reason.strip() or "模型未给出确认判断理由。",
            source="ai_tool_pydantic_parse",
        )

    def _analyze_json_mode(
        self,
        messages: list[dict[str, str]],
    ) -> ConfirmationReplyAnalysis | None:
        response = self.client.chat.completions.create(
            model=self.model_deployment,
            messages=messages,
            max_tokens=220,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = parse_confirmation_reply(raw)
        if parsed is None:
            return None
        return ConfirmationReplyAnalysis(
            stance=parsed.stance,
            has_new_reason=parsed.has_new_reason,
            extracted_reason=parsed.extracted_reason,
            confidence=parsed.confidence,
            reason=parsed.reason,
            source="ai_tool_json_mode",
        )

    def _complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 220,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model_deployment,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return (response.choices[0].message.content or "").strip()


class FoundryDiagnosisOrchestrator:
    def __init__(
        self,
        diagnosis_agent: FoundryDiagnosisAgent | None = None,
        coach_agent: FoundryCoachAgent | None = None,
        confirmation_analyzer: FoundryConfirmationAnalyzer | None = None,
    ) -> None:
        self.diagnosis_agent = diagnosis_agent or FoundryDiagnosisAgent()
        self.coach_agent = coach_agent or FoundryCoachAgent()
        self.confirmation_analyzer = confirmation_analyzer or FoundryConfirmationAnalyzer(
            self.diagnosis_agent
        )

    def create_session(
        self,
        *,
        problem_text: str,
        reference_answer: str,
        student_profile: str = "",
        student_memory_profile: dict[str, Any] | None = None,
        diagnosis_role_name: str = DEFAULT_DIAGNOSIS_ROLE,
        confirmation_role_name: str = DEFAULT_CONFIRMATION_ROLE,
        coach_role_name: str = DEFAULT_ROLE,
        coach_extra_rule: str = DEFAULT_EXTRA_RULE,
        coach_max_turns: int = DEFAULT_MAX_TURNS,
        max_confirm_turns: int = DEFAULT_MAX_CONFIRM_TURNS,
        max_orchestrator_turns: int = DEFAULT_MAX_ORCHESTRATOR_TURNS,
        direct_to_coach_confidence: float = DIRECT_TO_COACH_CONFIDENCE,
    ) -> DiagnosisFlowSession:
        return DiagnosisFlowSession(
            problem_text=problem_text,
            reference_answer=reference_answer,
            student_profile=student_profile,
            student_memory_profile=student_memory_profile,
            diagnosis_role_name=diagnosis_role_name,
            confirmation_role_name=confirmation_role_name,
            coach_role_name=coach_role_name,
            coach_extra_rule=coach_extra_rule,
            coach_max_turns=max(1, coach_max_turns),
            max_confirm_turns=max(1, max_confirm_turns),
            max_orchestrator_turns=max(2, max_orchestrator_turns),
            direct_to_coach_confidence=max(0.0, min(direct_to_coach_confidence, 1.0)),
            messages=[
                {
                    "role": "system",
                    "content": build_confirmation_system_instruction(
                        confirmation_role_name
                    ),
                }
            ],
        )

    def start(self, student_answer: str, *, session: DiagnosisFlowSession) -> OrchestratorResult:
        if session.done:
            raise RuntimeError(f"Flow already ended: {session.stop_reason}")

        session.orchestrator_turn_index = 1
        session.original_student_answer = student_answer.strip()
        session.latest_student_reply = student_answer.strip()
        return self._diagnose_and_route(student_answer, session=session)

    def handle_student_reply(
        self,
        student_reply: str,
        *,
        session: DiagnosisFlowSession,
    ) -> OrchestratorResult:
        if session.done:
            raise RuntimeError(f"Flow already ended: {session.stop_reason}")
        if session.phase != "await_confirmation":
            raise RuntimeError(f"Flow is not awaiting confirmation: {session.phase}")
        if session.pending_diagnosis is None or session.pending_question is None:
            raise RuntimeError("Missing pending diagnosis state for confirmation.")

        session.orchestrator_turn_index += 1
        session.latest_student_reply = student_reply.strip()
        analysis = self.confirmation_analyzer.analyze(
            student_reply,
            session=session,
            diagnosis=session.pending_diagnosis,
            confirmation_question=session.pending_question,
        )
        session.messages.extend(
            [
                {"role": "assistant", "content": session.pending_question},
                {"role": "user", "content": student_reply.strip()},
                {
                    "role": "assistant",
                    "content": json.dumps(analysis.as_dict(), ensure_ascii=False),
                },
            ]
        )
        session.confirm_turn_index += 1

        if analysis.stance == "confirm":
            return self._enter_coach(
                session.pending_diagnosis,
                session=session,
                confirmation_analysis=analysis,
            )

        if self._should_enter_coach_after_fallback_confirmation(
            session.pending_diagnosis,
            analysis,
            session=session,
        ):
            return self._enter_coach(
                session.pending_diagnosis,
                session=session,
                confirmation_analysis=analysis,
                forced=True,
            )

        if (
            analysis.source != "fallback_heuristic"
            and analysis.stance == "reject"
            and analysis.has_new_reason
            and session.orchestrator_turn_index < session.max_orchestrator_turns
        ):
            return self._diagnose_and_route(
                self._build_rediagnosis_input(session, analysis),
                session=session,
                confirmation_analysis=analysis,
            )

        if (
            session.confirm_turn_index >= session.max_confirm_turns
            or session.orchestrator_turn_index >= session.max_orchestrator_turns
        ):
            return self._enter_coach(
                session.pending_diagnosis,
                session=session,
                confirmation_analysis=analysis,
                forced=True,
            )

        session.pending_question = self._build_confirmation_question(
            session.pending_diagnosis,
            retry=True,
        )
        session.phase = "await_confirmation"
        session.stop_reason = "continue_confirmation"
        return OrchestratorResult(
            action="continue_confirmation",
            content=session.pending_question,
            diagnosis=session.pending_diagnosis,
            confirmation_analysis=analysis,
            done=False,
            stop_reason=session.stop_reason,
            coach_session=None,
        )

    def _diagnose_and_route(
        self,
        diagnosis_input: str,
        *,
        session: DiagnosisFlowSession,
        confirmation_analysis: ConfirmationReplyAnalysis | None = None,
    ) -> OrchestratorResult:
        diagnosis_session = self.diagnosis_agent.create_session(
            problem_text=session.problem_text,
            reference_answer=session.reference_answer,
            student_profile=session.student_profile,
            role_name=session.diagnosis_role_name,
            coach_max_turns=session.coach_max_turns,
        )
        diagnosis = self.diagnosis_agent.diagnose(diagnosis_input, session=diagnosis_session)
        session.diagnosis_history.append(diagnosis)
        session.pending_diagnosis = diagnosis

        if self._should_enter_coach_directly(diagnosis, session=session):
            return self._enter_coach(
                diagnosis,
                session=session,
                confirmation_analysis=confirmation_analysis,
            )

        if (
            session.confirm_turn_index >= session.max_confirm_turns
            or session.orchestrator_turn_index >= session.max_orchestrator_turns
        ):
            return self._enter_coach(
                diagnosis,
                session=session,
                confirmation_analysis=confirmation_analysis,
                forced=True,
            )

        session.pending_question = self._build_confirmation_question(diagnosis)
        session.phase = "await_confirmation"
        session.stop_reason = "await_confirmation"
        return OrchestratorResult(
            action="ask_confirmation",
            content=session.pending_question,
            diagnosis=diagnosis,
            confirmation_analysis=confirmation_analysis,
            done=False,
            stop_reason=session.stop_reason,
            coach_session=None,
        )

    def _should_enter_coach_directly(
        self,
        diagnosis: DiagnosisResult,
        *,
        session: DiagnosisFlowSession,
    ) -> bool:
        if diagnosis.confidence < session.direct_to_coach_confidence:
            return False
        if self._must_confirm_before_coach(diagnosis.error_type):
            return False
        return True

    def _should_enter_coach_after_fallback_confirmation(
        self,
        diagnosis: DiagnosisResult,
        analysis: ConfirmationReplyAnalysis,
        *,
        session: DiagnosisFlowSession,
    ) -> bool:
        if analysis.source != "fallback_heuristic":
            return False
        if diagnosis.confidence >= session.direct_to_coach_confidence:
            return True
        return session.orchestrator_turn_index >= session.max_orchestrator_turns

    def _must_confirm_before_coach(self, error_type: ErrorType) -> bool:
        return error_type in {
            ErrorType.MISSING_STRATEGY,
            ErrorType.CONCEPT_GAP,
        }

    def _enter_coach(
        self,
        diagnosis: DiagnosisResult,
        *,
        session: DiagnosisFlowSession,
        confirmation_analysis: ConfirmationReplyAnalysis | None,
        forced: bool = False,
    ) -> OrchestratorResult:
        coach_initial_student_reply = (
            session.latest_student_reply.strip()
            or diagnosis.student_answer.strip()
            or session.original_student_answer.strip()
        )
        coach_handoff = self._build_coach_handoff(
            session,
            diagnosis,
            confirmation_analysis,
        )
        coach_session = diagnosis.build_coach_session(
            self.coach_agent,
            student_profile=session.student_profile,
            student_memory_profile=session.student_memory_profile,
            role_name=session.coach_role_name,
            extra_rule=session.coach_extra_rule,
            max_turns=session.coach_max_turns,
            initial_student_reply=coach_initial_student_reply,
            handoff_context=coach_handoff,
            diagnosis_strategy_hint=diagnosis.coach_strategy,
        )
        session.coach_session = coach_session
        session.phase = "coach_ready"
        session.done = True
        session.stop_reason = "enter_coach_after_confirmation" if not forced else "enter_coach_after_max_confirm"

        return OrchestratorResult(
            action="enter_coach",
            content=(
                "已完成错因确认，进入 coach。"
                if not forced
                else "确认轮次已用尽，按当前最佳诊断进入 coach。"
            ),
            diagnosis=diagnosis,
            confirmation_analysis=confirmation_analysis,
            done=True,
            stop_reason=session.stop_reason,
            coach_session=coach_session,
            coach_initial_student_reply=coach_initial_student_reply,
            coach_handoff=coach_handoff,
        )

    def _build_confirmation_question(
        self,
        diagnosis: DiagnosisResult,
        *,
        retry: bool = False,
    ) -> str:
        base_questions = {
            ErrorType.MISREADING: "我现在更怀疑你是把题目条件、要求或求解对象看偏了。你的卡点更接近这个，还是你其实懂题意但卡在别的地方？",
            ErrorType.MISSING_STRATEGY: "我现在更怀疑你不是不会知识点，而是不知道第一步该抓哪个中间量。你的卡点更接近这个吗？如果不是，请直接说你真正卡在哪。",
            ErrorType.CALCULATION: "我现在更怀疑你主要不是不会方法，而是运算、移项或代入这一步不稳。你的问题更接近这个吗？如果不是，请直接补充真正原因。",
            ErrorType.CONCEPT_GAP: "我现在更怀疑你是相关概念或公式本身没有掌握稳。你的问题更接近这个吗？如果不是，请直接说你其实卡在哪里。",
            ErrorType.CARELESS: "我现在更怀疑你本来会做，但容易在符号、抄写或检查上出错。你的问题更接近这个吗？如果不是，请直接说真正原因。",
        }
        if retry:
            return (
                "我还不能稳定判断。请你不要只说对或不对，直接用一句话说清："
                "你真正卡住的是题意、第一步、概念公式，还是计算执行？"
            )
        return base_questions[diagnosis.error_type]

    def _build_rediagnosis_input(
        self,
        session: DiagnosisFlowSession,
        analysis: ConfirmationReplyAnalysis,
    ) -> str:
        return (
            f"学生原始回答：{session.original_student_answer.strip() or '无'}\n"
            f"上一轮候选错因：{session.pending_diagnosis.error_type.value if session.pending_diagnosis else 'unknown'}\n"
            f"学生对该判断的反馈：{session.latest_student_reply.strip() or '无'}\n"
            f"提炼出的新理由：{analysis.extracted_reason.strip() or session.latest_student_reply.strip() or '无'}"
        )

    def _build_coach_handoff(
        self,
        session: DiagnosisFlowSession,
        diagnosis: DiagnosisResult,
        confirmation_analysis: ConfirmationReplyAnalysis | None,
    ) -> str:
        confirmation_summary = "无确认分析。"
        if confirmation_analysis is not None:
            confirmation_summary = (
                f"确认态度：{confirmation_analysis.stance}；"
                f"是否提供新理由：{'是' if confirmation_analysis.has_new_reason else '否'}；"
                f"确认判断理由：{confirmation_analysis.reason}"
            )

        latest_reply = session.latest_student_reply.strip() or "无"
        original_reply = session.original_student_answer.strip() or "无"
        first_turn_goal = self._build_first_turn_goal(
            diagnosis,
            confirmation_analysis,
            latest_reply,
        )
        return (
            "【诊断交接摘要】\n"
            f"原始学生回答：{original_reply}\n"
            f"进入 coach 前学生最新回复：{latest_reply}\n"
            f"最终错因：{diagnosis.error_type.value}\n"
            f"最终诊断理由：{diagnosis.reason}\n"
            f"诊断阶段建议策略：{diagnosis.coach_strategy.as_prompt_block()}\n"
            f"确认阶段结论：{confirmation_summary}\n"
            f"第一轮 coach 目标：{first_turn_goal}"
        )

    def _build_first_turn_goal(
        self,
        diagnosis: DiagnosisResult,
        confirmation_analysis: ConfirmationReplyAnalysis | None,
        latest_reply: str,
    ) -> str:
        if diagnosis.error_type == ErrorType.MISSING_STRATEGY:
            if confirmation_analysis is not None and confirmation_analysis.stance == "confirm":
                return (
                    "不要重复学生已经会的代换或已说出的第一步，只聚焦他不会选下一步方法这一真实卡点，"
                    "先追问一个最小判断问题。"
                )
            return "先确认学生真正卡住的是哪一个中间目标，再只追问一个最小问题。"

        if diagnosis.error_type == ErrorType.CALCULATION:
            return "不要重讲整题，只把学生最可能算错的当前一步单独拎出来核对。"
        if diagnosis.error_type == ErrorType.MISREADING:
            return "先拉回题意或限制条件，不要直接展开完整解法。"
        if diagnosis.error_type == ErrorType.CONCEPT_GAP:
            return "先补当前题真正缺的概念，再立刻让学生把概念放回题目。"
        if diagnosis.error_type == ErrorType.CARELESS:
            return "先指出最该检查的一处，再让学生自己复核那一步。"
        if latest_reply:
            return "优先承接学生最新回复暴露出的真实卡点，不要回退到更早回答。"
        return "优先承接最新上下文，只推进当前题最缺的一步。"
