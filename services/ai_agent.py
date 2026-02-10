"""
AI Agent Service for Breast Cancer Patient Queries
Uses AWS Bedrock for AI responses and OpenSearch for knowledge retrieval
"""

import json
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import uuid

from config import settings, bedrock
from models.schemas_rag import (
    ChatMessage, ChatResponse, SourceCitation,
    QueryCategory, ContentType, MessageRole
)

logger = logging.getLogger(__name__)


# ================================
# System Prompts
# ================================

# Legacy prompt for general conversations (kept for backward compatibility)
BREAST_CANCER_COMPANION_PROMPT = """You are a compassionate and knowledgeable healthcare companion AI assistant specializing in breast cancer support. Your role is to provide accurate, empathetic, and helpful information to breast cancer patients and their caregivers.

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

### 4. RESPONSE STRUCTURE
- Start with acknowledgment of the patient's concern
- Provide clear, organized information
- End with supportive guidance and next steps

### 5. TOPICS YOU CAN HELP WITH:
- Understanding breast cancer types and stages
- Explaining common treatments (surgery, chemotherapy, radiation, hormone therapy)
- Managing side effects and symptoms
- Emotional support and coping strategies
- Nutrition and lifestyle guidance
- Questions about follow-up care
- Connecting with support resources

### 6. ALWAYS INCLUDE DISCLAIMER
End responses with a reminder that this information is educational and patients should consult their healthcare team for personalized advice.

## Knowledge Base Context:
{context}

## Conversation History:
{conversation_history}

## Current Question:
{question}

Please provide a helpful, empathetic response:"""


# ================================
# STRICT RAG PROMPT (Evidence-Based Only)
# ================================

STRICT_RAG_PROMPT = """You are a compassionate healthcare companion AI assistant specializing in breast cancer support. You provide accurate, empathetic information to patients and caregivers.

## CRITICAL RULES:
1. **ONLY use information from the provided source chunks below**
2. **DO NOT add any information from your training data**
3. **DO NOT make up, infer, or extrapolate beyond what is explicitly stated**
4. **Be warm, supportive, and acknowledge the patient's concerns**
5. **If the answer is not in the sources, say you don't have that information**

## FORMATTING STYLE:
- Use emojis to make responses warm and friendly:
  💜 for empathy and support statements
  ✨ for tips, positive points, or highlights
  📋 for lists or step-by-step guidance
  ⚠️ for important warnings or cautions
  💪 for encouragement and motivation
  🏥 for medical/clinical information
  🤗 for emotional support moments
- Use **bold** for key terms and important points
- Use bullet points and numbered lists for clarity
- Keep a warm, conversational, supportive tone throughout
- Start responses with an empathetic emoji (💜 or 🤗)

## RESPONSE FORMAT:

### ANSWER
Start with an empathetic emoji and acknowledgment of the patient's question.
Then provide your answer based ONLY on the source chunks.
Organize the information clearly with headings, bullet points, and appropriate emojis.
End with an encouraging note using 💪 or 🤗.
DO NOT include any disclaimer (it's added separately).

After a line with just "---" provide source summaries:

### SOURCES CONSULTED
For each source document you used, write one line in this format:
- 📄 **[Document Name]**: Brief summary of what information was found (1-2 sentences)

## SOURCE CHUNKS:
{chunks}

## PATIENT QUESTION:
{question}

## YOUR RESPONSE:"""


# Insufficient evidence response
INSUFFICIENT_EVIDENCE_RESPONSE = """💜 I understand you're looking for information, and I really want to help. Unfortunately, I don't have specific details about this topic in my medical leaflets.

🤗 I know it can be frustrating when you need answers. Here's what I'd suggest:

🏥 **Your healthcare team is best placed to help:**
- 👩‍⚕️ Your breast care nurse can provide personalized guidance
- 🩺 Your oncologist or surgeon can answer treatment-specific questions
- 💊 Your GP is available for general health concerns

📞 **Additional support:**
- Breast Cancer Now's free helpline: **0808 800 6000** (staffed by nurses and trained staff)
- They offer confidential support and can answer many questions

💪 Please don't hesitate to reach out to these resources - you're not alone in this journey!

I'm here to help with questions about breast cancer topics covered in my knowledge base - things like treatments, side effects, exercises, emotional support, and recovery. Is there something else I can help you with?

---
*Please always consult your healthcare team for advice specific to your situation.*"""


