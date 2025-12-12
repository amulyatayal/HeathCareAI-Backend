# 🏥 Healthcare Companion AI - Design Document

**Version:** 2.0  
**Date:** December 2025  
**Author:** Healthcare AI Team

---

## 📋 Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Backend Design](#3-backend-design)
4. [Frontend Design](#4-frontend-design)
5. [Data Architecture](#5-data-architecture)
6. [API Specification](#6-api-specification)
7. [Security & Compliance](#7-security--compliance)
8. [Deployment Architecture](#8-deployment-architecture)
9. [Future Roadmap](#9-future-roadmap)

---

## 1. Executive Summary

### 1.1 Purpose

A compassionate AI-powered healthcare companion designed to support breast cancer patients by providing accurate medical information, emotional support, and resource access.

### 1.2 Key Features

- 🤖 **AI Chat Assistant** - Empathetic, knowledge-grounded conversations
- 📚 **Knowledge Base** - 100+ medical leaflets and Q&A content
- 🔍 **Hybrid Search** - Vector + keyword search for accurate retrieval
- 📄 **Resource Library** - PDF leaflets with direct patient access
- 🔐 **Session Management** - Continuous conversation context

### 1.3 Tech Stack Overview

| Layer | Technology |
|-------|------------|
| **Frontend** | React/Next.js, TailwindCSS, TypeScript |
| **Backend** | Python, FastAPI, Pydantic |
| **AI/ML** | AWS Bedrock (Nova Pro, Titan Embeddings) |
| **Search** | Amazon OpenSearch Serverless (Hybrid) |
| **Storage** | Amazon S3 (PDFs), CloudFront (CDN) |
| **Infrastructure** | AWS (EC2/ECS), Docker, Nginx |

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (React/Next.js)                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Chat        │  │ Resource    │  │ Search      │  │ Profile/Session     │ │
│  │ Interface   │  │ Library     │  │ Interface   │  │ Management          │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼ HTTPS/REST API
┌─────────────────────────────────────────────────────────────────────────────┐
│                              API GATEWAY (Nginx/ALB)                         │
│                      Rate Limiting, SSL Termination, CORS                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI - Python)                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Chat        │  │ Knowledge   │  │ Health      │  │ Document            │ │
│  │ Router      │  │ Router      │  │ Router      │  │ Ingestion           │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────────┘ │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                          SERVICES LAYER                                  ││
│  │  ┌───────────────┐  ┌───────────────┐  ┌───────────────────────────────┐││
│  │  │ AI Agent      │  │ Knowledge     │  │ PDF Processor + S3 Uploader   │││
│  │  │ Service       │  │ Base Service  │  │ Service                       │││
│  │  └───────────────┘  └───────────────┘  └───────────────────────────────┘││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
           │                    │                         │
           ▼                    ▼                         ▼
┌─────────────────┐  ┌─────────────────────┐  ┌─────────────────────────────┐
│  AWS BEDROCK    │  │  OPENSEARCH         │  │  AMAZON S3 + CloudFront     │
│  ───────────────│  │  SERVERLESS         │  │  ─────────────────────────  │
│  • Nova Pro     │  │  ─────────────────  │  │  • PDF Storage              │
│  • Titan Embed  │  │  • Vector Index     │  │  • Public URLs              │
│                 │  │  • Hybrid Search    │  │  • CDN Distribution         │
└─────────────────┘  └─────────────────────┘  └─────────────────────────────┘
```

### 2.2 Data Flow - Chat Request

```
User Message
     │
     ▼
┌──────────────────┐
│ 1. Classify      │ ──▶ Query Category (symptoms, treatment, etc.)
│    Query         │
└──────────────────┘
     │
     ▼
┌──────────────────┐
│ 2. Hybrid        │ ──▶ Create query embedding
│    Search        │ ──▶ Vector + Keyword search
└──────────────────┘ ──▶ Return top 5 sources
     │
     ▼
┌──────────────────┐
│ 3. Build         │ ──▶ System prompt + Context + History + Query
│    Prompt        │
└──────────────────┘
     │
     ▼
┌──────────────────┐
│ 4. Generate      │ ──▶ Call Bedrock (Nova Pro / Claude)
│    Response      │ ──▶ Return empathetic answer
└──────────────────┘
     │
     ▼
┌──────────────────┐
│ 5. Format        │ ──▶ Add sources, confidence, disclaimer
│    Response      │ ──▶ Save to session history
└──────────────────┘
     │
     ▼
  ChatResponse
```

### 2.3 PDF Ingestion Pipeline

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   PDF Files     │────▶│   S3 Bucket     │────▶│  Public URLs    │
│  (data/raw/)    │     │  (with CDN)     │     │  (for patients) │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │
         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Extract Text   │────▶│  AI Generates   │────▶│  OpenSearch     │
│  (PyPDF2)       │     │  Q&A Pairs      │     │  Knowledge Base │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

---

## 3. Backend Design

### 3.1 Project Structure

```
healthcare-ai-backend/
├── main.py                 # FastAPI application entry point
├── config/
│   ├── __init__.py
│   ├── settings.py         # Environment configuration
│   └── aws.py              # AWS client factories
├── api/
│   ├── __init__.py
│   └── routes.py           # API endpoint definitions
├── models/
│   ├── __init__.py
│   └── schemas.py          # Pydantic request/response models
├── services/
│   ├── __init__.py
│   ├── ai_agent.py         # AI chat logic + session management
│   ├── knowledge_base.py   # OpenSearch hybrid search
│   ├── pdf_processor.py    # PDF text extraction (PLANNED)
│   └── s3_uploader.py      # S3 upload + URL generation (PLANNED)
├── scripts/
│   ├── ingest_qa_data.py   # Q&A ingestion script
│   └── ingest_pdf_knowledge.py  # PDF ingestion pipeline (PLANNED)
├── data/
│   └── sample/
│       ├── raw/            # 103 PDF leaflets
│       └── SampleQ&A-1     # 126 Q&A pairs
├── tests/
├── requirements.txt
└── Dockerfile
```

### 3.2 Core Services

#### 3.2.1 AI Agent Service (`services/ai_agent.py`)

**Classes:**

| Class | Responsibility |
|-------|----------------|
| `BreastCancerCompanionAgent` | Format prompts, call Bedrock, calculate confidence |
| `SessionManager` | Create/retrieve sessions, store history (10 messages) |

**Key Features:**
- Multi-model support (Amazon Nova, Anthropic Claude)
- Conversation memory (last 10 messages per session)
- Query classification (9 categories)
- Confidence scoring based on sources and response quality

**Query Classification Keywords:**

```python
QUERY_CATEGORIES = {
    "symptoms": ["symptom", "pain", "lump", "discharge", "swelling"],
    "treatment": ["treatment", "surgery", "mastectomy", "radiation", "chemo"],
    "medication": ["medicine", "medication", "drug", "tamoxifen", "herceptin"],
    "side_effects": ["side effect", "nausea", "hair loss", "fatigue"],
    "lifestyle": ["exercise", "diet", "sleep", "work", "travel"],
    "emotional_support": ["scared", "anxious", "depressed", "cope", "support"],
    "nutrition": ["food", "eat", "diet", "nutrition", "supplement"],
    "follow_up_care": ["follow up", "checkup", "scan", "mammogram", "recurrence"]
}
```

#### 3.2.2 Knowledge Base Service (`services/knowledge_base.py`)

**Classes:**

| Class | Responsibility |
|-------|----------------|
| `EmbeddingService` | Generate embeddings using Titan |
| `KnowledgeBaseService` | Add/delete documents, hybrid search |

**Hybrid Search Configuration:**

```python
VECTOR_WEIGHT = 0.7   # Semantic similarity (meaning)
KEYWORD_WEIGHT = 0.3  # Exact term matching
```

**Search Query Structure:**

```python
hybrid_query = {
    "query": {
        "bool": {
            "should": [
                # Vector search (semantic)
                {"knn": {"embedding": {"vector": query_embedding, "k": limit}}},
                # Keyword search (exact)
                {"multi_match": {"query": query, "fields": ["title^3", "content"]}}
            ],
            "minimum_should_match": 1
        }
    }
}
```

#### 3.2.3 PDF Processor Service (PLANNED)

```python
class PDFProcessor:
    """
    Responsibilities:
    - Extract text from PDFs using PyPDF2/pdfplumber
    - Chunk content intelligently (by section/page)
    - Generate Q&A pairs using AI (Bedrock)
    - Handle multi-language PDFs
    """
    
    def extract_text(self, pdf_path: str) -> str: ...
    def chunk_content(self, text: str, chunk_size: int = 1000) -> List[str]: ...
    async def generate_qa_pairs(self, content: str) -> List[Dict]: ...
```

#### 3.2.4 S3 Uploader Service (PLANNED)

```python
class S3Uploader:
    """
    Responsibilities:
    - Upload PDFs to S3 with organized structure
    - Generate public URLs or presigned URLs
    - Manage CloudFront distribution
    """
    
    def upload_pdf(self, file_path: str, category: str) -> str: ...
    def get_public_url(self, s3_key: str) -> str: ...
    def delete_file(self, s3_key: str) -> bool: ...
```

### 3.3 System Prompt

The AI agent uses a carefully crafted system prompt:

```
You are a compassionate and knowledgeable healthcare companion AI assistant 
specializing in breast cancer support.

## Your Guidelines:

### 1. EMPATHY FIRST
- Always acknowledge the emotional aspect of the patient's journey
- Use warm, supportive language
- Recognize that every patient's experience is unique

### 2. ACCURATE INFORMATION
- Provide evidence-based information from reliable medical sources
- Cite the knowledge base sources when available
- Be clear about what is general information vs. specific medical advice

### 3. SAFETY BOUNDARIES
- NEVER provide specific treatment recommendations or medication dosages
- ALWAYS encourage consulting with healthcare providers for medical decisions
- Clearly state when a question requires professional medical consultation

### 4. TOPICS YOU CAN HELP WITH:
- Understanding breast cancer types and stages
- Explaining common treatments
- Managing side effects and symptoms
- Emotional support and coping strategies
- Nutrition and lifestyle guidance
- Questions about follow-up care
- Connecting with support resources

### 5. ALWAYS INCLUDE DISCLAIMER
End responses with a reminder that this information is educational only.
```

---

## 4. Frontend Design

### 4.1 Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Framework** | Next.js 14 (App Router) | SSR, routing, API routes |
| **UI Library** | React 18 | Component architecture |
| **Styling** | TailwindCSS + shadcn/ui | Utility-first CSS |
| **State** | React Query + Zustand | Server/client state |
| **Forms** | React Hook Form + Zod | Form validation |
| **Icons** | Lucide React | Icon library |
| **Animation** | Framer Motion | Micro-interactions |

### 4.2 Page Structure

```
app/
├── layout.tsx              # Root layout with navigation
├── page.tsx                # Landing/home page
├── chat/
│   └── page.tsx            # Main chat interface
├── resources/
│   ├── page.tsx            # Resource library (PDF leaflets)
│   └── [category]/page.tsx # Category-filtered resources
├── search/
│   └── page.tsx            # Knowledge base search
└── about/
    └── page.tsx            # About + disclaimer page
```

### 4.3 Component Architecture

```
components/
├── chat/
│   ├── ChatContainer.tsx     # Main chat wrapper
│   ├── MessageList.tsx       # Message history display
│   ├── MessageBubble.tsx     # Individual message (user/assistant)
│   ├── ChatInput.tsx         # Input with send button
│   ├── SourceCard.tsx        # Citation display
│   ├── TypingIndicator.tsx   # AI thinking animation
│   └── SessionInfo.tsx       # Session metadata display
├── resources/
│   ├── ResourceGrid.tsx      # PDF card grid
│   ├── ResourceCard.tsx      # Individual PDF card
│   ├── CategoryFilter.tsx    # Category sidebar/tabs
│   ├── PDFViewer.tsx         # Embedded PDF viewer modal
│   └── DownloadButton.tsx    # PDF download action
├── search/
│   ├── SearchBar.tsx         # Search input with filters
│   ├── ResultsList.tsx       # Search results
│   └── ResultCard.tsx        # Individual result
├── layout/
│   ├── Header.tsx            # Navigation header
│   ├── Sidebar.tsx           # Mobile sidebar
│   ├── Footer.tsx            # Footer with disclaimer
│   └── MobileNav.tsx         # Bottom navigation (mobile)
└── ui/
    ├── Button.tsx
    ├── Card.tsx
    ├── Input.tsx
    ├── Modal.tsx
    └── (shadcn components)
```

### 4.4 UI/UX Design Principles

#### 4.4.1 Design Language

| Aspect | Choice | Rationale |
|--------|--------|-----------|
| **Primary Color** | Soft Teal `#0D9488` | Calming, medical, trustworthy |
| **Accent Color** | Warm Coral `#F97316` | Warmth, hope, breast cancer awareness |
| **Background** | Light Cream `#FFFBF5` | Warm, welcoming, easy on eyes |
| **Text Primary** | Dark Gray `#1F2937` | High contrast, readable |
| **Text Secondary** | Medium Gray `#6B7280` | Supporting text |
| **Font Family** | Source Sans Pro | Medical clarity, accessibility |
| **Tone** | Warm, empathetic | Supportive healthcare context |

#### 4.4.2 Chat Interface Wireframe

```
┌─────────────────────────────────────────────────────────────┐
│  🏥 Healthcare Companion                           [≡] [?]  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ 👋 Hello! I'm here to support you on your journey.  │   │
│  │ Feel free to ask me anything about breast cancer.   │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│         ┌─────────────────────────────────────────────┐    │
│         │ Why am I so tired after chemotherapy?       │    │
│         └─────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ I understand how exhausting this can be. Fatigue   │   │
│  │ is very common during chemotherapy and usually     │   │
│  │ improves after treatment ends.                     │   │
│  │                                                     │   │
│  │ ### Tips to Manage Fatigue:                        │   │
│  │ - Rest when you need to                            │   │
│  │ - Light exercise like walking                      │   │
│  │ - Stay hydrated                                    │   │
│  │                                                     │   │
│  │ 📚 Sources:                                        │   │
│  │ ├─ Managing Fatigue During Treatment    [View PDF] │   │
│  │ └─ Chemotherapy Side Effects Guide      [View PDF] │   │
│  │                                                     │   │
│  │ ⚕️ Confidence: 85%                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────┐  ┌─────────────┐  │
│  │ Type your question...               │  │   Send  ▶   │  │
│  └─────────────────────────────────────┘  └─────────────┘  │
│                                                             │
│  ⚠️ This is for educational purposes only. Please consult  │
│     your healthcare provider for medical advice.           │
└─────────────────────────────────────────────────────────────┘
```

#### 4.4.3 Resource Library Wireframe

```
┌─────────────────────────────────────────────────────────────┐
│  📚 Resource Library                          🔍 Search...  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Categories:                                                │
│  ┌──────┐ ┌─────────┐ ┌────────────┐ ┌──────────┐ ┌──────┐ │
│  │ All  │ │Treatment│ │Side Effects│ │Medication│ │ More │ │
│  └──────┘ └─────────┘ └────────────┘ └──────────┘ └──────┘ │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ 📄              │  │ 📄              │  │ 📄           │ │
│  │                 │  │                 │  │              │ │
│  │ Chemotherapy    │  │ Managing        │  │ Your Body    │ │
│  │ for Breast      │  │ Fatigue         │  │ After        │ │
│  │ Cancer          │  │                 │  │ Surgery      │ │
│  │                 │  │                 │  │              │ │
│  │ Treatment       │  │ Side Effects    │  │ Treatment    │ │
│  │ ─────────────── │  │ ─────────────── │  │ ──────────── │ │
│  │ [View] [↓]     │  │ [View] [↓]     │  │ [View] [↓]  │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ 📄              │  │ 📄              │  │ 📄           │ │
│  │                 │  │                 │  │              │ │
│  │ Tamoxifen       │  │ Diet and        │  │ Emotional    │ │
│  │ Information     │  │ Breast Cancer   │  │ Support      │ │
│  │                 │  │                 │  │              │ │
│  │ Medication      │  │ Nutrition       │  │ Support      │ │
│  │ ─────────────── │  │ ─────────────── │  │ ──────────── │ │
│  │ [View] [↓]     │  │ [View] [↓]     │  │ [View] [↓]  │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
│                                                             │
│  Showing 1-6 of 103 resources              [< 1 2 3 ... >] │
└─────────────────────────────────────────────────────────────┘
```

### 4.5 Mobile Responsiveness

| Breakpoint | Width | Layout Changes |
|------------|-------|----------------|
| `sm` | 640px | Stack cards, full-width input |
| `md` | 768px | 2-column grid, sidebar visible |
| `lg` | 1024px | 3-column grid, expanded sidebar |
| `xl` | 1280px | Max-width container, spacious |

**Mobile-Specific Features:**
- Bottom navigation bar
- Swipe gestures for categories
- Floating action button for new chat
- Collapsible message sources

### 4.6 Accessibility (a11y)

| Feature | Implementation |
|---------|----------------|
| Keyboard navigation | Full tab support, focus indicators |
| Screen readers | ARIA labels, semantic HTML |
| Color contrast | WCAG AA compliant (4.5:1 minimum) |
| Font sizing | rem-based, respects user preferences |
| Motion | Respects `prefers-reduced-motion` |

---

## 5. Data Architecture

### 5.1 OpenSearch Index Schema

```json
{
  "index": "breast_cancer_knowledge",
  "settings": {
    "index": {
      "knn": true,
      "number_of_shards": 2,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "document_id": { "type": "keyword" },
      "title": { 
        "type": "text", 
        "analyzer": "standard",
        "fields": {
          "keyword": { "type": "keyword" }
        }
      },
      "content": { 
        "type": "text", 
        "analyzer": "standard" 
      },
      "content_type": { "type": "keyword" },
      "category": { "type": "keyword" },
      "source_url": { "type": "keyword" },
      "author": { "type": "text" },
      "published_date": { "type": "date" },
      "tags": { "type": "keyword" },
      "embedding": {
        "type": "knn_vector",
        "dimension": 1024,
        "method": {
          "name": "hnsw",
          "space_type": "cosinesimil",
          "engine": "faiss",
          "parameters": {
            "ef_construction": 512,
            "m": 16
          }
        }
      },
      "created_at": { "type": "date" },
      "updated_at": { "type": "date" }
    }
  }
}
```

### 5.2 S3 Bucket Structure

```
s3://healthcare-ai-documents/
├── leaflets/
│   ├── treatment/
│   │   ├── bcc17-chemotherapy-for-breast-cancer-web.pdf
│   │   ├── bcc26-radiotherapy-for-primary-breast-cancer.pdf
│   │   ├── bcc7-breast-reconstruction-booklet.pdf
│   │   └── ...
│   ├── medication/
│   │   ├── bcc20-tamoxifen-web.pdf
│   │   ├── bcc41-trastuzumab.pdf
│   │   ├── bcc64-letrozole.pdf
│   │   └── ...
│   ├── side-effects/
│   │   ├── bcc54-breast-cancer-and-hairloss.pdf
│   │   ├── bcc18-menopausal-symptoms.pdf
│   │   └── ...
│   ├── lifestyle/
│   │   ├── bcc6-exercises-after-surgery.pdf
│   │   ├── bcc98-diet-and-breast-cancer.pdf
│   │   └── ...
│   └── emotional-support/
│       ├── bcc110-your-body-intimacy-and-sex.pdf
│       ├── bcc120-when-your-partner-has-cancer.pdf
│       └── ...
├── qa-exports/
│   └── qa-pairs-backup.json
└── uploads/
    └── user-documents/
```

### 5.3 Content Types

| Type | Description | Source | Count |
|------|-------------|--------|-------|
| `faq` | Q&A pairs | SampleQ&A-1 file | 126 |
| `medical_article` | Long-form content | PDF leaflets | ~100 |
| `patient_guide` | Step-by-step guides | PDF leaflets | ~30 |
| `research_summary` | Research highlights | Curated | TBD |
| `support_resource` | Support group info | External | TBD |

### 5.4 Query Categories

| Category | Description | Example Questions |
|----------|-------------|-------------------|
| `symptoms` | Signs and symptoms | "What does a lump feel like?" |
| `treatment` | Treatment options | "What is a lumpectomy?" |
| `medication` | Drugs and therapies | "Side effects of tamoxifen?" |
| `side_effects` | Managing side effects | "Why am I so tired?" |
| `lifestyle` | Daily life questions | "Can I travel during chemo?" |
| `emotional_support` | Mental health | "I'm scared it will come back" |
| `nutrition` | Diet and food | "What foods help during treatment?" |
| `follow_up_care` | Post-treatment | "How often do I need scans?" |
| `general` | Other questions | (fallback category) |

---

## 6. API Specification

### 6.1 Endpoints Summary

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/chat/` | Send message to AI | Optional |
| `DELETE` | `/api/v1/chat/session/{id}` | Clear session | Optional |
| `POST` | `/api/v1/knowledge/search` | Search knowledge base | Optional |
| `POST` | `/api/v1/knowledge/document` | Add document | Admin |
| `DELETE` | `/api/v1/knowledge/document/{id}` | Delete document | Admin |
| `GET` | `/api/v1/knowledge/stats` | Get KB statistics | Optional |
| `GET` | `/api/v1/health/` | Health check | Public |
| `GET` | `/api/v1/health/ping` | Simple ping | Public |
| `GET` | `/api/v1/categories/query` | List categories | Public |
| `GET` | `/api/v1/categories/content` | List content types | Public |

### 6.2 Chat API

#### Request

```http
POST /api/v1/chat/
Content-Type: application/json

{
  "message": "Why am I so tired after chemotherapy?",
  "session_id": "abc123-def456-...",
  "user_id": "user_001",
  "include_sources": true
}
```

#### Response

```json
{
  "answer": "I understand how exhausting this can be. Fatigue is very common during chemotherapy and is one of the most reported side effects...\n\n### Tips to Manage Fatigue:\n- Rest when you need to\n- Light exercise like walking can help\n- Stay well hydrated\n- Eat small, nutritious meals\n\nPlease remember to discuss persistent fatigue with your healthcare team, as they can check for treatable causes like anemia.\n\n*This information is for educational purposes only. Please consult your healthcare provider for personalized advice.*",
  "session_id": "abc123-def456-...",
  "query_category": "side_effects",
  "sources": [
    {
      "title": "What can I do to manage fatigue during and after treatment?",
      "content_type": "faq",
      "relevance_score": 0.92,
      "source_url": "https://cdn.healthcare-ai.com/leaflets/managing-fatigue.pdf",
      "excerpt": "Fatigue is very common and can feel frustrating, but it usually improves gradually..."
    },
    {
      "title": "Chemotherapy for Breast Cancer",
      "content_type": "patient_guide",
      "relevance_score": 0.87,
      "source_url": "https://cdn.healthcare-ai.com/leaflets/chemotherapy-guide.pdf",
      "excerpt": "Side effects of chemotherapy vary but commonly include fatigue, nausea..."
    }
  ],
  "confidence_score": 0.85,
  "response_time_ms": 3250.5,
  "disclaimer": "This information is for educational purposes only and should not replace professional medical advice. Please consult your healthcare provider for personalized guidance."
}
```

### 6.3 Knowledge Search API

#### Request

```http
POST /api/v1/knowledge/search
Content-Type: application/json

{
  "query": "hair loss during treatment",
  "category": "side_effects",
  "content_type": "faq",
  "limit": 10
}
```

#### Response

```json
{
  "results": [
    {
      "document_id": "qa_054",
      "title": "Will I definitely lose my hair during chemotherapy?",
      "content_excerpt": "Hair loss depends on the type and dose of chemotherapy...",
      "relevance_score": 0.94,
      "content_type": "faq",
      "category": "side_effects",
      "source_url": null
    }
  ],
  "total_results": 5,
  "search_time_ms": 125.3
}
```

### 6.4 Health Check API

#### Response

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "services": [
    {
      "name": "bedrock",
      "status": "healthy",
      "latency_ms": 150,
      "message": "Bedrock client initialized"
    },
    {
      "name": "opensearch",
      "status": "healthy",
      "latency_ms": 45,
      "message": "Cluster status: green"
    },
    {
      "name": "s3",
      "status": "healthy",
      "latency_ms": null,
      "message": "S3 client initialized"
    }
  ],
  "timestamp": "2025-12-11T10:30:00Z"
}
```

---

## 7. Security & Compliance

### 7.1 Security Measures

| Layer | Measure | Implementation |
|-------|---------|----------------|
| **Transport** | TLS 1.3 | HTTPS only, SSL certificates |
| **API Gateway** | Rate limiting | 100 req/min per IP |
| **Authentication** | JWT tokens | (Phase 2) |
| **Authorization** | Role-based | Admin vs User (Phase 2) |
| **Data at Rest** | Encryption | S3 SSE, OpenSearch encryption |
| **Secrets** | Secure storage | AWS Secrets Manager / env vars |
| **CORS** | Restricted origins | Whitelist frontend domains |

### 7.2 Healthcare Compliance

| Requirement | Implementation |
|-------------|----------------|
| **Medical Disclaimer** | Included in every AI response |
| **No PII Storage** | Sessions are anonymous by default |
| **Medical Advice Boundary** | Explicit in system prompt |
| **Content Verification** | Sources from verified organizations |
| **Audit Logging** | Request/response logging (no PII) |

### 7.3 Content Safety Guidelines

The AI agent has explicit boundaries:

**❌ NEVER:**
- Provide specific treatment recommendations
- Suggest medication dosages
- Diagnose conditions
- Replace professional medical advice

**✅ ALWAYS:**
- Encourage consulting healthcare providers
- Include educational disclaimer
- Cite knowledge base sources
- Acknowledge emotional aspects

### 7.4 Data Retention

| Data Type | Retention | Notes |
|-----------|-----------|-------|
| Chat sessions | 24 hours | In-memory, cleared on restart |
| Knowledge base | Permanent | Versioned content |
| Access logs | 30 days | No PII stored |
| Error logs | 7 days | Masked sensitive data |

---

## 8. Deployment Architecture

### 8.1 AWS Infrastructure

```
                                   ┌─────────────────┐
                                   │   CloudFront    │
                                   │   (CDN)         │
                                   │   - PDF caching │
                                   │   - SSL         │
                                   └────────┬────────┘
                                            │
┌─────────────────┐                         │
│   Route 53      │◀────────────────────────┤
│   (DNS)         │                         │
│   - A records   │                         │
│   - Health chk  │                         │
└────────┬────────┘                         │
         │                                  │
         ▼                                  ▼
┌─────────────────┐                ┌─────────────────┐
│   ALB           │                │   S3 Bucket     │
│   (Load         │                │   ─────────────  │
│   Balancer)     │                │   • PDF storage │
│   - SSL term    │                │   • Static files│
│   - Health chk  │                │   • Versioning  │
└────────┬────────┘                └─────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│   ECS Cluster / EC2 Auto Scaling Group              │
│   ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│   │ Container 1 │  │ Container 2 │  │ Container N│ │
│   │ FastAPI     │  │ FastAPI     │  │ FastAPI    │ │
│   │ Python 3.12 │  │ Python 3.12 │  │ Python 3.12│ │
│   └─────────────┘  └─────────────┘  └────────────┘ │
│                                                     │
│   Auto Scaling: 2-10 instances                     │
│   CPU threshold: 70%                               │
└─────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌─────────────────┐  ┌─────────────────┐
│ AWS Bedrock     │  │ OpenSearch      │
│ ─────────────── │  │ Serverless      │
│ • Nova Pro      │  │ ─────────────── │
│ • Titan Embed   │  │ • Vector search │
│ • us-east-1     │  │ • 2 shards      │
└─────────────────┘  └─────────────────┘
```

### 8.2 Environment Variables

```bash
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...

# OpenSearch
OPENSEARCH_ENDPOINT=xxx.us-east-1.aoss.amazonaws.com
OPENSEARCH_INDEX=breast_cancer_knowledge

# Bedrock
BEDROCK_MODEL_ID=amazon.nova-pro-v1:0
BEDROCK_EMBEDDING_MODEL=amazon.titan-embed-text-v2:0

# S3
S3_BUCKET_NAME=healthcare-ai-documents
S3_REGION=us-east-1

# Application
APP_ENV=production
DEBUG=false
LOG_LEVEL=INFO
API_HOST=0.0.0.0
API_PORT=8000

# CORS
ALLOWED_ORIGINS=https://healthcare-companion.com,https://www.healthcare-companion.com
```

### 8.3 Docker Configuration

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Run with uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8.4 CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: pytest tests/

  deploy:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to ECS
        run: |
          aws ecs update-service \
            --cluster healthcare-ai \
            --service backend \
            --force-new-deployment
```

---

## 9. Future Roadmap

### Phase 1: MVP (Current) ✅

- [x] AI chat with AWS Bedrock (Nova Pro)
- [x] Knowledge base with hybrid search
- [x] Q&A ingestion pipeline (126 pairs)
- [x] Session management (in-memory)
- [x] Health check endpoints
- [x] Multi-model support (Nova + Claude)

### Phase 2: Q1 2025

- [ ] **PDF Ingestion Pipeline**
  - PDF text extraction
  - AI-generated Q&A pairs
  - S3 upload with public URLs
  - Batch processing for 103 PDFs

- [ ] **Frontend MVP**
  - Next.js application
  - Chat interface
  - Resource library
  - Mobile responsive

- [ ] **User Authentication**
  - JWT-based auth
  - User profiles
  - Session persistence

### Phase 3: Q2 2025

- [ ] **Streaming Responses**
  - Server-Sent Events (SSE)
  - Real-time typing effect
  - Reduced perceived latency

- [ ] **Enhanced Search**
  - Faceted search
  - Search suggestions
  - Query expansion

- [ ] **Analytics Dashboard**
  - Usage metrics
  - Popular questions
  - User satisfaction

### Phase 4: Q3 2025

- [ ] **Multi-language Support**
  - Translation pipeline
  - Language detection
  - Localized content

- [ ] **Voice Interface**
  - Speech-to-text input
  - Text-to-speech output
  - Accessibility enhancement

- [ ] **Mobile App**
  - React Native
  - Push notifications
  - Offline support

### Phase 5: Q4 2025

- [ ] **Personalization**
  - User treatment stage
  - Saved resources
  - Custom recommendations

- [ ] **Care Team Features**
  - Share with doctor
  - Appointment reminders
  - Treatment timeline

- [ ] **Integration APIs**
  - EHR integration
  - Telehealth platforms
  - Patient portals

---

## 📎 Appendix

### A. PDF Content Inventory (103 files)

| Category | Count | Examples |
|----------|-------|----------|
| Treatment | 25 | Chemotherapy, Radiation, Surgery guides |
| Medication | 15 | Tamoxifen, Herceptin, Letrozole |
| Side Effects | 18 | Fatigue, Hair loss, Nausea, Lymphoedema |
| Lifestyle | 12 | Exercise, Diet, Travel, Work |
| Emotional | 10 | Coping, Partner support, Body image |
| Know Your Breasts | 15 | Multi-language awareness guides |
| Secondary Cancer | 8 | Bone, Liver, Lung, Brain metastases |

### B. Performance Targets

| Metric | Target | Current |
|--------|--------|---------|
| Chat response time | < 5s | ~5.5s |
| Search latency | < 500ms | ~600ms |
| Uptime | 99.9% | TBD |
| Concurrent users | 1,000 | TBD |
| Knowledge base size | 10,000 docs | 126 |

### C. Monitoring & Alerting

| Metric | Threshold | Action |
|--------|-----------|--------|
| Error rate | > 1% | PagerDuty alert |
| Latency P95 | > 10s | Slack notification |
| CPU usage | > 80% | Auto-scale |
| Memory usage | > 85% | Alert + investigate |
| OpenSearch errors | Any | Immediate alert |

---

*Document maintained by Healthcare AI Team*  
*Last updated: December 2025*

