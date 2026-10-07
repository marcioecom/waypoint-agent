from pydantic import BaseModel, Field


class FlightOffer(BaseModel):
    """Oferta copiada do resultado da busca. Nunca inventar nem enviar só o id."""

    price: str = Field(description="Preço já formatado, ex: R$ 3.240,00")
    route: str = Field(
        description="Rota e horários, ex: GRU → LIS · 22:10 → 12:05 · 12/10"
    )
    details: str = Field(
        default="",
        description="Companhia, escalas e bagagem, se o resultado informar",
    )
    booking_url: str = Field(description="URL de checkout da oferta")


class AgentReply(BaseModel):
    """Resposta montada pela aplicação para o WhatsApp."""

    message: str = Field(
        description="Texto humano da conversa. Nunca só ids de oferta."
    )
    offers: list[FlightOffer] = Field(
        default_factory=list,
        max_length=3,
        description="Até 3 ofertas com preço, rota e link. Vazio se não houver voos para mostrar.",
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
    return as_text(messages[-1].content).strip()
