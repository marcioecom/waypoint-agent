"""Fronteira Kiwi: validação de busca, normalização MCP e render WhatsApp."""

from __future__ import annotations

import asyncio
import copy
import json
import math
import re
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import jsonschema
from jsonschema import ValidationError as JsonSchemaValidationError
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel

from settings import settings

SEARCH_TOOL_NAME = "search-flight"
MCP_SERVER_URL = "https://mcp.kiwi.com"
MCP_TIMEOUT_S = 30
INVOKE_TIMEOUT_S = 30.0
MAX_ITINERARIES = 6
MAX_OFFER_CARDS = 3
_MAX_DISPLAY_LEN = 80

NEUTRAL_TOOL_DESCRIPTION = (
    "Busca voos no Kiwi com origem, destino, datas e passageiros. "
    "Retorna JSON com itinerários; não formate tabelas nem invente preços ou links."
)

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_IATA_RE = re.compile(r"^[A-Z]{3}$")
_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_EMAIL_RE = re.compile(r"@[\w.-]+\.\w+")
_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
_MD_TABLE_RE = re.compile(r"^\s*\|.+\|\s*$", re.MULTILINE)
_HTML_TAG_RE = re.compile(r"<[/a-zA-Z][^>]*>")
_CODE_FENCE_RE = re.compile(r"```")
_URL_IN_TEXT_RE = re.compile(r"https?://", re.I)
_MD_BOLD_RE = re.compile(r"\*\*")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_OFFER_PRICE_CLAIM_RE = re.compile(
    r"(R\$\s*[\d.,]+|\b(opção|oferta)\s*\d+.*\d+\s*(BRL|R\$))",
    re.I,
)

_KIWI_HOSTS = frozenset({"kiwi.com", "www.kiwi.com"})
_BAGGAGE_KEYS = ("personalItem", "cabinBag", "checkedBag")

_MSG_OUT_OF_SCOPE = (
    "Só consigo ajudar com busca de voos (origem, destino, datas e passageiros) por aqui."
)
_MSG_UNAVAILABLE_EMPTY = (
    "Não encontrei voos com esses critérios. Quer tentar datas mais flexíveis ou outro aeroporto próximo?"
)
_MSG_UNAVAILABLE_ERROR = "A busca não completou; tente novamente em instantes."
_MSG_UNAVAILABLE_DEFAULT = (
    "Para buscar voos, preciso de origem, destino e data de ida. Quer começar por aí?"
)
_RENDER_FOOTER = "Preço e disponibilidade podem mudar até concluir a reserva; confira no checkout."


def _today_local() -> date:
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _parse_br_date(value: str) -> date:
    if not _DATE_RE.fullmatch(value):
        raise ValueError(f"data inválida: {value!r}")
    day, month, year = (int(p) for p in value.split("/"))
    return date(year, month, day)


