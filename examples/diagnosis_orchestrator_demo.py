import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coach_agent import FoundryCoachAgent
from diagnosis_orchestrator import (
    FoundryDiagnosisOrchestrator,
    orchestrator_environment,
)


def main() -> None:
    print(orchestrator_environment())

    orchestrator = FoundryDiagnosisOrchestrator(
        coach_agent=FoundryCoachAgent(),
    )
    flow_session = orchestrator.create_session(
        problem_text="已知 x+2=5，求 3x-1 的值。",
        reference_answer="先由 x+2=5 解得 x=3，再代入 3x-1=8。",
        student_profile="学生会基础方程，但遇到组合表达式时常不知道第一步。",
        coach_max_turns=4,
        max_confirm_turns=2,
        direct_to_coach_confidence=0.95,
    )

    student_answer = "我知道要先求 x，但是不知道为什么先算这个。"
    first = orchestrator.start(student_answer, session=flow_session)

    print("=== Orchestrator Turn 1 ===")
    print("action:", first.action)
    print("content:", first.content)
    if first.diagnosis is not None:
        print("diagnosis:", json.dumps(first.diagnosis.as_dict(), ensure_ascii=False, indent=2))

    if first.action != "enter_coach":
        second = orchestrator.handle_student_reply(
            "不是看错题，我其实知道要求什么，就是不知道第一步为什么先解 x。",
            session=flow_session,
        )
        print("\n=== Orchestrator Turn 2 ===")
        print("action:", second.action)
        print("content:", second.content)
        if second.confirmation_analysis is not None:
            print(
                "confirmation_analysis:",
                json.dumps(second.confirmation_analysis.as_dict(), ensure_ascii=False, indent=2),
            )
        if second.diagnosis is not None:
            print("diagnosis:", json.dumps(second.diagnosis.as_dict(), ensure_ascii=False, indent=2))

        final_result = second
    else:
        final_result = first

    if final_result.action == "enter_coach" and final_result.coach_session is not None:
        coach = orchestrator.coach_agent
        coach_result = coach.reply(student_answer, session=final_result.coach_session)
        print("\n=== Coach Turn 1 ===")
        print(coach_result.content)
        print("quality:", coach_result.reply_quality.value)
        print("mode:", coach_result.strategy.mode.value)
        print("analysis_source:", coach_result.reply_analysis.source)
        print("stop_reason:", coach_result.stop_reason)


if __name__ == "__main__":
    main()
