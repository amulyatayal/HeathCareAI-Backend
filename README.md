# 🏥 Healthcare Companion AI Backend

Multi-agent FastAPI backend for patient education (breast cancer focus), with evidence-grounded responses, intent/stage classification, and safety validation. Built on AWS (Bedrock, OpenSearch, S3).

## 🌟 Features

- **💬 Multi-Agent Chat (v2)**: Intent + stage → retrieval → specialized reasoning → safety validator
- **📚 Evidence-Based**: Hybrid search over OpenSearch (medical + nutrition KBs), citations in responses
- **🔒 Guardrails**: Validator agent (rule-based + optional LLM) enforces non-clinical, educational output
- **📉 Structured Logs & Metrics**: Optional structured logging and metric emission toggles
- **📱 Multi-Platform**: iOS / Android / Web ready
- **☁️ AWS-Powered**: Bedrock (Claude), OpenSearch, S3

## 🏗️ Architecture (v2 pipeline)

```
Client (Web/iOS/Android)
   │
   ▼
FastAPI (v2)
   │
   ▼
┌─────────────────────────────────────────────┐
│ Orchestrator                                │
│  ├─ Intent Agent (parallel)                 │
│  ├─ Stage Agent (parallel)                  │
│  ├─ Retrieval Agent (KB routing)            │
│  ├─ Reasoning Agent (18 specialized)        │
│  └─ Validator Agent (guardrails + LLM opt)  │
└─────────────────────────────────────────────┘
   │
   ▼
AWS Bedrock (Claude) • OpenSearch (hybrid) • S3
```

## 🚀 Quick Start

### Prerequisites

- Python 3.9/3.10+
- AWS Account with access to:
  - Bedrock (Claude models)
  - OpenSearch Serverless
  - S3

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/amulyatayal/HeathCareAI-Backend.git
   cd HeathCareAI-Backend
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp env.example .env
   # Edit .env with your AWS credentials and endpoints
   ```

   **Chat / guests** (`POST /api/v2/chat/`): **guests do not require OAuth**; `X-User-ID` is optional for session tracking. Signed-in users send `Authorization: Bearer <JWT>`. For automated tests that need a stable user id with **no** headers, set `IS_AUTHENTICATION_REQUIRED=N` (optional: `UNAUTHENTICATED_TEST_USER_ID`). See `tests/test_chat_authentication.py`.

5. **Run the server**
   ```bash
   python main.py
   ```

   The API will be available at `http://localhost:8000`

### API Documentation

Once running, visit:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## 📁 Project Structure (key files)

```
HeathCareAI-Backend/
├── api/                    # API routes and endpoints
│   ├── __init__.py         # exports v1 (deprecated) + v2 (active)
│   ├── routes.py           # v2 multi-agent API
│   └── routes_deprecated.py# v1 single-agent API
├── config/                 # Configuration and AWS clients
│   ├── __init__.py
│   ├── settings.py
│   └── aws.py
├── models/                 # Pydantic schemas
│   ├── schemas.py          # v2 pipeline schemas
│   └── schemas_deprecated.py# v1 schemas
├── services/               # Business logic
│   ├── ai_agent.py         # v1 single-agent
│   ├── knowledge_base.py   # KB operations
│   └── agents/             # v2 multi-agent pipeline
│       ├── orchestrator.py
│       ├── intent_agent.py
│       ├── stage_agent.py
│       ├── retrieval_agent.py
│       ├── reasoning_agent.py
│       └── validator_agent.py
├── services/metrics.py     # structured metrics (log-based)
├── knowledge_base/         # KB management utilities
├── utils/                  # Helper functions
├── data/                   # Sample data and documents
├── logs/                   # Application logs
├── main.py                 # FastAPI application entry
├── requirements.txt        # Python dependencies
├── env.example            # Environment variables template
└── README.md
```

## 🔌 API Endpoints

