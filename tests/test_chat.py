from travel_agent.services.chat import as_text


def test_as_text_joins_blocks():
    assert as_text("olá") == "olá"
    assert as_text(["a", {"text": "b"}, {"type": "ignore"}]) == "a\nb"
