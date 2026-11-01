import pytest


async def test_tool_errors_raise_instead_of_returning_text(boxes):
    with pytest.raises(RuntimeError, match="429"):
        await boxes["notion"].call("TEST-boom")


async def test_unknown_tool_has_helpful_message(boxes):
    with pytest.raises(RuntimeError, match="doctor"):
        await boxes["notion"].call("API-does-not-exist")


async def test_empty_gmail_result_is_not_an_error(boxes, mail_file):
    from agent.gmail import InboxReader
    assert await InboxReader(boxes["gmail"]).search("x") == []
