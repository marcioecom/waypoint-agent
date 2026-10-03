# travel-agent — Dhay

Dhay é a assistente de **busca de voos** no WhatsApp. Recebe o texto de uma conversa, consulta o Kiwi (MCP) e devolve a resposta. Quem fala com o WhatsApp é o gateway (`waypoint-baileys`).

Escopo fixo: só busca e explica voos (`search-flight`). Não reserva, não paga, não altera reservas e não oferece hotel/pacote/visto.

1. O gateway faz `POST /v1/messages` com `{ message, thread_id }`. O `thread_id` é o JID do chat.
2. Com `GATEWAY_URL`, este serviço responde `202` e continua o trabalho.
3. Quando o modelo termina, faz `POST {GATEWAY_URL}/messages` com `{ jid, text }`.
4. Sem `GATEWAY_URL`, responde na hora com `{ messages }` (usado pela UI local em Streamlit).

Os dois serviços usam o mesmo `GATEWAY_TOKEN` no header `Authorization: Bearer ...`. **Sem esse token, `/v1/messages` fica indisponível (503)** — nunca aberto.

```bash
uv sync
cp .env.example .env
fastapi dev main.py
```

| Arquivo | O que faz |
| --- | --- |
| `prompts.py` | System prompt da Dhay: tom, fluxo de conversa, formato WhatsApp. |
| `agent.py` | Monta o grafo: modelo, tool de busca, limites, saída estruturada (`DhayReply`). |
| `kiwi.py` | Fronteira com o MCP Kiwi: valida argumentos de busca, normaliza o resultado, renderiza o texto final (sem tabelas/Markdown, com link e preço sempre do resultado real). |
| `chat.py` | Roda o agent por thread (lock, timeout, limite de recursão), redige PII antes de enviar ao modelo, loga métricas por turno. |
| `settings.py` | Envs: timeout, timezone, checkpoint, taxas de custo (opcionais). |
| `routers/message_routers_v1.py` | Contrato HTTP de `POST /v1/messages`. |
| `gateway.py` | Manda `{ jid, text }` de volta para o gateway. |
| `middlewares/auth.py` | Exige o token em `/v1/messages`; falha fechada sem `GATEWAY_TOKEN`. |
| `app.py` | UI local em Streamlit, mesmo runtime do WhatsApp. Não entra no fluxo de produção. |
| `evaluate.py` | Avaliação ponta a ponta com o modelo real: cenários de conversa (dados faltando, troca de critério, família, fora de escopo, injeção de prompt, falha/vazio da busca, isolamento entre threads). `--live` usa a Kiwi real. |

A conversa é persistida por `thread_id` em SQLite (`AsyncSqliteSaver`, caminho em `CHECKPOINT_PATH`). Cada thread do WhatsApp (JID) é isolada por um identificador derivado (hash), nunca o número em claro nos logs.

| Variável | Exemplo |
| --- | --- |
| `OPENAI_API_KEY` | chave da OpenAI |
| `GATEWAY_URL` | `http://localhost:3000` |
| `GATEWAY_TOKEN` | o mesmo segredo do gateway |
| `CHECKPOINT_PATH` | `data/dhay.sqlite` |
| `TIMEZONE` | `America/Sao_Paulo` |
| `AGENT_TIMEOUT_SECONDS` | `90` |
| `OPENAI_*_COST_PER_MILLION` | opcional, para custo estimado por turno nos logs |

Rodar a avaliação (sem tocar na Kiwi real):

```bash
uv run python evaluate.py
```

Com busca real (nunca reserva):

```bash
uv run python evaluate.py --live --case complete
```

No Railway, este é o segundo service. `GATEWAY_URL` usa a rede privada: `http://<gateway>.railway.internal:<porta>`.
