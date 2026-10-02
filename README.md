# travel-agent

Agent de viagens. Recebe o texto de uma conversa, consulta o Kiwi e devolve a resposta. Quem fala com o WhatsApp é o gateway (`waypoint-baileys`).

1. O gateway faz `POST /v1/messages` com `{ message, thread_id }`. O `thread_id` é o JID do chat.
2. Com `GATEWAY_URL`, este serviço responde `202` e continua o trabalho.
3. Quando o modelo termina, faz `POST {GATEWAY_URL}/messages` com `{ jid, text }`.
4. Sem `GATEWAY_URL`, responde na hora com `{ messages }`.

Os dois serviços usam o mesmo `GATEWAY_TOKEN` no header `Authorization: Bearer ...`. Sem esse token, `/v1/messages` fica aberto.

A memória da conversa é por `thread_id`, em `InMemorySaver`. Um restart esquece o histórico.

```bash
uv sync
cp .env.example .env
fastapi dev main.py
```

`main.py` sobe o FastAPI. O resto fica em funções de módulo, no mesmo papel dos arquivos em `src/` do gateway:

| Arquivo | O que faz |
| --- | --- |
| `settings.py` | Lê as envs. Ponto único de configuração. |
| `routers/message_routers_v1.py` | Contrato HTTP de `POST /v1/messages`. |
| `chat.py` | Roda o agent e agenda a resposta. |
| `gateway.py` | Manda `{ jid, text }` de volta para o gateway. |
| `middlewares/auth.py` | Exige o token só em `/v1/messages`. |
| `agent.py` | Monta o modelo e as tools do Kiwi. |

`app.py` é a UI local em Streamlit. Não entra no fluxo do WhatsApp.

| Variável | Exemplo |
| --- | --- |
| `OPENAI_API_KEY` | chave da OpenAI |
| `GATEWAY_URL` | `http://localhost:3000` |
| `GATEWAY_TOKEN` | o mesmo segredo do gateway |

No Railway, este é o segundo service. `GATEWAY_URL` usa a rede privada: `http://<gateway>.railway.internal:<porta>`.
