from reply import AgentReply, FlightOffer, render_reply, text_from_response


def test_render_includes_offer_fields_not_just_ids():
    reply = AgentReply(
        message="Encontrei estas opções:",
        offers=[
            FlightOffer(
                price="R$ 2.100,00",
                route="GRU → LIS · 22:10 → 12:05",
                details="LATAM, 1 escala",
                booking_url="https://www.kiwi.com/deep?offer=abc",
            )
        ],
    )
    text = render_reply(reply)
    assert "Encontrei estas opções:" in text
    assert "*Opção 1* — R$ 2.100,00" in text
    assert "GRU → LIS · 22:10 → 12:05" in text
    assert "LATAM, 1 escala" in text
    assert "https://www.kiwi.com/deep?offer=abc" in text
    assert text.strip() != "abc"
    assert "offer_ids" not in text


def test_render_without_offers_is_just_the_message():
    assert render_reply(AgentReply(message="De onde você sai?")) == "De onde você sai?"


def test_text_from_response_prefers_structured_offers():
    class Msg:
        content = "offer-id-99"

    text = text_from_response(
        {
            "structured_response": {
                "message": "Olha essa:",
                "offers": [
                    {
                        "price": "R$ 900",
                        "route": "CGH → SDU · 08:00 → 09:00",
                        "details": "GOL, direto",
                        "booking_url": "https://www.kiwi.com/x",
                    }
                ],
            },
            "messages": [Msg()],
        },
        as_text=lambda content: str(content),
    )
    assert "R$ 900" in text
    assert "https://www.kiwi.com/x" in text
    assert "offer-id-99" not in text


def test_structured_schema_has_offer_payload_not_ids():
    properties = AgentReply.model_json_schema()["properties"]
    assert "offer_ids" not in properties
    assert "offers" in properties
    offer_props = FlightOffer.model_json_schema()["properties"]
    for field in ("price", "route", "booking_url"):
        assert field in offer_props


def _object_schemas(schema: dict):
    if schema.get("type") == "object" or "properties" in schema:
        yield schema
    for defn in schema.get("$defs", {}).values():
        yield from _object_schemas(defn)
    for defn in schema.get("definitions", {}).values():
        yield from _object_schemas(defn)


def test_structured_schema_sets_additional_properties_false():
    root = AgentReply.model_json_schema()
    assert root.get("additionalProperties") is False
    objects = list(_object_schemas(root))
    assert objects
    for schema in objects:
        assert schema.get("additionalProperties") is False
    assert FlightOffer.model_json_schema().get("additionalProperties") is False


def test_text_from_response_falls_back_to_message_content():
    class Msg:
        content = "Oi! Sou a Dhay."

    text = text_from_response(
        {"messages": [Msg()]},
        as_text=lambda content: str(content),
    )
    assert text == "Oi! Sou a Dhay."
