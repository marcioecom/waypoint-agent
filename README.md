# travel-agent

Agent de viagens. Recebe o texto de uma conversa, consulta o Kiwi e devolve a resposta. Quem fala com o WhatsApp é o gateway (`waypoint-baileys`).

1. O gateway faz `POST /v1/messages` com `{ message, thread_id }`. O `thread_id` é o JID do chat.
2. Com `GATEWAY_URL`, este serviço responde `202` e continua o trabalho.
3. Quando o modelo termina, faz `POST {GATEWAY_URL}/messages` com `{ jid, text }`.
4. Sem `GATEWAY_URL`, responde na hora com `{ messages }`.

Os dois serviços usam o mesmo `GATEWAY_TOKEN` no header `Authorization: Bearer ...`. Sem esse token, `/v1/messages` fica aberto.

A memória da conversa fica em SQLite por `thread_id`:
- checkpointer LangGraph: `SQLITE_PATH` (padrão `data/agent.sqlite`)
- preferências + pedido ativo (`TripBrief`): arquivo irmão `*-state.sqlite`

A busca passa por um wrapper fino da Kiwi (top ofertas já normalizadas). O texto do WhatsApp é montado a partir da resposta estruturada (mensagem + ofertas com preço, rota e link).

```bash
uv sync
cp .env.example .env
fastapi dev main.py
```

Testes:

```bash
uv run pytest
```

## Estrutura

Organização no estilo LangGraph + módulos claros (mental model de Node):

```text
main.py / app.py          # entrypoints (FastAPI / Streamlit)
travel_agent/
  settings.py             # configuração (envs)
  api/                    # HTTP (rotas + auth)
  services/               # orquestração (chat, gateway client)
  agent/                  # domínio do agent
    builder.py            # create_agent / wiring
    prompt.py             # system prompt
    reply.py              # schema + render WhatsApp
    flights.py            # compressão Kiwi
    memory.py             # checkpointer, prefs, trip brief
    tools/                # tools do modelo
    middleware/           # trim, guards
tests/
```

| Pasta / arquivo | Analogia Node | O que faz |
| --- | --- | --- |
| `travel_agent/api/` | `routes/` + middleware HTTP | Contrato FastAPI |
| `travel_agent/services/` | `services/` | Roda o agent e fala com o gateway |
| `travel_agent/agent/` | domínio do bot | Prompt, tools, memória, builder |
| `travel_agent/settings.py` | `config/` | Envs |

| Variável | Exemplo |
| --- | --- |
| `OPENAI_API_KEY` | chave da OpenAI / AI Gateway |
| `OPENAI_MODEL` | `gpt-5-mini` |
| `OPENAI_REASONING_EFFORT` | `low` (ou `minimal`/`medium`) |
| `OPENAI_VERBOSITY` | `low` |
| `GATEWAY_URL` | `http://localhost:3000` |
| `GATEWAY_TOKEN` | o mesmo segredo do gateway |
| `ADMIN_TOKEN` | token do `DELETE` admin (sem ele, o endpoint recusa) |
| `TIMEZONE` | `America/Sao_Paulo` |
| `SQLITE_PATH` | `data/agent.sqlite` |

Para zerar um chat de teste (preferências, pedido ativo e histórico LangGraph):

```bash
curl -X DELETE \
  "http://localhost:8000/v1/admin/threads/5511999999999%40s.whatsapp.net" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

O `thread_id` é o mesmo JID do WhatsApp usado em `POST /v1/messages`. Sem `ADMIN_TOKEN` no ambiente, ou com token errado, a resposta é `401`. Apagar uma thread que não existe devolve `200`.

No Railway, este é o segundo service. `GATEWAY_URL` usa a rede privada: `http://<gateway>.railway.internal:<porta>`. Monte um volume em `data/` se quiser persistir o SQLite entre deploys.