def _safe_external_text(value: str, *, iata: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _MAX_DISPLAY_LEN:
        return None
    if _CTRL_RE.search(text) or _HTML_TAG_RE.search(text) or _URL_IN_TEXT_RE.search(text) or re.search(r"[*`<>]", text):
        return None
    if _MD_TABLE_RE.search(text) or "|" in text:
        return None
    if iata:
        up = text.upper()
        return up if _IATA_RE.fullmatch(up) else None
    return text


def _location_ok(value: str) -> None:
    if not value or len(value) > 100:
        raise ValueError("origem/destino inválido")
    if (
        _EMAIL_RE.search(value) or _CPF_RE.search(value) or _PHONE_RE.search(value)
        or _safe_external_text(value) is None or "@" in value
    ):
        raise ValueError("origem/destino deve conter somente cidade ou aeroporto")


def _bag_list_ok(items: list[int] | None, count: int, label: str, per_max: int) -> None:
    if items is None:
        return
    if len(items) != count:
        raise ValueError(f"{label}: quantidade não confere com passageiros")
    if any(not isinstance(x, int) or x < 0 or x > per_max for x in items):
        raise ValueError(f"{label}: valores fora do permitido")


def _tool_json_schema(args_schema: Any) -> dict[str, Any] | None:
    if isinstance(args_schema, dict):
        return args_schema
    if isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
        return args_schema.model_json_schema()
    if hasattr(args_schema, "model_json_schema"):
        return args_schema.model_json_schema()
    return None


def _normalize_schema_node(node: Any) -> Any:
    if not isinstance(node, dict):
        return node
    out = copy.deepcopy(node)
    if "ge" in out and "minimum" not in out:
        out["minimum"] = out.pop("ge")
    if "le" in out and "maximum" not in out:
        out["maximum"] = out.pop("le")
    for key in ("properties", "patternProperties", "$defs", "definitions"):
        if key in out and isinstance(out[key], dict):
            out[key] = {k: _normalize_schema_node(v) for k, v in out[key].items()}
    if "items" in out:
        out["items"] = _normalize_schema_node(out["items"])
    for key in ("allOf", "anyOf", "oneOf"):
        if key in out and isinstance(out[key], list):
            out[key] = [_normalize_schema_node(x) for x in out[key]]
    return out


def prepare_tool_schema(args_schema: Any) -> dict[str, Any] | None:
    raw = _tool_json_schema(args_schema)
    if raw is None:
        return None
    schema = _normalize_schema_node(raw)
    if isinstance(schema, dict):
        schema["additionalProperties"] = False
        props = schema.get("properties")
        if isinstance(props, dict):
            if "currency" in props and isinstance(props["currency"], dict):
                props["currency"]["default"] = "BRL"
            if "cabinClass" in props and isinstance(props["cabinClass"], dict):
                props["cabinClass"]["default"] = "M"
    return schema


def _apply_param_defaults(params: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
    p = dict(params)
    if schema:
        props = schema.get("properties") or {}
        if isinstance(props, dict):
            for key, spec in props.items():
                if key not in p and isinstance(spec, dict) and "default" in spec:
                    p[key] = spec["default"]
    if schema and isinstance(schema.get("properties"), dict):
        props = schema["properties"]
        if "currency" in props:
            p.setdefault("currency", "BRL")
        if "cabinClass" in props:
            p.setdefault("cabinClass", "M")
    else:
        p.setdefault("currency", "BRL")
        p.setdefault("cabinClass", "M")
    return p


def _coerce_int_field(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} inválido")
    return value


def validate_with_tool_schema(params: dict[str, Any], args_schema: Any) -> None:
    schema = prepare_tool_schema(args_schema)
    if schema is None:
        return
    jsonschema.validate(instance=params, schema=schema)


def validate_search_params(params: dict[str, Any]) -> dict[str, Any]:
    p = dict(params)
    fly_from = p.get("flyFrom")
    fly_to = p.get("flyTo")
    if not isinstance(fly_from, str) or not isinstance(fly_to, str):
        raise ValueError("flyFrom e flyTo são obrigatórios")
    _location_ok(fly_from.strip())
    _location_ok(fly_to.strip())

    dep = p.get("departureDate")
    if not isinstance(dep, str):
        raise ValueError("departureDate obrigatório")
    dep_d = _parse_br_date(dep)

    dep_to = p.get("departureDateTo")
    dep_flex = int(p.get("departureDateFlexDays") or 0)
    if dep_to is not None:
        if dep_flex:
            raise ValueError("use departureDateTo ou departureDateFlexDays, não ambos")
        if _parse_br_date(dep_to) < dep_d:
            raise ValueError("departureDateTo anterior a departureDate")

    ret = p.get("returnDate")
    ret_to = p.get("returnDateTo")
    ret_flex = int(p.get("returnDateFlexDays") or 0)
    if ret is not None:
        ret_d = _parse_br_date(ret)
        if ret_d < dep_d:
            raise ValueError("returnDate anterior à ida")
        if ret_to is not None:
            if ret_flex:
                raise ValueError("use returnDateTo ou returnDateFlexDays, não ambos")
            if _parse_br_date(ret_to) < ret_d:
                raise ValueError("returnDateTo anterior a returnDate")
    elif ret_to is not None or ret_flex:
        raise ValueError("returnDate obrigatório para volta flexível ou intervalo")

    nights_from = p.get("nights_in_dst_from")
    nights_to = p.get("nights_in_dst_to")
    if nights_from is not None and nights_to is not None and nights_from > nights_to:
        raise ValueError("nights_in_dst_from maior que nights_in_dst_to")

    if "adults" not in p:
        raise ValueError("adults obrigatório")
    adults = _coerce_int_field(p["adults"], "adults")
    if not 1 <= adults <= 9:
        raise ValueError("adults deve ser entre 1 e 9")
    children = _coerce_int_field(p.get("children", 0), "children")
    if not 0 <= children <= 8:
        raise ValueError("children deve ser entre 0 e 8")
    infants = _coerce_int_field(p.get("infants", 0), "infants")
    if infants < 0 or infants > adults:
        raise ValueError("infants inválido")
    if adults + children + infants > 9:
        raise ValueError("máximo 9 passageiros")
    p["adults"] = adults
    p["children"] = children
    p["infants"] = infants

    _bag_list_ok(p.get("adults_hold_bags"), adults, "adults_hold_bags", 2)
    _bag_list_ok(p.get("adults_hand_bags"), adults, "adults_hand_bags", 1)
    _bag_list_ok(p.get("children_hold_bags"), children, "children_hold_bags", 2)
    _bag_list_ok(p.get("children_hand_bags"), children, "children_hand_bags", 1)

    currency = (p.get("currency") or "BRL").upper()
    if not _CURRENCY_RE.fullmatch(currency):
        raise ValueError("currency inválida")
    p["currency"] = currency

    if p.get("select_airlines") and p.get("exclude_airlines"):
        raise ValueError("select_airlines e exclude_airlines são mutuamente exclusivos")

    price_from = p.get("price_from")
    price_to = p.get("price_to")
    if price_from is not None and price_to is not None and price_from > price_to:
        raise ValueError("price_from maior que price_to")

    for a, b, label in (
        (p.get("dtime_from"), p.get("dtime_to"), "horário de partida ida"),
        (p.get("atime_from"), p.get("atime_to"), "horário de chegada ida"),
        (p.get("ret_dtime_from"), p.get("ret_dtime_to"), "horário de partida volta"),
        (p.get("ret_atime_from"), p.get("ret_atime_to"), "horário de chegada volta"),
        (p.get("stopover_from"), p.get("stopover_to"), "escala"),
    ):
        if a is not None and b is not None and a > b:
            raise ValueError(f"{label}: intervalo inválido")

    if dep_d < _today_local():
        raise ValueError("departureDate no passado")
    return p


def is_allowed_kiwi_booking_url(url: str) -> bool:
    if not isinstance(url, str) or not url.strip() or url != url.strip():
        return False
    if _CTRL_RE.search(url) or "\\" in url or re.search(r"\s", url):
        return False
    try:
        parsed = urlparse(url)
        port = parsed.port
    except Exception:
        return False
    if parsed.scheme != "https":
        return False
    if parsed.username or parsed.password:
        return False
    if port is not None and port != 443:
        return False
    host = (parsed.hostname or "").lower()
    if not host or _CTRL_RE.search(host):
        return False
    return host in _KIWI_HOSTS


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _segment_times_ok(dep_raw: str, arr_raw: str) -> bool:
    try:
        dep, arr = _parse_iso(dep_raw), _parse_iso(arr_raw)
    except ValueError:
        return False
    if dep.tzinfo is not None and arr.tzinfo is not None:
        return arr >= dep
    return True


def _normalize_baggage(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict):
        return None
    out = {k: raw[k] for k in _BAGGAGE_KEYS if isinstance(raw.get(k), int) and raw[k] >= 0}
    return out or None


def _normalize_segment(seg: dict[str, Any]) -> dict[str, Any] | None:
    req = ("from", "to", "departureTime", "arrivalTime")
    if not all(isinstance(seg.get(k), str) for k in req):
        return None
    from_iata = _safe_external_text(seg["from"], iata=True)
    to_iata = _safe_external_text(seg["to"], iata=True)
    if not from_iata or not to_iata:
        return None
    if not _segment_times_ok(seg["departureTime"], seg["arrivalTime"]):
        return None
    dur = seg.get("durationSeconds")
    if dur is not None and (type(dur) not in (int, float) or not math.isfinite(dur) or dur < 0):
        return None
    clean: dict[str, Any] = {
        "from": from_iata,
        "to": to_iata,
        "departureTime": seg["departureTime"],
        "arrivalTime": seg["arrivalTime"],
    }
    if isinstance(dur, (int, float)):
        clean["durationSeconds"] = int(dur)
    for key in ("fromCity", "toCity", "flightNumber", "cabinClass"):
        if isinstance(seg.get(key), str):
            safe = _safe_external_text(seg[key])
            if safe:
                clean[key] = safe
    for key in ("carrier", "carrierName"):
        if isinstance(seg.get(key), str):
            safe = _safe_external_text(seg[key])
            if safe:
                clean[key] = safe
    return clean


def _normalize_leg(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    segments_raw = raw.get("segments")
    if not isinstance(segments_raw, list) or not segments_raw:
        return None
    segments: list[dict[str, Any]] = []
    for block in segments_raw:
        if not isinstance(block, dict):
            return None
        norm = _normalize_segment(block)
        if norm is None:
            return None
        segments.append(norm)
    from_code = _safe_external_text(str(raw.get("from") or segments[0]["from"]), iata=True)
    to_code = _safe_external_text(str(raw.get("to") or segments[-1]["to"]), iata=True)
    if not from_code or not to_code or from_code != segments[0]["from"] or to_code != segments[-1]["to"]:
        return None
    leg: dict[str, Any] = {
        "from": from_code,
        "to": to_code,
        "departureTime": segments[0]["departureTime"],
        "arrivalTime": segments[-1]["arrivalTime"],
        "segments": segments,
    }
    stops = raw.get("stops")
    if stops is not None:
        if type(stops) is not int or stops != len(segments) - 1:
            return None
        leg["stops"] = stops
    duration = raw.get("durationSeconds")
    if duration is not None:
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            return None
        leg["durationSeconds"] = int(duration)
    if isinstance(raw.get("route"), list):
        route = []
        for x in raw["route"]:
            code = _safe_external_text(str(x), iata=True)
            if code:
                route.append(code)
        if route:
            leg["route"] = route
    if isinstance(raw.get("cabinClass"), str):
        cabin = _safe_external_text(raw["cabinClass"])
        if cabin:
            leg["cabinClass"] = cabin
    return leg


def _normalize_itinerary(item: dict[str, Any]) -> dict[str, Any] | None:
    provider_id = item.get("id")
    price, url = item.get("price"), item.get("bookingUrl")
    if not isinstance(provider_id, str) or not provider_id:
        return None
    if not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
        return None
    if not isinstance(url, str) or not is_allowed_kiwi_booking_url(url):
        return None
    outbound = _normalize_leg(item.get("outbound"))
    if outbound is None:
        return None
    has_inbound = item.get("inbound") is not None
    inbound = _normalize_leg(item.get("inbound")) if has_inbound else None
    if has_inbound and inbound is None:
        return None

    clean: dict[str, Any] = {
        "providerId": provider_id,
        "price": float(price),
        "bookingUrl": url,
        "outbound": outbound,
    }
    duration = item.get("totalDurationSeconds")
    if duration is not None:
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            return None
        clean["totalDurationSeconds"] = int(duration)
    baggage = _normalize_baggage(item.get("baggage"))
    if baggage:
        clean["baggage"] = baggage
    if inbound:
        clean["inbound"] = inbound
    for flag_key in ("selfTransfer", "hasSelfTransfer", "isSelfTransfer"):
        if isinstance(item.get(flag_key), bool):
            clean["selfTransfer"] = item[flag_key]
            break
    return clean


def _validate_response_passengers(passengers: Any) -> dict[str, int] | None:
    if not isinstance(passengers, dict):
        return None
    try:
        a = _coerce_int_field(passengers.get("adults"), "adults")
        c = _coerce_int_field(passengers.get("children", 0), "children")
        i = _coerce_int_field(passengers.get("infants", 0), "infants")
    except ValueError:
        return None
    if not (1 <= a <= 9 and 0 <= c <= 8 and 0 <= i <= a and a + c + i <= 9):
        return None
    return {"adults": a, "children": c, "infants": i}


def _passengers_match(req: dict[str, Any], resp: dict[str, int] | None) -> bool:
    if resp is None:
        return False
    return (
        resp["adults"] == req.get("adults")
        and resp["children"] == req.get("children", 0)
        and resp["infants"] == req.get("infants", 0)
    )


def _itinerary_matches_request(it: dict[str, Any], req: dict[str, Any]) -> bool:
    price = it["price"]
    if req.get("price_from") is not None and price < req["price_from"]:
        return False
    if req.get("price_to") is not None and price > req["price_to"]:
        return False
    wants_return = req.get("returnDate") is not None or req.get("nights_in_dst_from") is not None
    if wants_return != bool(it.get("inbound")):
        return False
    for key, prefix in (("outbound", "departure"), ("inbound", "return")):
        leg = it.get(key)
        if not leg:
            continue
        if req.get(f"{prefix}Date"):
            start = _parse_br_date(req[f"{prefix}Date"])
            flex = timedelta(days=req.get(f"{prefix}DateFlexDays", 0))
            end = _parse_br_date(req[f"{prefix}DateTo"]) if req.get(f"{prefix}DateTo") else start + flex
            if not start - flex <= _parse_iso(leg["departureTime"]).date() <= end:
                return False
        maximum = req.get("max_sector_stopovers")
        if maximum is not None and (leg.get("stops") is None or leg["stops"] > maximum):
            return False
        for field, target in (("from", "flyFrom" if key == "outbound" else "flyTo"),
                              ("to", "flyTo" if key == "outbound" else "flyFrom")):
            if _IATA_RE.fullmatch(req[target]) and leg[field] != req[target]:
                return False
        if req.get("allow_diff_airport_connection") is False:
            if any(a["to"] != b["from"] for a, b in zip(leg["segments"], leg["segments"][1:])):
                return False
    return True


def _payload_context(payload: dict[str, Any]) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    cur = payload.get("currency")
    if isinstance(cur, str) and _CURRENCY_RE.fullmatch(cur):
        ctx["currency"] = cur
    pax = _validate_response_passengers(payload.get("passengers"))
    if pax:
        ctx["passengers"] = pax
    return ctx


def _empty_shell(partial: dict[str, Any] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {"status": "empty", "itineraries": []}
    if partial:
        for key in ("currency", "passengers", "search_request"):
            if key in partial:
                base[key] = partial[key]
    return base


def _error_result(message: str, partial: dict[str, Any] | None = None) -> dict[str, Any]:
    out = _empty_shell(partial)
    out["status"] = "error"
    out["error"] = message
    return out


def _structured_from_artifact(artifact: Any) -> dict[str, Any] | None:
    if artifact is None:
        return None
    sc = getattr(artifact, "structured_content", None)
    if isinstance(sc, dict):
        return sc
    if isinstance(artifact, dict):
        nested = artifact.get("structured_content") or artifact.get("structuredContent")
        if isinstance(nested, dict):
            return nested
    return None


def parse_mcp_tool_result(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, tuple) and len(raw) == 2:
        content, artifact = raw
        from_artifact = _structured_from_artifact(artifact)
        if from_artifact is not None:
            return from_artifact
        raw = content
    if isinstance(raw, dict):
        if "itineraries" in raw or "resultsCount" in raw or "error" in raw:
            return raw
        sc = raw.get("structuredContent") or raw.get("structured_content")
        if isinstance(sc, dict):
            return sc
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    if isinstance(raw, list):
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                try:
                    return json.loads(block["text"])
                except json.JSONDecodeError:
                    continue
    return None


def normalize_search_response(
    raw: Any,
    *,
    duration_ms: int | None = None,
    search_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = parse_mcp_tool_result(raw)
    if payload is None:
        return _error_result("mcp_invalid")

    ctx: dict[str, Any] = {}
    if search_params:
        ctx["search_request"] = search_params
    ctx.update(_payload_context(payload))
    meta = {"durationMs": duration_ms} if duration_ms is not None else {}

    if payload.get("error") is not None or payload.get("isError") is True:
        return _error_result("kiwi_error", ctx)

    currency = payload.get("currency")
    if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
        return _error_result("bad_currency", ctx)

    if search_params and currency != search_params.get("currency"):
        return _error_result("currency_mismatch", ctx)

    passengers = _validate_response_passengers(payload.get("passengers"))
    if passengers is None and payload.get("passengers") is not None:
        return _error_result("bad_passengers", ctx)
    if search_params and not _passengers_match(search_params, passengers):
        return _error_result("passengers_mismatch", ctx)

    ctx = {**ctx, "currency": currency}
    if passengers:
        ctx["passengers"] = passengers

    itineraries_raw = payload.get("itineraries")
    if not isinstance(itineraries_raw, list):
        return _error_result("no_itineraries", ctx)

    if len(itineraries_raw) == 0:
        shell = _empty_shell(ctx)
        if meta:
            shell["_meta"] = meta
        return shell

    normalized: list[dict[str, Any]] = []
    saw_candidate = False
    for item in itineraries_raw:
        if not isinstance(item, dict):
            saw_candidate = True
            continue
        saw_candidate = True
        leg = _normalize_itinerary(item)
        if leg is None:
            continue
        if search_params and not _itinerary_matches_request(leg, search_params):
            continue
        normalized.append(leg)
        if len(normalized) >= MAX_ITINERARIES:
            break

    if not normalized:
        err = _error_result("invalid_itineraries", ctx) if saw_candidate else _empty_shell(ctx)
        if meta:
            err["_meta"] = meta
        return err

    for idx, it in enumerate(normalized, start=1):
        it["id"] = str(idx)

    out: dict[str, Any] = {
        "status": "ok",
        "currency": currency,
        "itineraries": normalized,
    }
    if search_params:
        out["search_request"] = search_params
    if passengers:
        out["passengers"] = passengers
    if meta:
        out["_meta"] = meta
    return out


def agent_message_format_ok(message: str, *, kind: str) -> bool:
    if kind in ("offers", "detail", "unavailable", "out_of_scope"):
        return isinstance(message, str)
    if not isinstance(message, str) or not message.strip():
        return False
    if (
        _MD_TABLE_RE.search(message)
        or _HTML_TAG_RE.search(message)
        or _CODE_FENCE_RE.search(message)
        or _MD_BOLD_RE.search(message)
        or _MD_HEADING_RE.search(message)
    ):
        return False
    if _URL_IN_TEXT_RE.search(message):
        return False
    if kind in ("question", "ack") and _OFFER_PRICE_CLAIM_RE.search(message):
        return False
    return True


def _fmt_clock(iso: str) -> str:
    try:
        return _parse_iso(iso).strftime("%d/%m %H:%M")
    except ValueError:
        return iso


def _fmt_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    h, rem = divmod(int(seconds), 3600)
    m = rem // 60
    return f"{h}h{m:02d}" if h else f"{m}min"


def _stops_label(stops: int | None) -> str:
    if stops is None:
        return "escalas não informadas"
    if stops == 0:
        return "direto"
    return "1 escala" if stops == 1 else f"{stops} escalas"


def _format_money(price: float, currency: str) -> str:
    if currency == "BRL":
        whole, frac = f"{price:.2f}".split(".")
        whole = f"{int(whole):,}".replace(",", ".")
        return f"R$ {whole},{frac}"
    return f"{price:g} {currency}"


def _baggage_line(bag: dict[str, int] | None) -> str:
    if not bag:
        return ""
    parts = []
    if "personalItem" in bag:
        parts.append(f"item pessoal {bag['personalItem']}")
    if "cabinBag" in bag:
        parts.append(f"mão {bag['cabinBag']}")
    if "checkedBag" in bag:
        parts.append(f"despachada {bag['checkedBag']}")
    if not parts:
        return ""
    return "Bagagem na tarifa (unidade não confirmada; confira no checkout): " + ", ".join(parts)


def _price_label(it: dict[str, Any], currency: str) -> str:
    price = it.get("price")
    if isinstance(price, (int, float)) and math.isfinite(price):
        return _format_money(float(price), currency)
    return currency


def _carrier_summary(leg: dict[str, Any]) -> str:
    names: list[str] = []
    for seg in leg.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        name = seg.get("carrierName") or seg.get("carrier")
        if isinstance(name, str) and name and name not in names:
            names.append(name)
    return ", ".join(names)


def _leg_summary(leg: dict[str, Any]) -> str:
    carrier = _carrier_summary(leg)
    base = (
        f"{leg.get('from', '?')} → {leg.get('to', '?')} · "
        f"{_fmt_clock(leg['departureTime'])} → {_fmt_clock(leg['arrivalTime'])} "
        f"({_fmt_duration(leg.get('durationSeconds'))}, {_stops_label(leg.get('stops'))})"
    )
    return f"{base} · {carrier}" if carrier else base


def _leg_connection_alerts(leg: dict[str, Any]) -> list[str]:
    alerts: list[str] = []
    segs = [s for s in (leg.get("segments") or []) if isinstance(s, dict)]
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        if a.get("to") != b.get("from"):
            alerts.append(f"Conexão: aeroporto muda de {a.get('to')} para {b.get('from')}.")
        try:
            arr, dep = _parse_iso(a["arrivalTime"]), _parse_iso(b["departureTime"])
            if a.get("to") == b.get("from") and dep.date() > arr.date():
                alerts.append("Possível pernoite na conexão.")
        except (KeyError, ValueError):
            pass
    return alerts


def _offer_card(index: int, it: dict[str, Any], currency: str) -> str:
    lines = [f"*Opção {index}* — {_price_label(it, currency)}", f"Ida: {_leg_summary(it['outbound'])}"]
    inbound = it.get("inbound")
    if inbound:
        lines.append(f"Volta: {_leg_summary(inbound)}")
    bag = _baggage_line(it.get("baggage"))
    if bag:
        lines.append(bag)
    for leg in (it["outbound"], inbound):
        if leg:
            lines.extend(_leg_connection_alerts(leg))
    if it.get("selfTransfer") is True:
        lines.append("Conexão por conta própria: confira bagagem e condições antes de comprar.")
    lines.append(it["bookingUrl"])
    return "\n".join(lines)


def _segment_lines(leg: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for seg in leg.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        carrier = seg.get("carrierName") or seg.get("carrier") or "companhia não informada"
        flight = seg.get("flightNumber") or ""
        label = " ".join(x for x in (carrier, flight) if x).strip()
        out.append(
            f"  · {seg.get('from', '?')} → {seg.get('to', '?')} "
            f"{_fmt_clock(seg.get('departureTime', ''))}–{_fmt_clock(seg.get('arrivalTime', ''))}"
            + (f" ({label})" if label else "")
        )
    return out


def _self_transfer_line(it: dict[str, Any]) -> str:
    flag = it.get("selfTransfer")
    if flag is True:
        return "Conexão por conta própria indicada; proteção e condições precisam ser conferidas no checkout."
    return "Proteção das conexões: não confirmada pelo resultado."


def _detail_card(it: dict[str, Any], currency: str) -> str:
    lines = [f"*Detalhe* — {_price_label(it, currency)}", f"Ida: {_leg_summary(it['outbound'])}"]
    lines.extend(_segment_lines(it["outbound"]))
    for alert in _leg_connection_alerts(it["outbound"]):
        lines.append(alert)
    inbound = it.get("inbound")
    if inbound:
        lines.append(f"Volta: {_leg_summary(inbound)}")
        lines.extend(_segment_lines(inbound))
        for alert in _leg_connection_alerts(inbound):
            lines.append(alert)
    bag = _baggage_line(it.get("baggage"))
    if bag:
        lines.append(bag)
    elif it.get("baggage") is None:
        lines.append("Bagagem: não informada no resultado da busca.")
    lines.append(_self_transfer_line(it))
    lines.append(it["bookingUrl"])
    return "\n".join(lines)


def _search_header(search_result: dict[str, Any]) -> list[str]:
    req = search_result.get("search_request")
    if not isinstance(req, dict):
        return []
    lines: list[str] = []
    ff, ft = req.get("flyFrom"), req.get("flyTo")
    if isinstance(ff, str) and isinstance(ft, str):
        lines.append(f"Rota: {ff.strip()} → {ft.strip()}")
    dep = req.get("departureDate")
    if isinstance(dep, str):
        dep_line = f"Ida: {dep}"
        if isinstance(req.get("departureDateTo"), str):
            dep_line += f" até {req['departureDateTo']}"
        elif req.get("departureDateFlexDays"):
            dep_line += f" (±{req['departureDateFlexDays']} dias)"
        lines.append(dep_line)
    ret = req.get("returnDate")
    if isinstance(ret, str):
        ret_line = f"Volta: {ret}"
        if isinstance(req.get("returnDateTo"), str):
            ret_line += f" até {req['returnDateTo']}"
        elif req.get("returnDateFlexDays"):
            ret_line += f" (±{req['returnDateFlexDays']} dias)"
        lines.append(ret_line)
    elif req.get("nights_in_dst_from") is not None:
        nf, nt = req.get("nights_in_dst_from"), req.get("nights_in_dst_to")
        if nf is not None and nt is not None:
            lines.append(f"Estadia no destino: {nf}–{nt} noites")
    pax = search_result.get("passengers")
    if isinstance(pax, dict):
        a, c, i = int(pax.get("adults", 0)), int(pax.get("children", 0)), int(pax.get("infants", 0))
        lines.append(f"Passageiros: {a} adulto(s), {c} criança(s), {i} bebê(s).")
    cur = search_result.get("currency")
    if isinstance(cur, str) and _CURRENCY_RE.fullmatch(cur):
        lines.append(f"Moeda: {cur}")
    return lines


def _select_offers(
    offer_ids: list[str],
    search_result: dict[str, Any],
) -> tuple[list[dict[str, Any]] | None, str | None]:
    by_id = {
        it["id"]: it
        for it in search_result.get("itineraries", [])
        if isinstance(it.get("id"), str)
    }
    if not offer_ids:
        return [], None
    if any(i not in by_id for i in offer_ids):
        return None, "Os IDs de oferta não batem com a última busca. Peça uma nova busca."
    return [by_id[i] for i in offer_ids], None


def _render_offers_body(kind: str, reply: dict[str, Any], search_result: dict[str, Any]) -> str:
    offer_ids = reply.get("offer_ids") if isinstance(reply.get("offer_ids"), list) else []
    offer_ids = [x for x in offer_ids if isinstance(x, str)][:MAX_OFFER_CARDS]

    selected, err = _select_offers(offer_ids, search_result)
    if err:
        return err
    selected = selected or []

    if kind == "detail" and len(selected) != 1:
        return "Preciso de exatamente uma oferta válida para detalhar."

    currency = search_result.get("currency")
    if not isinstance(currency, str):
        currency = "???"

    body = _search_header(search_result)
    if kind == "detail" and selected:
        body.append(_detail_card(selected[0], currency))
    else:
        for oid in offer_ids:
            it = next(x for x in selected if x.get("id") == oid)
            body.append(_offer_card(int(oid), it, currency))
    body.append("Valor retornado para esta busca; abrangência por pessoa/grupo não confirmada.")
    body.append(_RENDER_FOOTER)
    return "\n\n".join(body)


def render_reply(reply: dict[str, Any] | Any, search_result: dict[str, Any] | None) -> str:
    if not isinstance(reply, dict):
        return "Não consegui montar a resposta. Tente de novo."

    kind = reply.get("kind") if isinstance(reply.get("kind"), str) else ""
    message = reply.get("message") if isinstance(reply.get("message"), str) else ""

    if kind not in ("question", "offers", "detail", "unavailable", "out_of_scope", "ack"):
        return "Resposta do assistente em formato inválido."
    if not agent_message_format_ok(message, kind=kind):
        return "Não consegui enviar essa mensagem com segurança (formato inválido). Pode reformular?"

    if search_result and search_result.get("status") == "error" and kind in ("offers", "detail"):
        return "A última busca falhou. Tente novamente em instantes."

    if kind == "out_of_scope":
        return _MSG_OUT_OF_SCOPE

    if kind == "unavailable":
        if search_result and search_result.get("status") == "empty":
            return _MSG_UNAVAILABLE_EMPTY
        if search_result and search_result.get("status") == "error":
            return _MSG_UNAVAILABLE_ERROR
        return _MSG_UNAVAILABLE_DEFAULT

    if kind in ("question", "ack"):
        return message.strip() if message.strip() else "Como posso ajudar na busca de voos?"

    if kind in ("offers", "detail"):
        if not search_result or search_result.get("status") != "ok":
            return "Não há resultados de busca válidos para mostrar ofertas."
        return _render_offers_body(kind, reply, search_result)

    return message.strip() if message.strip() else "Como posso ajudar na busca de voos?"


def _tool_result_dict(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict) and content.get("status") in ("ok", "empty", "error"):
        return content
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def latest_search_result(messages: list[BaseMessage] | list[Any]) -> dict[str, Any] | None:
    last_msg: ToolMessage | None = None
    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        name = getattr(msg, "name", None)
        if name and name != SEARCH_TOOL_NAME:
            continue
        last_msg = msg
    if last_msg is None:
        return None
    parsed = _tool_result_dict(last_msg.content)
    if not parsed:
        return None
    if parsed.get("status") == "error":
        return parsed
    if parsed.get("status") in ("ok", "empty"):
        return parsed
    return None


async def _invoke_normalized(source: BaseTool, **kwargs: Any) -> str:
    started = time.perf_counter()
    prepared_schema = prepare_tool_schema(source.args_schema)
    try:
        params = _apply_param_defaults(kwargs, prepared_schema)
        validate_with_tool_schema(params, prepared_schema or source.args_schema)
        params = validate_search_params(params)
    except (JsonSchemaValidationError, ValueError) as exc:
        return json.dumps(_error_result(str(exc)[:120]), ensure_ascii=False)
    try:
        raw = await asyncio.wait_for(source.ainvoke(params), timeout=INVOKE_TIMEOUT_S)
    except asyncio.TimeoutError:
        return json.dumps(_error_result("timeout"), ensure_ascii=False)
    except Exception:
        return json.dumps(_error_result("kiwi_failed"), ensure_ascii=False)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return json.dumps(
        normalize_search_response(raw, duration_ms=duration_ms, search_params=params),
        ensure_ascii=False,
    )


def build_search_tool(source: BaseTool) -> StructuredTool:
    if source.name != SEARCH_TOOL_NAME:
        raise ValueError(f"ferramenta inesperada: {source.name}")

    async def _run(**kwargs: Any) -> str:
        return await _invoke_normalized(source, **kwargs)

    return StructuredTool.from_function(
        coroutine=_run,
        name=SEARCH_TOOL_NAME,
        description=NEUTRAL_TOOL_DESCRIPTION,
        args_schema=prepare_tool_schema(source.args_schema),
    )


async def load_search_tool() -> StructuredTool:
    client = MultiServerMCPClient(
        {
            "travel_server": {
                "transport": "streamable_http",
                "url": MCP_SERVER_URL,
                "timeout": MCP_TIMEOUT_S,
            }
        }
    )
    tools = await client.get_tools()
    source = next((t for t in tools if t.name == SEARCH_TOOL_NAME), None)
    if source is None:
        raise RuntimeError(f"ferramenta {SEARCH_TOOL_NAME} não encontrada no MCP Kiwi")
    return build_search_tool(source)
