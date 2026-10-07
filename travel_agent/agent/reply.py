from pydantic import BaseModel, ConfigDict, Field


class FlightOffer(BaseModel):
    """Oferta copiada do resultado da busca. Nunca inventar nem enviar só o id."""

    model_config = ConfigDict(extra="forbid")

    price: str = Field(description="Preço já formatado, ex: R$ 3.240,00")
    route: str = Field(
        description="Rota e horários, ex: GRU → LIS · 22:10 → 12:05 · 12/10"
    )
    details: str = Field(
        description=(
            "Companhia, escalas e bagagem, se o resultado informar. "
            "Use string vazia se não houver."
        ),
    )
    booking_url: str = Field(description="URL de checkout da oferta")


class AgentReply(BaseModel):
    """Resposta montada pela aplicação para o WhatsApp."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        description="Texto humano da conversa. Nunca só ids de oferta."
    )
    offers: list[FlightOffer] = Field(
        max_length=3,
        description=(
            "Até 3 ofertas com preço, rota e link. "
            "Use lista vazia se não houver voos para mostrar."
        ),
    )


def render_reply(reply: AgentReply) -> str:
    parts = [reply.message.strip()]
    for index, offer in enumerate(reply.offers, start=1):
        card = [f"*Opção {index}* — {offer.price.strip()}", offer.route.strip()]
        if offer.details.strip():
            card.append(offer.details.strip())
        if offer.booking_url.strip():
            card.append(offer.booking_url.strip())
        parts.append("\n".join(line for line in card if line))
    return "\n\n".join(part for part in parts if part).strip()


SEARCH_BUDGET_FALLBACK = (
    "Parei as buscas pra não ficar rodando em círculo. "
    "Quer tentar outra origem, datas ou duração da estadia?"
)

_LIMIT_MARKERS = (
    "call limits exceeded",
    "model call limits exceeded",
    "tool call limit exceeded",
)


def text_from_response(response: dict, as_text) -> str:
    structured = response.get("structured_response")
    if structured is not None:
        try:
            reply = (
                structured
                if isinstance(structured, AgentReply)
                else AgentReply.model_validate(structured)
            )
            text = render_reply(reply)
            if text:
                return text
        except Exception:
            pass
    messages = response.get("messages") or []
    if not messages:
        return ""
    text = as_text(messages[-1].content).strip()
    if text and any(marker in text.casefold() for marker in _LIMIT_MARKERS):
        return SEARCH_BUDGET_FALLBACK
    return text