# ================================
# Query Classification
# ================================

QUERY_CATEGORIES = {
    "symptoms": ["symptom", "pain", "lump", "discharge", "swelling", "fatigue", "tired", "ache"],
    "treatment": ["treatment", "surgery", "mastectomy", "lumpectomy", "radiation", "chemo", "therapy"],
    "medication": ["medicine", "medication", "drug", "tamoxifen", "herceptin", "dose", "prescription"],
    "side_effects": ["side effect", "nausea", "hair loss", "fatigue", "vomiting", "pain", "reaction"],
    "lifestyle": ["exercise", "diet", "sleep", "work", "travel", "activity", "daily life"],
    "emotional_support": ["scared", "anxious", "depressed", "worried", "cope", "support", "family", "feeling"],
    "nutrition": ["food", "eat", "diet", "nutrition", "supplement", "vitamin", "weight"],
    "follow_up_care": ["follow up", "checkup", "scan", "mammogram", "monitoring", "recurrence", "survivor"]
}


def classify_query(query: str) -> QueryCategory:
    """Classify the user's query into a category"""
    query_lower = query.lower()
    
    scores = {}
    for category, keywords in QUERY_CATEGORIES.items():
        score = sum(1 for keyword in keywords if keyword in query_lower)
        scores[category] = score
    
    if max(scores.values()) > 0:
        best_category = max(scores, key=scores.get)
        return QueryCategory(best_category)
    
    return QueryCategory.GENERAL


# ================================
# Session Management
# ================================

class SessionManager:
    """Manages conversation sessions"""
    
    _sessions: Dict[str, Dict[str, Any]] = {}
    
    @classmethod
    def get_or_create_session(cls, session_id: Optional[str] = None) -> str:
        """Get existing session or create new one"""
        if session_id and session_id in cls._sessions:
            cls._sessions[session_id]["last_active"] = datetime.utcnow()
            return session_id
        
        new_id = session_id or str(uuid.uuid4())
        cls._sessions[new_id] = {
            "created_at": datetime.utcnow(),
            "last_active": datetime.utcnow(),
            "messages": [],
            "user_id": None
        }
        return new_id
    
    @classmethod
    def add_message(cls, session_id: str, role: str, content: str):
        """Add message to session history"""
        if session_id in cls._sessions:
            cls._sessions[session_id]["messages"].append({
                "role": role,
                "content": content,
                "timestamp": datetime.utcnow().isoformat()
            })
            # Keep only last 10 messages for context
            cls._sessions[session_id]["messages"] = cls._sessions[session_id]["messages"][-10:]
    
    @classmethod
    def get_history(cls, session_id: str, max_messages: int = 5) -> List[Dict[str, str]]:
        """Get recent conversation history"""
        if session_id not in cls._sessions:
            return []
        return cls._sessions[session_id]["messages"][-max_messages:]
    
    @classmethod
    def clear_session(cls, session_id: str):
        """Clear a session"""
        if session_id in cls._sessions:
            del cls._sessions[session_id]


# ================================
# AI Agent
# ================================

