# Backend README (Flask + Groq + SQLite)

## MiniQuest Backend

This backend powers the MiniQuest adventure game for children, handling quests, AI storytelling, and event logging.

### Features

* Interactive story branching with Groq LLM and LangGraph.
* SQLite storage for quests and steps.
* Safety filters for forbidden words.
* COPPA-aware minimal data collection.
* Event logging for metrics: session start/finish, turns, FTU, recap opens.

### Requirements

* Python 3.10+
* pip packages:

```bash
pip install flask flask-cors groq langgraph python-dotenv
```

### Setup & Run

1. Clone the repo.
2. Create a `.env` file for Groq API key (if required).
3. Initialize database and run server:

```bash
python backend.py
```

4. Backend runs at `http://localhost:5000`.

### API Endpoints

| Endpoint                | Method | Description                               |
| ----------------------- | ------ | ----------------------------------------- |
| `/start`                | POST   | Start a new quest for a user.             |
| `/turn`                 | POST   | Send child input and get AI response.     |
| `/dashboard/<quest_id>` | GET    | Fetch quest summary for parent dashboard. |
| `/recap/<quest_id>`     | POST   | Generate 3-sentence story recap.          |
| `/log_event`            | POST   | Log events for metrics.                   |
| `/`                     | GET    | Health check.                             |

### Database

* `quests`: stores quest state and timestamps.
* `quest_steps`: stores each AI-child interaction.
* `events`: logs metrics for pilot analytics.

### Event Logging Example

```json
{
  "eventType": "turn",
  "quest_id": 1,
  "child_id": "player1",
  "turn_number": 2,
  "latency_ms": 300,
  "child_input": "I choose left",
  "ai_response": "You arrive at a river",
  "additionalData": {}
}
```

### Metrics

<img width="925" height="502" alt="Screenshot 2025-09-18 225659" src="https://github.com/user-attachments/assets/061a6333-094e-406c-9d6c-18cb00f0674b" />
<img width="4" height="3" alt="Screenshot 2025-09-18 225653" src="https://github.com/user-attachments/assets/64765e2e-5c1c-4752-bca4-856bf65a2b4e" />
<img width="907" height="28" alt="Screenshot 2025-09-18 225649" src="https://github.com/user-attachments/assets/db97b397-9328-48f1-9c7b-a5311b46f360" />
<img width="919" height="226" alt="Screenshot 2025-09-18 225645" src="https://github.com/user-attachments/assets/077ca74d-720f-41fc-992d-36aa209e4ae1" />
<img width="923" height="263" alt="Screenshot 2025-09-18 225639" src="https://github.com/user-attachments/assets/a96808ac-52ed-4fe0-9ca5-b575ef55a53e" />
