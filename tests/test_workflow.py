"""Workflow tests — wired in Phase 2.

Placeholder tests assert the import graph stays consistent so CI doesn't pass
with a silently broken module.
"""

from __future__ import annotations


def test_event_imports():
    from focusparse.pipeline.events import (
        AnswerEvent,
        EvidenceEvent,
        PagesEvent,
        PlanEvent,
        QuestionEvent,
        RegionsEvent,
        VerdictEvent,
    )

    assert QuestionEvent.__name__ == "QuestionEvent"
    assert all(
        e is not None
        for e in (PlanEvent, PagesEvent, RegionsEvent, EvidenceEvent, AnswerEvent, VerdictEvent)
    )


def test_workflow_stub_importable():
    from focusparse.pipeline.workflow import FocusWorkflow, SimpleBaselineAgent, WorkflowResult

    assert FocusWorkflow.__name__ == "FocusWorkflow"
    assert SimpleBaselineAgent.__name__ == "SimpleBaselineAgent"
    assert WorkflowResult is not None
