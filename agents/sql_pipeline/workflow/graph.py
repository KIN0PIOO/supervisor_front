"""단일 마이그레이션 재시도 시도에 대한 LangGraph 정의.

START
  -> tobe_generation.generate
      -> non-SELECT: mark_non_select -> END
      -> SELECT:     tobe_generation.validate
                       -> PASS: sql_tuning.run -> END
                       -> FAIL: END
"""

from typing import Literal

from langgraph.graph import END, START, StateGraph

from agents.sql_pipeline.workflow.state import MigrationGraphState


def build_migration_workflow(generation_agent, tuning_agent):
    def tobe_generation_generate_node(state: MigrationGraphState) -> MigrationGraphState:
        execution = state["execution"]
        generation_agent.generate(execution)
        return {"execution": execution, "terminal_action": None}

    def tobe_generation_validate_node(state: MigrationGraphState) -> MigrationGraphState:
        execution = state["execution"]
        generation_agent.validate(execution)
        return {"execution": execution, "terminal_action": None}

    def mark_non_select_node(state: MigrationGraphState) -> MigrationGraphState:
        execution = state["execution"]
        return {"execution": execution, "terminal_action": "persist_non_select"}

    def sql_tuning_run_node(state: MigrationGraphState) -> MigrationGraphState:
        execution = state["execution"]
        tuning_agent.run(execution)
        return {"execution": execution, "terminal_action": tuning_agent.name}

    graph = StateGraph(MigrationGraphState)
    graph.add_node("tobe_generation.generate", tobe_generation_generate_node)
    graph.add_node("tobe_generation.validate", tobe_generation_validate_node)
    graph.add_node("mark_non_select", mark_non_select_node)
    graph.add_node("sql_tuning.run", sql_tuning_run_node)

    graph.add_edge(START, "tobe_generation.generate")
    graph.add_conditional_edges(
        "tobe_generation.generate",
        route_after_generation,
        {
            "validate_generation": "tobe_generation.validate",
            "mark_non_select": "mark_non_select",
        },
    )
    graph.add_conditional_edges(
        "tobe_generation.validate",
        route_after_validation,
        {
            "tune_sql": "sql_tuning.run",
            "end": END,
        },
    )
    graph.add_edge("mark_non_select", END)
    graph.add_edge("sql_tuning.run", END)
    return graph.compile()


def route_after_generation(state: MigrationGraphState) -> Literal["validate_generation", "mark_non_select"]:
    execution = state["execution"]
    tag_kind = (execution.job.tag_kind or "").strip().upper()
    if tag_kind != "SELECT":
        return "mark_non_select"
    return "validate_generation"


def route_after_validation(state: MigrationGraphState) -> Literal["tune_sql", "end"]:
    execution = state["execution"]
    if execution.status == "PASS":
        return "tune_sql"
    return "end"
