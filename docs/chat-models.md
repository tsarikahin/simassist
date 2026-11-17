# Chat model selection

Choose a model above the chat input. Each message uses the selected model, and
switching models keeps the current conversation history. The browser remembers
your choice across reloads. The selector is disabled while a response is running.

The backend exposes the choices through `GET /api/chat/models`. By default they
are `qwen3.5-4b`, `spark-x2.6-4b`, and `google/gemma-4-e2b`, with
`spark-x2.6-4b` selected initially.

To change the list, set these variables before starting the backend (PowerShell):

```powershell
$env:SIMASSIST_CHAT_MODELS = "qwen3.5-4b,spark-x2.6-4b,google/gemma-4-e2b"
$env:SIMASSIST_MODEL = "spark-x2.6-4b"
```

`SIMASSIST_CHAT_MODELS` is a comma-separated list of model IDs served by your
LM Studio instance. `SIMASSIST_MODEL` sets the default and is automatically
included in the choices. Both models use the existing `SIMASSIST_LLM_ENDPOINT`
(default `http://127.0.0.1:1235/v1`). Restart the backend and reload the page after
changing configuration.

Both `POST /api/chat` and `POST /api/chat/stream` accept an optional `model` field.
Omitting it uses the configured default. Unknown model IDs return HTTP 422 before
the turn is stored or executed.