### v2 (active, multi-agent pipeline)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v2/chat/` | Multi-agent chat (intent+stage → retrieval → reasoning → validator) |
| GET  | `/api/v2/health/` | Pipeline health |
| GET  | `/api/v2/health/ping` | Ping |
| GET  | `/api/v2/debug/routing/{intent}` | Inspect routing (KB/model/strict_rag) |
| POST | `/api/v2/debug/analyze` | Intent+stage only (no full answer) |

### v1 (deprecated, single-agent)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat/` | Legacy chat |
| DELETE | `/api/v1/chat/session/{session_id}` | Clear session |
| POST | `/api/v1/knowledge/search` | Search KB |
| POST | `/api/v1/knowledge/document` | Add document |
| DELETE | `/api/v1/knowledge/document/{id}` | Delete document |
| GET | `/api/v1/knowledge/stats` | KB stats |
| GET | `/api/v1/health/` | Health |
| GET | `/api/v1/health/ping` | Ping |

## 💬 Example Chat Requests

### v2 (recommended)
```bash
curl -X POST "http://localhost:8000/api/v2/chat/" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What are common side effects of chemotherapy?",
    "include_trace": false
  }'
```

### v1 (deprecated)
```bash
curl -X POST "http://localhost:8000/api/v1/chat/" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What are common side effects of chemotherapy?",
    "include_sources": true
  }'
```

## 🏥 Intent & Stage (v2)

- **Intents (18)**: symptoms, surgery_procedures, drains_wound_care, cancer_treatment, medication_info, side_effects, pre_surgery_prehab, post_surgery_recovery, follow_up_care, nutrition, exercise, clothing, emotional_support, diagnosis_testing, admin_logistics, safety_red_flags, statistics, unknown
- **Patient stages**: pre_diagnosis, awaiting_results, newly_diagnosed, active_treatment, post_treatment, surveillance, palliative_support, unknown

Routing:
- Most intents → KB `breast_cancer_knowledge`
- nutrition → primary `nutrition_assistant`, fallback `breast_cancer_knowledge` (strict_rag=False)
- emotional_support → primary `forum_posts`, fallback `breast_cancer_knowledge` (strict_rag=False)

## ☁️ AWS Setup

### Bedrock

1. Enable Claude model access in AWS Bedrock console
2. Recommended models:
   - Chat: `anthropic.claude-3-haiku-20240307-v1:0`
   - Embeddings: `amazon.titan-embed-text-v2:0`

### OpenSearch Serverless

1. Create a collection for vector search
2. Configure IAM permissions
3. Create index with the provided mapping

### S3

1. Create a bucket for document storage
2. Enable versioning (recommended)
3. Configure appropriate bucket policies

## 🔐 Security Considerations

- All medical information includes appropriate disclaimers
- Rate limiting to prevent abuse
- CORS configuration for allowed origins
- No storage of personal health information (PHI) by default
- Secure API authentication (implement as needed)

## 🧪 Testing

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

## 📝 Environment Variables (key)

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_REGION` | AWS region | `us-east-1` |
| `OPENSEARCH_ENDPOINT` | OpenSearch URL | - |
| `BEDROCK_MODEL_ID` | Chat model ID | `anthropic.claude-3-haiku-20240307-v1:0` |
| `S3_BUCKET_NAME` | Document bucket | - |
| `API_PORT` | Server port | `8000` |
| `DEBUG` | Debug mode | `true` |
| `ENABLE_STRUCTURED_LOGGING` | Emit JSON logs | `true` |
| `ENABLE_METRICS` | Emit metrics as logs | `false` |
| `METRICS_NAMESPACE` | Metrics namespace | `healthcare_ai_backend` |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## ⚠️ Disclaimer

This application provides educational information only and should not replace professional medical advice. Always consult healthcare providers for medical decisions.

## 📄 License

MIT License - see LICENSE file for details

---

Built with ❤️ for breast cancer patients and their families

