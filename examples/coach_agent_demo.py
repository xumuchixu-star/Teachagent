from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coach_agent import ErrorType, FoundryCoachAgent, diagnose_environment

ANALYSIS_SOURCE_LABELS = {
    "ai_tool_pydantic_parse": "官方 structured outputs + Pydantic parse",
    "ai_tool_json_mode": "json_object 模式成功",
    "ai_tool_text_json_validated": "普通文本 JSON，被 Pydantic 校验通过",
    "ai_tool_text_json_basic": "普通文本 JSON，基础 JSON 解析通过",
    "fallback_heuristic": "本地 heuristic fallback",
}


def main() -> None:
    print(diagnose_environment())

    agent = FoundryCoachAgent()
    session = agent.create_session(
        problem_text="已知 x+2=5，求 3x-1 的值。",
        error_type=ErrorType.MISSING_STRATEGY,
        student_profile="学生会基础方程，但遇到组合表达式时不知道先算什么。",
        max_turns=3,
    )

    first = agent.reply("我不会。", session=session)
    print("=== Turn 1 ===")
    print(first.content)
    print("quality:", first.reply_quality.value)
    print("analysis:", first.reply_analysis.source, first.reply_analysis.reason)
    print("analysis_label:", ANALYSIS_SOURCE_LABELS.get(first.reply_analysis.source, "unknown"))
    print("mode:", first.strategy.mode.value)
    print("stop_reason:", first.stop_reason)

    if not first.done:
        second = agent.reply("是不是先算 x=3？", session=session)
        print("\n=== Turn 2 ===")
        print(second.content)
        print("quality:", second.reply_quality.value)
        print("analysis:", second.reply_analysis.source, second.reply_analysis.reason)
        print("analysis_label:", ANALYSIS_SOURCE_LABELS.get(second.reply_analysis.source, "unknown"))
        print("mode:", second.strategy.mode.value)
        print("stop_reason:", second.stop_reason)


def run_turn(student_reply, stream=False):
    if stream:
        result = agent.print_stream_reply(student_reply, session=session)
    else:
        result = agent.reply(student_reply, session=session)
        print(result.content)

    print("student_reply:", student_reply)
    print("quality:", result.reply_quality.value)
    print("understands:", result.reply_analysis.understands)
    print("analysis_source:", result.reply_analysis.source)
    print("analysis_reason:", result.reply_analysis.reason)
    print("mode:", result.strategy.mode.value)
    print("turn_index:", result.turn_index)
    print("max_turns:", session.max_turns)
    print("done:", result.done)
    print("stop_reason:", result.stop_reason)
    print("-" * 40)
    return result


if __name__ == "__main__":
    main()
