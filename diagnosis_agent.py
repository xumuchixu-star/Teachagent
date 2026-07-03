from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from typing import Any, Optional

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError:
    BaseModel = Field = ValidationError = None

from coach_agent import (
    DEFAULT_EXTRA_RULE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MAX_TURNS,
    DEFAULT_ROLE,
    MODEL_DEPLOYMENT,
    PROJECT_ENDPOINT,
    CoachStrategy,
    ErrorType,
    FoundryCoachAgent,
    ReplyQuality,
    ensure_azure_cli_on_path,
    get_coach_strategy,
    normalize_error_type,
    supports_structured_outputs,
)


DIAGNOSIS_AGENT_VERSION = "2026-06-17-fixed-problem-diagnosis"
DEFAULT_DIAGNOSIS_ROLE = "数学错因诊断助手"
DEFAULT_DIAGNOSIS_MAX_TOKENS = int(
    os.getenv("DIAGNOSIS_AGENT_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
)


@dataclass
class DiagnosisSession:
    problem_text: str
    reference_answer: str
    student_profile: str = ""
    role_name: str = DEFAULT_DIAGNOSIS_ROLE
    ocr_source: str = "fixed_text"
    coach_max_turns: int = DEFAULT_MAX_TURNS
    messages: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class DiagnosisResult:
    problem_text: str
    reference_answer: str
    student_answer: str
    student_profile: str
    error_type: ErrorType
    confidence: float
    reason: str
    evidence: str
    coach_strategy: CoachStrategy
    source: str = "fallback_heuristic"

    def as_dict(self) -> dict[str, Any]:
        return {
            "problem_text": self.problem_text,
            "reference_answer": self.reference_answer,
            "student_answer": self.student_answer,
            "student_profile": self.student_profile,
            "error_type": self.error_type.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
            "coach_mode": self.coach_strategy.mode.value,
            "coach_trap": self.coach_strategy.trap,
            "coach_prompt": self.coach_strategy.prompt,
            "source": self.source,
        }

    def build_coach_session(
        self,
        coach_agent: FoundryCoachAgent,
        *,
        student_profile: str | None = None,
        student_memory_profile: dict[str, Any] | None = None,
        role_name: str = DEFAULT_ROLE,
        extra_rule: str = DEFAULT_EXTRA_RULE,
        max_turns: int = DEFAULT_MAX_TURNS,
        initial_student_reply: str = "",
        handoff_context: str = "",
        diagnosis_strategy_hint: CoachStrategy | None = None,
    ):
        safe_error_type = normalize_error_type(self.error_type)
        safe_problem_text = self.problem_text.strip() or "未提供题目。"
        safe_profile = (
            student_profile if student_profile is not None else self.student_profile
        )
        return coach_agent.create_session(
            problem_text=safe_problem_text,
            error_type=safe_error_type,
            role_name=role_name,
            student_profile=safe_profile,
            student_memory_profile=student_memory_profile,
            extra_rule=extra_rule,
            max_turns=max_turns,
            initial_student_reply=initial_student_reply,
            handoff_context=handoff_context,
            diagnosis_strategy_hint=diagnosis_strategy_hint or self.coach_strategy,
        )


@dataclass(frozen=True)
class ParsedDiagnosisPayload:
    error_type: ErrorType
    confidence: float
    reason: str
    evidence: str
    source: str


if BaseModel is not None:

    class DiagnosisSchema(BaseModel):
        error_type: ErrorType = Field(
            description=(
                "学生当前这道题的主要错误类型，只能从 "
                "concept_gap、misreading、calculation、missing_strategy、careless 中选择一个。"
            )
        )
        confidence: float = Field(
            description="本次诊断置信度，范围 0 到 1。", ge=0.0, le=1.0
        )
        reason: str = Field(description="一句中文理由，说明为什么判成这个错因。")
        evidence: str = Field(
            description="一句中文证据，指出学生回答里的具体线索。"
        )

else:
    DiagnosisSchema = None


def diagnosis_environment() -> dict[str, str | None]:
    ensure_azure_cli_on_path()
    return {
        "diagnosis_agent_version": DIAGNOSIS_AGENT_VERSION,
        "az_path": os.environ.get("PATH"),
        "project_endpoint": PROJECT_ENDPOINT,
        "model_deployment": MODEL_DEPLOYMENT,
        "structured_outputs_supported": str(
            supports_structured_outputs(MODEL_DEPLOYMENT)
        ),
    }


def fixed_ocr_read(problem_text: str) -> str:
    """Placeholder for OCR. Current MVP keeps the problem text fixed."""
    return problem_text.strip()


def build_diagnosis_system_instruction(role_name: str = DEFAULT_DIAGNOSIS_ROLE) -> str:
    return f"""
你是{role_name}，负责把学生当前这道题的主要错因归入固定标签。

执行规则：
1. 只选择一个主错因，不要同时输出多个。
2. 必须综合题目、标准答案和学生回答，不要只看关键词。
3. 重点区分：
   - concept_gap：概念、定义、公式不会或混淆。
   - misreading：看错题意、忽略限制条件、求错对象。
   - calculation：思路方向基本对，但算错、移项错、代入算错。
   - missing_strategy：知道局部知识，但不知道先算什么、缺少中间目标。
   - careless：本来会做，但出现抄写、符号、漏步、检查不到位。
4. 你只能输出一个 JSON 对象，第一字符必须是 {{，最后字符必须是 }}。
5. 不要输出 ```json，不要输出“下面是结果”、不要输出任何解释、前缀或结尾说明。
6. JSON 必须严格包含 error_type、confidence、reason、evidence 四个字段，不能多也不能少。
""".strip()


def get_diagnosis_schema_text() -> str:
    if DiagnosisSchema is None:
        return json.dumps(
            {
                "type": "object",
                "properties": {
                    "error_type": {
                        "type": "string",
                        "enum": [item.value for item in ErrorType],
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["error_type", "confidence", "reason", "evidence"],
                "additionalProperties": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(
        DiagnosisSchema.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )


def build_diagnosis_prompt(session: DiagnosisSession, student_answer: str) -> str:
    schema_text = get_diagnosis_schema_text()
    return f"""
请根据题目、标准答案和学生回答，判断学生这道题的主要错因。

输出要求：
- 你必须只输出一个合法 JSON 对象。
- 第一字符必须是 {{，最后字符必须是 }}。
- 不要输出 Markdown 代码块，不要输出任何解释、标题、前缀或附加文字。
- error_type 只能填写以下之一：
  {", ".join(item.value for item in ErrorType)}
- confidence 是 0 到 1 的小数。
- reason 要解释主错因。
- evidence 要指出学生回答中的关键证据。
- 如果学生已经给出了局部正确步骤，但不会继续，优先考虑 missing_strategy，不要误判为空回答。

JSON Schema：
{schema_text}

【题目】
{fixed_ocr_read(session.problem_text)}

【标准答案】
{session.reference_answer.strip() or "未提供标准答案。"}

【学生画像】
{session.student_profile.strip() or "无额外学生画像。"}

【学生回答】
{student_answer.strip() or "无回答"}
""".strip()


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


def parse_diagnosis_payload(raw_text: str) -> ParsedDiagnosisPayload | None:
    json_text = extract_json_object(raw_text)
    if json_text is None:
        return None

    if DiagnosisSchema is not None:
        try:
            parsed = DiagnosisSchema.model_validate_json(json_text)
            return ParsedDiagnosisPayload(
                error_type=normalize_error_type(parsed.error_type),
                confidence=float(parsed.confidence),
                reason=parsed.reason.strip() or "模型未给出诊断理由。",
                evidence=parsed.evidence.strip() or "模型未给出诊断证据。",
                source="ai_tool_text_json_validated",
            )
        except ValidationError:
            pass

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None

    try:
        error_type = normalize_error_type(str(data["error_type"]).strip())
    except (KeyError, ValueError):
        return None

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))

    reason = str(data.get("reason", "")).strip() or "模型未给出诊断理由。"
    evidence = str(data.get("evidence", "")).strip() or "模型未给出诊断证据。"
    return ParsedDiagnosisPayload(
        error_type=error_type,
        confidence=confidence,
        reason=reason,
        evidence=evidence,
        source="ai_tool_text_json_basic",
    )


def build_diagnosis_result(
    session: DiagnosisSession,
    student_answer: str,
    error_type: ErrorType,
    confidence: float,
    reason: str,
    evidence: str,
    *,
    source: str,
) -> DiagnosisResult:
    safe_problem_text = session.problem_text.strip() or "未提供题目。"
    safe_reference_answer = session.reference_answer.strip() or "未提供标准答案。"
    safe_student_answer = student_answer.strip() or "无回答"
    safe_profile = session.student_profile.strip()
    safe_error_type = normalize_error_type(error_type)
    safe_confidence = max(0.0, min(float(confidence), 1.0))
    safe_reason = reason.strip() or "未提供诊断理由。"
    safe_evidence = evidence.strip() or "未提供诊断证据。"
    safe_source = source.strip() or "fallback_heuristic"

    strategy = get_coach_strategy(
        safe_error_type,
        ReplyQuality.EMPTY,
        turn_index=0,
        total_turns=session.coach_max_turns,
        understands=False,
    )
    return DiagnosisResult(
        problem_text=safe_problem_text,
        reference_answer=safe_reference_answer,
        student_answer=safe_student_answer,
        student_profile=safe_profile,
        error_type=safe_error_type,
        confidence=safe_confidence,
        reason=safe_reason,
        evidence=safe_evidence,
        coach_strategy=strategy,
        source=safe_source,
    )


def heuristic_diagnose_error_type(
    student_answer: str,
) -> tuple[ErrorType, float, str, str]:
    normalized = student_answer.strip().lower()
    if not normalized or any(
        marker in normalized for marker in ("不会", "不知道", "没思路", "不清楚", "忘了")
    ):
        return (
            ErrorType.MISSING_STRATEGY,
            0.35,
            "学生没有给出可执行的第一步，更像缺少切入路径。",
            "学生回答为空或直接表示不会。",
        )

    if any(
        marker in normalized
        for marker in ("看错", "题意", "条件", "求的是", "漏看", "审题")
    ):
        return (
            ErrorType.MISREADING,
            0.4,
            "学生更像忽略了题目条件或求解目标。",
            "学生回答中出现了审题、条件或求解对象相关线索。",
        )

    if any(
        marker in normalized
        for marker in ("不知道先", "先算什么", "怎么开始", "第一步", "卡住")
    ):
        return (
            ErrorType.MISSING_STRATEGY,
            0.42,
            "学生知道局部信息，但不知道该先建立哪个中间步骤。",
            "学生回答直接暴露出不会起步或缺少中间目标。",
        )

    if any(
        marker in normalized for marker in ("公式", "定义", "概念", "不会用", "不懂")
    ):
        return (
            ErrorType.CONCEPT_GAP,
            0.4,
            "学生更像没有掌握所需概念或公式。",
            "学生回答直接提到了公式、定义或概念不会用。",
        )

    if any(
        marker in normalized for marker in ("算错", "移项", "代入", "解得", "结果")
    ):
        return (
            ErrorType.CALCULATION,
            0.4,
            "学生像是已经开始运算，但执行链条里出了错。",
            "学生回答包含明确计算动作，更像计算或变形失误。",
        )

    return (
        ErrorType.CONCEPT_GAP,
        0.3,
        "本地规则无法稳定细分，保守按概念或方法未掌握处理。",
        "学生回答没有提供足够线索进行更精确分类。",
    )


class FoundryDiagnosisAgent:
    """Notebook-friendly DiagnoseAgent backed by Azure AI Foundry chat completions."""

    def __init__(
        self,
        project_endpoint: str = PROJECT_ENDPOINT,
        model_deployment: str = MODEL_DEPLOYMENT,
        *,
        use_default_credential: bool = False,
        use_ai_diagnoser: bool = True,
        max_tokens: int = DEFAULT_DIAGNOSIS_MAX_TOKENS,
        temperature: float = 0.0,
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
        self.use_ai_diagnoser = use_ai_diagnoser
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.last_result: DiagnosisResult | None = None

    def _finalize_result(
        self,
        result: DiagnosisResult,
        *,
        session: DiagnosisSession,
        assistant_content: str,
    ) -> DiagnosisResult:
        safe_result = build_diagnosis_result(
            session,
            result.student_answer,
            result.error_type,
            result.confidence,
            result.reason,
            result.evidence,
            source=result.source,
        )
        session.messages = session.messages[:1] + [
            {"role": "user", "content": build_diagnosis_prompt(session, safe_result.student_answer)},
            {"role": "assistant", "content": assistant_content},
        ]
        self.last_result = safe_result
        return safe_result

    def create_session(
        self,
        *,
        problem_text: str,
        reference_answer: str,
        student_profile: str = "",
        role_name: str = DEFAULT_DIAGNOSIS_ROLE,
        ocr_source: str = "fixed_text",
        coach_max_turns: int = DEFAULT_MAX_TURNS,
    ) -> DiagnosisSession:
        system_prompt = build_diagnosis_system_instruction(role_name)
        return DiagnosisSession(
            problem_text=problem_text,
            reference_answer=reference_answer,
            student_profile=student_profile,
            role_name=role_name,
            ocr_source=ocr_source,
            coach_max_turns=max(1, coach_max_turns),
            messages=[{"role": "system", "content": system_prompt}],
        )

    def diagnose(
        self,
        student_answer: str,
        *,
        session: DiagnosisSession,
        max_tokens: int | None = None,
    ) -> DiagnosisResult:
        fallback_type, fallback_confidence, fallback_reason, fallback_evidence = (
            heuristic_diagnose_error_type(student_answer)
        )
        fallback = build_diagnosis_result(
            session,
            student_answer,
            fallback_type,
            fallback_confidence,
            fallback_reason,
            fallback_evidence,
            source="fallback_heuristic",
        )

        if not self.use_ai_diagnoser:
            self.last_result = fallback
            return fallback

        prompt = build_diagnosis_prompt(session, student_answer)
        messages = session.messages[:1] + [{"role": "user", "content": prompt}]

        try:
            if supports_structured_outputs(self.model_deployment):
                result = self._diagnose_structured(student_answer, session=session)
                if result is not None:
                    return self._finalize_result(
                        result,
                        session=session,
                        assistant_content=json.dumps(
                            result.as_dict(),
                            ensure_ascii=False,
                        ),
                    )

            result = self._diagnose_json_mode(student_answer, session=session)
            if result is not None:
                return self._finalize_result(
                    result,
                    session=session,
                    assistant_content=json.dumps(
                        result.as_dict(),
                        ensure_ascii=False,
                    ),
                )

            raw = self._complete(messages, max_tokens=max_tokens)
            parsed = parse_diagnosis_payload(raw)
            if parsed is not None:
                result = build_diagnosis_result(
                    session,
                    student_answer,
                    parsed.error_type,
                    parsed.confidence,
                    parsed.reason,
                    parsed.evidence,
                    source=parsed.source,
                )
                return self._finalize_result(
                    result,
                    session=session,
                    assistant_content=raw,
                )
        except Exception as exc:
            fallback = replace(
                fallback,
                reason=f"AI 诊断调用失败，已使用本地 fallback：{type(exc).__name__}",
            )

        return self._finalize_result(
            fallback,
            session=session,
            assistant_content=json.dumps(fallback.as_dict(), ensure_ascii=False),
        )

    def _diagnose_structured(
        self,
        student_answer: str,
        *,
        session: DiagnosisSession,
    ) -> DiagnosisResult | None:
        if DiagnosisSchema is None:
            return None

        beta_chat = getattr(getattr(self.client, "beta", None), "chat", None)
        completions = getattr(beta_chat, "completions", None)
        parse_fn = getattr(completions, "parse", None)
        if parse_fn is None:
            return None

        prompt = build_diagnosis_prompt(session, student_answer)
        response = parse_fn(
            model=self.model_deployment,
            messages=[
                {"role": "system", "content": session.messages[0]["content"]},
                {
                    "role": "system",
                    "content": "你必须严格输出与 response_format 完全匹配的对象，不能输出额外文本。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=220,
            temperature=0.0,
            response_format=DiagnosisSchema,
        )

        message = response.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            return None

        return build_diagnosis_result(
            session,
            student_answer,
            parsed.error_type,
            float(parsed.confidence),
            parsed.reason.strip() or "模型未给出诊断理由。",
            parsed.evidence.strip() or "模型未给出诊断证据。",
            source="ai_tool_pydantic_parse",
        )

    def _diagnose_json_mode(
        self,
        student_answer: str,
        *,
        session: DiagnosisSession,
    ) -> DiagnosisResult | None:
        prompt = build_diagnosis_prompt(session, student_answer)
        response = self.client.chat.completions.create(
            model=self.model_deployment,
            messages=[
                {"role": "system", "content": session.messages[0]["content"]},
                {
                    "role": "system",
                    "content": "你必须只输出一个合法 JSON 对象，不能输出任何解释、前后缀或 Markdown。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=220,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = parse_diagnosis_payload(raw)
        if parsed is None:
            return None

        return build_diagnosis_result(
            session,
            student_answer,
            parsed.error_type,
            parsed.confidence,
            parsed.reason,
            parsed.evidence,
            source="ai_tool_json_mode",
        )

    def _complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
    ) -> str:
        response = self.client.chat.completions.create(
            model=self.model_deployment,
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
        )
        return (response.choices[0].message.content or "").strip()


def notebook_diagnosis_demo() -> DiagnosisResult:
    agent = FoundryDiagnosisAgent()
    session = agent.create_session(
        problem_text="已知 x+2=5，求 3x-1 的值。",
        reference_answer="先由 x+2=5 解得 x=3，再代入 3x-1=8。",
        student_profile="学生会基础方程，但经常不知道先算什么。",
    )
    return agent.diagnose("我把 x+2=5 直接看成 x=5，所以后面不会了。", session=session)


if __name__ == "__main__":
    print(diagnosis_environment())
    result = notebook_diagnosis_demo()
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
