"""Normaliza e comprime resultados da Kiwi para o WhatsApp."""

from __future__ import annotations

import ast
import json
from datetime import datetime
from typing import Any


def _parse_json(payload: Any) -> Any:
    if isinstance(payload, str):
        text = payload.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # MCP adapters às vezes serializam content blocks com aspas simples.
            try:
                return ast.literal_eval(text)
            except (SyntaxError, ValueError):
                return {"raw": payload}
    return payload


def _unwrap_mcp_payload(payload: Any) -> Any:
    """Extrai o JSON útil de content blocks do MCP/LangChain.

    Formatos comuns:
    - dict já pronto
    - list[{type: text, text: "{...json...}"}]
    - str JSON / repr de list
    """
    data = _parse_json(payload)

    if isinstance(data, list):
        texts: list[str] = []
        for block in data:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text)
        for text in texts:
            parsed = _parse_json(text)
            if isinstance(parsed, dict) and (
                "itineraries" in parsed or "resultsCount" in parsed or "query" in parsed
            ):
                return parsed
        if texts:
            return _parse_json(texts[0])
        return data

    if isinstance(data, dict) and isinstance(data.get("content"), list):
        return _unwrap_mcp_payload(data["content"])

    return data


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _fmt_local(value: Any) -> str:
    text = _as_str(value)
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return f"{dt.day:02d}/{dt.month:02d} {dt.hour:02d}:{dt.minute:02d}"


def _route_line(leg: dict[str, Any] | None) -> str:
    if not isinstance(leg, dict):
        return ""
    airports = _as_list(leg.get("route"))
    path = " → ".join(str(code) for code in airports if code)
    dep = _fmt_local(leg.get("departureTime"))
    arr = _fmt_local(leg.get("arrivalTime"))
    times = f"{dep} → {arr}" if dep and arr else ""
    if path and times:
        return f"{path} · {times}"
    return path or times


def _details_line(itinerary: dict[str, Any]) -> str:
    outbound = _as_dict(itinerary.get("outbound"))
    segments = _as_list(outbound.get("segments"))
    carriers: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        name = segment.get("carrierName") or segment.get("carrier")
        if name and name not in carriers:
            carriers.append(str(name))
    stops = outbound.get("stops")
    stop_text = ""
    if isinstance(stops, int):
        stop_text = "direto" if stops == 0 else f"{stops} escala(s)"
    baggage = _as_dict(itinerary.get("baggage"))
    bags: list[str] = []
    if baggage.get("cabinBag"):
        bags.append(f"{baggage['cabinBag']} mão")
    if baggage.get("checkedBag"):
        bags.append(f"{baggage['checkedBag']} despachada")
    parts = [", ".join(carriers), stop_text, ("bagagem: " + ", ".join(bags)) if bags else ""]
    return " · ".join(part for part in parts if part)


def offer_from_itinerary(itinerary: dict[str, Any]) -> dict[str, str]:
    outbound = _as_dict(itinerary.get("outbound"))
    inbound = _as_dict(itinerary.get("inbound")) or None
    route_parts = [_route_line(outbound)]
    if inbound:
        inbound_line = _route_line(inbound)
        if inbound_line:
            route_parts.append(f"volta: {inbound_line}")
    price = itinerary.get("priceFormatted") or (
        str(itinerary.get("price")) if itinerary.get("price") is not None else ""
    )
    return {
        "price": str(price),
        "route": " | ".join(part for part in route_parts if part),
        "details": _details_line(itinerary),
        "booking_url": str(itinerary.get("bookingUrl") or ""),
    }


def compress_search_payload(payload: Any, *, limit: int = 5) -> dict[str, Any]:
    data = _unwrap_mcp_payload(payload)
    if not isinstance(data, dict):
        return {"resultsCount": 0, "offers": [], "raw": str(payload)[:500]}

    itineraries = data.get("itineraries")
    if not isinstance(itineraries, list):
        itineraries = []

    offers: list[dict[str, str]] = []
    for item in itineraries[:limit]:
        if isinstance(item, dict):
            offer = offer_from_itinerary(item)
            if offer["booking_url"] or offer["price"]:
                offers.append(offer)

    results_count = data.get("resultsCount", len(itineraries))
    if offers and (not results_count or results_count == 0):
        results_count = len(offers)

    return {
        "query": data.get("query"),
        "currency": data.get("currency"),
        "passengers": data.get("passengers"),
        "resultsCount": results_count,
        "offers": offers,
        "note": (
            "Copie price/route/details/booking_url das offers para AgentReply. "
            "Não invente dados."
            if offers
            else "Sem itinerários. Ajuste a busca e tente de novo sem perguntar menu."
        ),
    }


def mcp_search_args(
    *,
    fly_from: str,
    fly_to: str,
    departure_date: str,
    departure_date_to: str | None = None,
    return_date: str | None = None,
    return_date_to: str | None = None,
    nights_in_dst_from: int | None = None,
    nights_in_dst_to: int | None = None,
    adults: int = 1,
    cabin_class: str = "M",
    currency: str = "BRL",
    sort: str = "price",
) -> dict[str, Any]:
    """Preenche o schema estrito do MCP Kiwi com defaults seguros."""
    # Estadia fixa (ex.: 7 noites) é o padrão certo para "ida + N dias".
    # Nessas buscas, returnDate vira redundante e costuma piorar o match.
    if nights_in_dst_from is not None or nights_in_dst_to is not None:
        return_date = None
        return_date_to = None
        if nights_in_dst_from is None:
            nights_in_dst_from = nights_in_dst_to
        if nights_in_dst_to is None:
            nights_in_dst_to = nights_in_dst_from

    return {
        "flyFrom": fly_from,
        "flyTo": fly_to,
        "departureDate": departure_date,
        "departureDateFlexDays": 0,
        "departureDateTo": departure_date_to,
        "returnDate": return_date,
        "returnDateFlexDays": 0,
        "returnDateTo": return_date_to,
        "adults": adults,
        "children": 0,
        "infants": 0,
        "cabinClass": cabin_class,
        "currency": currency,
        "locale": "pt",
        "nights_in_dst_from": nights_in_dst_from,
        "nights_in_dst_to": nights_in_dst_to,
        "one_for_city": False,
        "max_sector_stopovers": None,
        "price_from": None,
        "price_to": None,
        "max_fly_duration": None,
        "select_airlines": None,
        "exclude_airlines": None,
        "dtime_from": None,
        "dtime_to": None,
        "atime_from": None,
        "atime_to": None,
        "ret_dtime_from": None,
        "ret_dtime_to": None,
        "ret_atime_from": None,
        "ret_atime_to": None,
        "stopover_from": None,
        "stopover_to": None,
        "adults_hold_bags": None,
        "adults_hand_bags": None,
        "children_hold_bags": None,
        "children_hand_bags": None,
        "allow_self_transfer": True,
        "allow_overnight_stopovers": True,
        "allow_diff_airport_connection": True,
        "stopover_airports": None,
        "exclude_stopover_airports": None,
        "stopover_countries": None,
        "exclude_stopover_countries": None,
        "fly_days": None,
        "ret_fly_days": None,
        "sort": sort,
    }