class BreastCancerCompanionAgent:
    """AI Agent for breast cancer patient support"""
    
    def __init__(self):
        self.model_id = settings.bedrock_model_id
        self.bedrock_client = None
    
    def _get_client(self):
        """Lazy load Bedrock client"""
        if self.bedrock_client is None:
            self.bedrock_client = bedrock()
        return self.bedrock_client
    
    def _format_conversation_history(self, history: List[Dict[str, str]]) -> str:
        """Format conversation history for prompt"""
        if not history:
            return "No previous conversation."
        
        formatted = []
        for msg in history:
            role = "Patient" if msg["role"] == "user" else "Assistant"
            formatted.append(f"{role}: {msg['content']}")
        
        return "\n".join(formatted)
    
    def _format_context(self, sources: List[Dict[str, Any]]) -> str:
        """Format knowledge base sources for prompt context"""
        if not sources:
            return "No specific knowledge base sources available. Please provide general, evidence-based information."
        
        context_parts = []
        for i, source in enumerate(sources, 1):
            context_parts.append(f"""
Source {i}: {source.get('title', 'Unknown')}
Type: {source.get('content_type', 'article')}
Content: {source.get('content', '')[:500]}...
""")
        
        return "\n".join(context_parts)
    
    def _is_nova_model(self) -> bool:
        """Check if using Amazon Nova model"""
        return 'nova' in self.model_id.lower()
    
    def _is_claude_model(self) -> bool:
        """Check if using Anthropic Claude model"""
        return 'anthropic' in self.model_id.lower() or 'claude' in self.model_id.lower()
    
    async def generate_response(
        self,
        question: str,
        session_id: str,
        knowledge_sources: List[Dict[str, Any]] = None,
        conversation_history: List[Dict[str, str]] = None
    ) -> Tuple[str, float]:
        """
        Generate AI response to patient question
        Supports both Amazon Nova and Anthropic Claude models
        
        Returns:
            Tuple of (response_text, confidence_score)
        """
        start_time = time.time()
        
        # Format prompt
        context = self._format_context(knowledge_sources or [])
        history = self._format_conversation_history(conversation_history or [])
        
        prompt = BREAST_CANCER_COMPANION_PROMPT.format(
            context=context,
            conversation_history=history,
            question=question
        )
        
        try:
            client = self._get_client()
            
            # Build request body based on model type
            if self._is_nova_model():
                # Amazon Nova format
                body = json.dumps({
                    "inferenceConfig": {
                        "max_new_tokens": 1500,
                        "temperature": 0.3
                    },
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": prompt}]
                        }
                    ]
                })
            else:
                # Anthropic Claude format (default)
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1500,
                    "temperature": 0.3,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                })
            
            response = client.invoke_model(
                modelId=self.model_id,
                body=body
            )
            
            response_body = json.loads(response['body'].read())
            
            # Parse response based on model type
            if self._is_nova_model():
                answer = response_body['output']['message']['content'][0]['text']
            else:
                answer = response_body['content'][0]['text']
            
            # Calculate confidence based on response characteristics
            confidence = self._calculate_confidence(answer, knowledge_sources)
            
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"Generated response in {elapsed_ms:.0f}ms with confidence {confidence:.2f}")
            
            return answer, confidence
            
        except Exception as e:
            logger.error(f"Error generating AI response: {e}")
            raise
    
    def _calculate_confidence(
        self,
        response: str,
        sources: List[Dict[str, Any]] = None
    ) -> float:
        """Calculate confidence score for response"""
        confidence = 0.7  # Base confidence
        
        # Increase confidence if sources were used
        if sources and len(sources) > 0:
            confidence += 0.1
        
        # Increase confidence for longer, more detailed responses
        if len(response) > 500:
            confidence += 0.05
        
        # Cap at 0.95 (never claim 100% confidence for medical info)
        return min(confidence, 0.95)
    
    def _format_chunks_for_prompt(self, chunks: List[Dict[str, Any]]) -> str:
        """Format chunks for the strict RAG prompt with clean document names"""
        if not chunks:
            return "No source documents available."
        
        formatted = []
        for i, chunk in enumerate(chunks, 1):
            source_file = chunk.get('source_file', 'Unknown')
            page_start = chunk.get('page_start', '?')
            page_end = chunk.get('page_end', '?')
            section = chunk.get('section', '')
            content = chunk.get('content', '')
            
            # Create clean document name for LLM to reference in source summaries
            clean_name = source_file.replace(".pdf", "").replace("-", " ").replace("_", " ")
            clean_name = clean_name.replace("web pdf", "").replace("web", "").strip()
            clean_name = " ".join(word.capitalize() for word in clean_name.split())
            
            section_text = f"\nSection: {section}" if section else ""
            
            formatted.append(f"""
[Document: {clean_name}]
Pages: {page_start}-{page_end}{section_text}
{content}
""")
        
        return "\n---\n".join(formatted)
    
    async def generate_response_from_chunks(
        self,
        question: str,
        chunks: List[Dict[str, Any]],
        has_sufficient_evidence: bool
    ) -> Tuple[str, float, List[Dict[str, Any]]]:
        """
        Generate response using ONLY the provided chunks (strict RAG).
        Uses temperature=0 for factual accuracy.
        
        Args:
            question: User's question
            chunks: Retrieved chunks with content and metadata
            has_sufficient_evidence: Whether evidence gating passed
        
        Returns:
            Tuple of (response_text, confidence_score, citations)
        """
        start_time = time.time()
        
        # If insufficient evidence, return canned response
        if not has_sufficient_evidence:
            logger.info("Insufficient evidence - returning canned response")
            return INSUFFICIENT_EVIDENCE_RESPONSE, 0.3, []
        
        # Format chunks for prompt
        chunks_text = self._format_chunks_for_prompt(chunks)
        
        prompt = STRICT_RAG_PROMPT.format(
            chunks=chunks_text,
            question=question
        )
        
        try:
            client = self._get_client()
            
            # Build request with temperature=0 for factual responses
            if self._is_nova_model():
                body = json.dumps({
                    "inferenceConfig": {
                        "max_new_tokens": 1500,
                        "temperature": 0.0  # Strictly factual
                    },
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": prompt}]
                        }
                    ]
                })
            else:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1500,
                    "temperature": 0.0,  # Strictly factual
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                })
            
            response = client.invoke_model(
                modelId=self.model_id,
                body=body
            )
            
            response_body = json.loads(response['body'].read())
            
            # Parse response based on model type
            if self._is_nova_model():
                raw_response = response_body['output']['message']['content'][0]['text']
            else:
                raw_response = response_body['content'][0]['text']
            
            # Parse the response to separate answer from source summaries
            answer = raw_response
            source_summaries = {}  # Map document name -> summary
            
            # Try multiple separator patterns
            separators = ["---SOURCES---", "### SOURCES CONSULTED", "## SOURCES CONSULTED", 
                          "### SOURCE SUMMARIES", "## SOURCE SUMMARIES", "SOURCES CONSULTED",
                          "---\n\n### SOURCES", "---\n### SOURCES"]
            
            for sep in separators:
                if sep.lower() in raw_response.lower():
                    # Find the separator case-insensitively
                    lower_response = raw_response.lower()
                    sep_pos = lower_response.find(sep.lower())
                    if sep_pos > 0:
                        answer = raw_response[:sep_pos].strip()
                        summaries_text = raw_response[sep_pos + len(sep):].strip()
                        
                        # Parse source summaries - handle various LLM output formats
                        import re
                        for line in summaries_text.split('\n'):
                            line = line.strip()
                            if not line or line.startswith('#'):
                                continue
                            
                            # Remove leading bullet points and asterisks
                            line = line.lstrip('-').lstrip('*').strip()
                            
                            doc_name = None
                            summary = None
                            
                            # Format: **[Document Name: Actual Name]**: Summary
                            match = re.search(r'\[Document(?:\s+Name)?:\s*([^\]]+)\]', line)
                            if match:
                                doc_name = match.group(1).strip()
                                rest = line[match.end():].strip()
                                summary = rest.lstrip('*:').strip()
                            # Format: **[Doc Name]**: Summary
                            elif '[' in line and ']' in line:
                                start = line.find('[')
                                end = line.find(']')
                                if end > start:
                                    doc_name = line[start+1:end].strip()
                                    summary = line[end+1:].strip().lstrip(':*').strip()
                            # Format: Doc Name: Summary (simple)
                            elif ':' in line and len(line.split(':')[0]) < 80:
                                colon_pos = line.find(':')
                                doc_name = line[:colon_pos].strip().strip('*[]')
                                summary = line[colon_pos+1:].strip()
                            
                            if doc_name and summary and len(doc_name) < 100:
                                source_summaries[doc_name.lower().strip()] = summary
                                logger.debug(f"Parsed: '{doc_name}' -> {summary[:50]}...")
                        break
            
            # Clean up answer - remove section headers
            answer = answer.replace("### Section 1: ANSWER", "").strip()
            answer = answer.replace("## Section 1: ANSWER", "").strip()
            answer = answer.replace("Section 1: ANSWER", "").strip()
            answer = answer.replace("### ANSWER", "").strip()
            answer = answer.replace("## ANSWER", "").strip()
            # Remove trailing --- separator
            if answer.endswith("---"):
                answer = answer[:-3].strip()
            
            logger.info(f"Parsed {len(source_summaries)} source summaries from LLM response")
            
            # Extract citations grouped by source document with full text
            source_docs = {}  # Group chunks by source file
            
            for chunk in chunks:
                source_file = chunk.get('source_file', 'Unknown')
                if source_file not in source_docs:
                    source_docs[source_file] = {
                        "source_file": source_file,
                        "page_start": chunk.get('page_start', 1),
                        "page_end": chunk.get('page_end', 1),
                        "sections": [],
                        "relevance_scores": [],
                        "chunk_contents": []  # Store full chunk content for popup
                    }
                
                # Update page range to cover all chunks from this document
                doc = source_docs[source_file]
                doc["page_start"] = min(doc["page_start"], chunk.get('page_start', 1))
                doc["page_end"] = max(doc["page_end"], chunk.get('page_end', 1))
                
                # Collect sections, scores, and full content
                if chunk.get('section') and chunk['section'] not in doc["sections"]:
                    doc["sections"].append(chunk['section'])
                doc["relevance_scores"].append(chunk.get('relevance_score', 0))
                
                # Store chunk content for popup display
                if chunk.get('content'):
                    doc["chunk_contents"].append(chunk['content'])
            
            # Convert to citations list with full text for popups
            citations = []
            for source_file, doc in source_docs.items():
                avg_score = sum(doc["relevance_scores"]) / len(doc["relevance_scores"]) if doc["relevance_scores"] else 0
                
                # Combine chunk contents for popup (limit to prevent huge payloads)
                combined_text = "\n\n---\n\n".join(doc["chunk_contents"][:5])  # Max 5 chunks per source
                if len(doc["chunk_contents"]) > 5:
                    combined_text += f"\n\n... and {len(doc['chunk_contents']) - 5} more excerpts"
                
                # Create clean document name
                clean_name = source_file.replace(".pdf", "").replace("-", " ").replace("_", " ")
                clean_name = clean_name.replace("web pdf", "").replace("web", "").strip()
                clean_name = " ".join(word.capitalize() for word in clean_name.split())
                
                # Look up LLM-generated summary for this document
                llm_summary = None
                clean_name_lower = clean_name.lower()
                for key, summary in source_summaries.items():
                    # Match by substring to handle slight naming differences
                    if key in clean_name_lower or clean_name_lower in key:
                        llm_summary = summary
                        break
                
                citations.append({
                    "source_file": doc["source_file"],
                    "document_name": clean_name,
                    "page_start": doc["page_start"],
                    "page_end": doc["page_end"],
                    "section": "; ".join(doc["sections"][:2]) if doc["sections"] else None,
                    "relevance_score": avg_score,
                    "source_text": combined_text,  # Full text for popup
                    "display_summary": llm_summary  # LLM-generated summary of what was found
                })
            
            # Calculate confidence based on evidence quality
            avg_score = sum(c.get('relevance_score', 0) for c in chunks) / len(chunks) if chunks else 0
            confidence = min(0.95, 0.5 + (avg_score / 20))  # Scale to 0.5-0.95
            
            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"Generated strict RAG response in {elapsed_ms:.0f}ms with {len(citations)} citations")
            
            return answer, confidence, citations
            
        except Exception as e:
            logger.error(f"Error generating strict RAG response: {e}")
            raise


