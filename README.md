# Afterglow

Incident response that learns from every postmortem. Afterglow recalls previous symptoms, mitigations, outcomes, and team preferences before suggesting a careful next step.

## Demo

The dashboard ships with a clearly labelled sample workspace. Try **Past checkout fix**, inspect the memory bank, then save a postmortem. In demo mode, saved learning stays in that browser. In connected mode, it is retained in Hindsight and becomes available to future recall.

Sample incident metrics and alerts are illustrative; they are not connected to production systems. The assistant never executes infrastructure actions.

## Run locally

Requires Python 3.10 or newer.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Set HINDSIGHT_API_KEY and GROQ_API_KEY in .env.
uvicorn server:app --reload
```

Open http://127.0.0.1:8000. Provider keys stay in the server environment and are never sent to the browser. `.env` is ignored by Git and Docker.

## Deploy on Render

The repository includes a Render Blueprint at [`render.yaml`](render.yaml). Render's Blueprint setup prompts for variables marked `sync: false`; provider secrets are not stored in the repository. The app also supports Docker via [`Dockerfile`](Dockerfile).

1. Push this repository to GitHub and connect it to Render.
2. In Render, create a new **Blueprint** from the repository. Render reads `render.yaml` and provisions the web service.
3. Enter `HINDSIGHT_API_KEY` and `GROQ_API_KEY` when prompted. Set `AFTERGLOW_ACCESS_KEY` to a separate, strong passphrase for the private assistant and memory endpoints. Share that passphrase only with demo viewers.
4. Wait for the deployment health check at `/healthz` to pass, then open the generated `onrender.com` URL.

The included Blueprint uses Render's free web service plan, which may spin down when idle. Choose an always-on plan in Render for a live event where cold starts are unacceptable. The Hindsight memory bank is external, so app restarts do not erase retained memories.

## How Hindsight is used

- **Recall:** each assistant question calls the official Hindsight Python client `recall` method. Retrieved memories are given to Groq as evidence. The assistant is instructed to cite incident IDs, say when evidence is missing, and recommend a reversible first step.
- **Retain:** **Save postmortem** calls `POST /api/resolve`, which stores the summary and incident metadata in the configured Hindsight bank.
- **Memory view:** the connected dashboard loads real bank memories from Hindsight. The offline demo uses separate sample data stored in the browser.
- **Tenant boundary:** one bank ID is configured with `HINDSIGHT_BANK_ID`. Use a distinct bank and access key per organization before serving multiple customers.

## Configuration

| Variable | Purpose |
| --- | --- |
| `HINDSIGHT_API_KEY` | Hindsight Cloud key |
| `HINDSIGHT_API_URL` | Hindsight API URL; defaults to Cloud |
| `HINDSIGHT_BANK_ID` | Persistent incident memory bank |
| `GROQ_API_KEY` | Groq key for grounded response generation |
| `GROQ_MODEL` | Groq model; defaults to `openai/gpt-oss-120b` |
| `AFTERGLOW_ACCESS_KEY` | Optional shared key protecting memory and assistant API routes |

## API

- `GET /api/status` — reports provider configuration without exposing credentials.
- `GET /api/memories` — lists the configured bank's latest memories.
- `POST /api/chat` — accepts `{ "message": "...", "incident": "INC-2486" }` and returns an answer grounded in recall.
- `POST /api/resolve` — accepts `{ "incident_id": "INC-2486", "service": "checkout", "summary": "..." }` and retains the postmortem.
- `GET /healthz` — deployment health check.

When `AFTERGLOW_ACCESS_KEY` is set, send it as `X-Afterglow-Key` for memory and assistant routes. The browser keeps it in session storage for the current tab session.

## Production follow-up

The live dashboard still uses sample incident cards and illustrative service metrics. Connect an authenticated incident source before using it for operational decisions. Add individual accounts and role-based authorization before a multi-user production rollout.
