"""Tool logging preserves execution and keeps argument previews bounded."""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from agent_framework import FunctionInvocationContext, tool
from pydantic import BaseModel
from simassist.agents.orchestrator import ToolTelemetry, _tool_arguments_preview


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_tool_call_logs_arguments_duration_and_outcome(caplog, outcome):
    @tool
    def inspect_uploaded_file(file_id: str) -> str:
        return '{"ok":true}'

    composition = SimpleNamespace(request_id="request-123", invoked=[])
    context = FunctionInvocationContext(
        function=inspect_uploaded_file, arguments={"file_id": "file-456"}
    )
    failure = (
        asyncio.CancelledError()
        if outcome == "cancelled"
        else RuntimeError("private exception details")
    )
    calls = []

    async def invoke():
        async def next_call():
            calls.append(context.arguments)
            if outcome != "completed":
                raise failure
            context.result = "untouched tool output"

        await ToolTelemetry(composition).process(context, next_call)

    with caplog.at_level(logging.INFO, logger="simassist.agents.orchestrator"):
        if outcome == "completed":
            asyncio.run(invoke())
            assert context.result == "untouched tool output"
        else:
            with pytest.raises(type(failure)) as caught:
                asyncio.run(invoke())
            assert caught.value is failure

    assert calls == [{"file_id": "file-456"}]
    assert composition.invoked == ["inspect_uploaded_file"]
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert messages[0].startswith("agent_tool_start ")
    assert 'arguments={"file_id":"file-456"}' in messages[0]
    assert messages[1].startswith("agent_tool_end ")
    assert f"status={outcome}" in messages[1]
    assert "duration_ms=" in messages[1]
    for message in messages:
        assert "request=request-123" in message
        assert "tool=inspect_uploaded_file" in message
    assert (
        messages[0].split("call=")[1].split()[0]
        == messages[1].split("call=")[1].split()[0]
    )
    assert "private exception details" not in caplog.text
    assert "untouched tool output" not in caplog.text


def test_arguments_preview_is_short_single_line_and_supports_models():
    class Arguments(BaseModel):
        name: str
        parameters: dict[str, float]

    assert _tool_arguments_preview(
        Arguments(name="Block", parameters={"width": 3})
    ) == ('{"name":"Block","parameters":{"width":3.0}}')
    preview = _tool_arguments_preview(
        {"name": "line one\nline two", "operands": ["x" * 1000]}
    )
    assert len(preview) == 500
    assert preview.endswith("...")
    assert "\n" not in preview
    assert "\\n" in preview


def test_logging_also_works_without_composition(caplog):
    context = SimpleNamespace(
        function=SimpleNamespace(name="list_project_jobs"), arguments={}
    )

    async def invoke():
        async def next_call():
            context.result = "done"

        await ToolTelemetry().process(context, next_call)

    with caplog.at_level(logging.INFO, logger="simassist.agents.orchestrator"):
        asyncio.run(invoke())
    assert context.result == "done"
    assert "tool=list_project_jobs arguments={}" in caplog.text
    assert "status=completed" in caplog.text