# ================================
# Main Chat Function (Strict RAG)
# ================================

async def chat_with_agent(
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    include_sources: bool = True,
    use_strict_rag: bool = True,
    index_name: Optional[str] = None
) -> ChatResponse:
    """
    Main function to chat with the breast cancer companion agent.
    
    Uses STRICT RAG by default:
    - Only answers from knowledge base chunks
    - Returns "I don't have that information" if evidence is insufficient
    - Includes citations with source file, page numbers
    - Uses temperature=0 for factual accuracy
    
    Args:
        message: User's question or message
        session_id: Optional session ID for conversation continuity
        user_id: Optional user ID for personalization
        include_sources: Whether to include source citations
        use_strict_rag: Use strict RAG with evidence gating (default: True)
        index_name: OpenSearch index to search (default: breast_cancer_knowledge)
    
    Returns:
        ChatResponse with answer, sources, and metadata
    """
    start_time = time.time()
    
    # Get or create session
    session_id = SessionManager.get_or_create_session(session_id)
    
    # Add user message to history
    SessionManager.add_message(session_id, "user", message)
    
    # Classify query
    query_category = classify_query(message)
    logger.info(f"Query classified as: {query_category}")
    
    # Initialize agent
    agent = BreastCancerCompanionAgent()
    
    # Use default index if not specified
    # Default to breast_cancer_knowledge (PDF chunks) - ignore settings as it may be outdated
    if not index_name:
        index_name = "breast_cancer_knowledge"
    
    # Get knowledge base
    from services.knowledge_base import KnowledgeBaseService
    kb = KnowledgeBaseService(use_vectors=True, index_name=index_name)
    
    if use_strict_rag:
        # ========================================
        # STRICT RAG MODE (Evidence-Based Only)
        # ========================================
        logger.info(f"Using STRICT RAG mode with index: {index_name}")
        
        # Adjust thresholds based on index type
        # Nutrition index needs more lenient thresholds for general queries like "give me a recipe"
        is_nutrition_index = index_name and 'nutrition' in index_name.lower()
        
        if is_nutrition_index:
            min_chunks = 1  # Recipes are self-contained, 1 is enough
            min_score = 1.0  # Lower threshold for general recipe queries
            require_keyword = False  # Don't require exact keyword match for recipes
        else:
            min_chunks = 2  # Medical content needs more evidence
            min_score = 2.0  # Higher threshold for medical accuracy
            require_keyword = True  # Require keyword overlap for medical queries
        
        try:
            # Search for relevant chunks with evidence gating
            rag_result = await kb.search_chunks_for_rag(
                query=message,
                limit=15,  # Get 15 chunks
                min_chunks=min_chunks,
                min_score=min_score,
                require_keyword_match=require_keyword
            )
            
            chunks = rag_result["chunks"]
            has_sufficient_evidence = rag_result["has_sufficient_evidence"]
            evidence_stats = rag_result["evidence_stats"]
            
            logger.info(
                f"RAG search: {len(chunks)} chunks, "
                f"sufficient_evidence={has_sufficient_evidence}, "
                f"stats={evidence_stats}"
            )
            
        except Exception as e:
            logger.error(f"Failed to search chunks: {e}")
            chunks = []
            has_sufficient_evidence = False
            evidence_stats = {"error": str(e)}
        
        # Generate response from chunks with strict prompt
        answer, confidence, citations = await agent.generate_response_from_chunks(
            question=message,
            chunks=chunks,
            has_sufficient_evidence=has_sufficient_evidence
        )
        
        # Format citations for response - grouped by document with full text
        sources = []
        if include_sources and citations:
            # Sort by relevance score descending
            sorted_citations = sorted(citations, key=lambda x: x.get("relevance_score", 0), reverse=True)
            
            for citation in sorted_citations:
                source_file = citation.get("source_file", "Unknown")
                page_start = citation.get("page_start", 1)
                page_end = citation.get("page_end", 1)
                document_name = citation.get("document_name", source_file)
                
                # Format page range for title
                if page_start == page_end:
                    page_info = f"page {page_start}"
                else:
                    page_info = f"pages {page_start}-{page_end}"
                
                # Use LLM-generated summary if available, otherwise fallback
                display_summary = citation.get("display_summary")
                if not display_summary:
                    source_text = citation.get("source_text", "")
                    if source_text:
                        first_sentence = source_text.split('.')[0][:150] if source_text else ""
                        display_summary = f"Contains information about: {first_sentence}..."
                    else:
                        display_summary = f"Medical information from {document_name}"
                
                sources.append(SourceCitation(
                    title=f"{document_name} ({page_info})",
                    content_type=ContentType.MEDICAL_ARTICLE,
                    relevance_score=citation.get("relevance_score", 0.0),
                    source_url=source_file,
                    excerpt=citation.get("section", "")[:200] if citation.get("section") else "",
                    # New fields for popup display
                    source_text=citation.get("source_text", ""),  # Full text for popup
                    document_name=document_name,
                    page_start=page_start,
                    page_end=page_end,
                    section=citation.get("section"),
                    display_summary=display_summary  # LLM-generated summary
                ))
        
    else:
        # ========================================
        # LEGACY MODE (General AI Response)
        # ========================================
        logger.info("Using legacy mode (general AI response)")
        
        # Legacy mode (KB+AI) is NOT verified from knowledge base only
        has_sufficient_evidence = False
        
        # Get conversation history
        history = SessionManager.get_history(session_id)
        
        try:
            knowledge_context = await kb.get_relevant_context(
                query=message,
                category=query_category,
                limit=5
            )
            knowledge_sources = knowledge_context
        except Exception as e:
            logger.warning(f"Failed to retrieve knowledge sources: {e}")
            knowledge_sources = []
        
        answer, confidence = await agent.generate_response(
            question=message,
            session_id=session_id,
            knowledge_sources=knowledge_sources,
            conversation_history=history[:-1]
        )
        
        # Format sources for response
        sources = []
        if include_sources and knowledge_sources:
            for source in knowledge_sources:
                sources.append(SourceCitation(
                    title=source.get("title", "Unknown"),
                    content_type=ContentType(source.get("content_type", "medical_article")),
                    relevance_score=source.get("score", 0.0),
                    source_url=source.get("url"),
                    excerpt=source.get("content", "")[:200]
                ))
    
    # Add assistant response to history
    SessionManager.add_message(session_id, "assistant", answer)
    
    elapsed_ms = (time.time() - start_time) * 1000
    
    # Custom disclaimer based on mode
    if use_strict_rag:
        disclaimer_text = (
            "This information is from our medical leaflets and is for educational purposes only. "
            "Please consult your healthcare team (breast care nurse, oncologist, or GP) "
            "for advice specific to your situation."
        )
    else:
        disclaimer_text = (
            "This information is for educational purposes only and should not replace "
            "professional medical advice. Please consult your healthcare provider for personalized guidance."
        )
    
    return ChatResponse(
        answer=answer,
        session_id=session_id,
        query_category=query_category,
        sources=sources,
        confidence_score=confidence,
        response_time_ms=elapsed_ms,
        disclaimer=disclaimer_text,
        has_sufficient_evidence=has_sufficient_evidence,  # Defined in both branches
        support_helpline="0 800",
        support_helpline_name="HealthCareAI Now"
    )

