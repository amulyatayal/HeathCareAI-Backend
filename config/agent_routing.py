"""
Agent Routing Configuration for Multi-Agent Pipeline
Maps intents to reasoning agents, knowledge bases, and model selections.

Spec Reference: ProjectSpec.md v1.2, Section 8.2
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from config.pipeline_config import IntentCategory, ModelType


# ================================
# Knowledge Base Identifiers
# ================================

class KnowledgeBase(str, Enum):
    """Available knowledge bases for retrieval."""
    MEDICAL = "breast_cancer_knowledge"  # Main breast cancer KB (PDFs, Q&A)
    NUTRITION = "nutrition_assistant"    # Nutrition and recipe KB
    FORUM = "forum_posts"                # Community forum discussions
    EMOTIONAL = "emotional_support"      # Emotional support content (future)
    LOGISTICS = "logistics_navigation"   # Hospital/insurance navigation (future)


# ================================
# Agent Type Identifiers
# ================================

class ReasoningAgentType(str, Enum):
    """Types of reasoning agents available."""
    # Core Medical Agents
    SYMPTOMS = "symptoms_agent"
    SURGERY = "surgery_agent"
    WOUND_CARE = "wound_care_agent"
    CANCER_TREATMENT = "cancer_treatment_agent"
    MEDICATION = "medication_agent"
    SIDE_EFFECTS = "side_effects_agent"
    
    # Perioperative Agents
    PREHAB = "prehab_agent"
    RECOVERY = "recovery_agent"
    
    # Follow-up Care Agents
    FOLLOW_UP = "follow_up_agent"
    NUTRITION = "nutrition_agent"
    EXERCISE = "exercise_agent"
    CLOTHING = "clothing_agent"
    
    # Support & Admin Agents
    EMOTIONAL = "emotional_agent"
    DIAGNOSIS = "diagnosis_agent"
    LOGISTICS = "logistics_agent"
    
    # Safety & Info Agents
    SAFETY = "safety_agent"
    STATISTICS = "statistics_agent"
    
    # Fallback
    GENERAL = "general_agent"


# ================================
# Agent Route Configuration
# ================================

@dataclass
class AgentRoute:
    """
    Configuration for routing a specific intent to its handling agent.
    
    Attributes:
        agent_type: The reasoning agent to use
        knowledge_bases: List of KBs to search (in priority order)
        model_type: Which model to use (fast/accurate)
        requires_stage: Whether stage context affects the response
        allow_parallel_kb: Whether to search multiple KBs in parallel
        strict_rag: If True, only use KB evidence; if False, LLM can supplement
    """
    agent_type: ReasoningAgentType
    knowledge_bases: List[KnowledgeBase]
    model_type: ModelType
    requires_stage: bool = True
    allow_parallel_kb: bool = True
    strict_rag: bool = True  # Default: strict RAG (KB only)


# ================================
# Intent → Agent Routing Map
# ================================

INTENT_ROUTING: Dict[IntentCategory, AgentRoute] = {
    
    # ---- Core Medical ----
    IntentCategory.SYMPTOMS: AgentRoute(
        agent_type=ReasoningAgentType.SYMPTOMS,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True
    ),
    
    IntentCategory.SURGERY_PROCEDURES: AgentRoute(
        agent_type=ReasoningAgentType.SURGERY,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True
    ),
    
    IntentCategory.DRAINS_WOUND_CARE: AgentRoute(
        agent_type=ReasoningAgentType.WOUND_CARE,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True
    ),
    
    IntentCategory.CANCER_TREATMENT: AgentRoute(
        agent_type=ReasoningAgentType.CANCER_TREATMENT,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True
    ),
    
    IntentCategory.MEDICATION_INFO: AgentRoute(
        agent_type=ReasoningAgentType.MEDICATION,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True
    ),
    
    IntentCategory.SIDE_EFFECTS: AgentRoute(
        agent_type=ReasoningAgentType.SIDE_EFFECTS,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True
    ),
    
    # ---- Perioperative ----
    IntentCategory.PRE_SURGERY_PREHAB: AgentRoute(
        agent_type=ReasoningAgentType.PREHAB,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True
    ),
    
    IntentCategory.POST_SURGERY_RECOVERY: AgentRoute(
        agent_type=ReasoningAgentType.RECOVERY,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True
    ),
    
    # ---- Follow-up Care ----
    IntentCategory.FOLLOW_UP_CARE: AgentRoute(
        agent_type=ReasoningAgentType.FOLLOW_UP,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.FAST,
        requires_stage=True
    ),
    
    IntentCategory.NUTRITION: AgentRoute(
        agent_type=ReasoningAgentType.NUTRITION,
        knowledge_bases=[KnowledgeBase.NUTRITION, KnowledgeBase.MEDICAL],
        model_type=ModelType.FAST,
        requires_stage=True,
        strict_rag=False  # Can use LLM general nutrition knowledge
    ),
    
    IntentCategory.EXERCISE: AgentRoute(
        agent_type=ReasoningAgentType.EXERCISE,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.FAST,
        requires_stage=True,
        strict_rag=False  # Can use LLM general exercise knowledge
    ),
    
    IntentCategory.CLOTHING: AgentRoute(
        agent_type=ReasoningAgentType.CLOTHING,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.FAST,
        requires_stage=True,
        strict_rag=False  # Can use LLM general advice
    ),
    
    # ---- Support & Admin ----
    IntentCategory.EMOTIONAL_SUPPORT: AgentRoute(
        agent_type=ReasoningAgentType.EMOTIONAL,
        knowledge_bases=[KnowledgeBase.FORUM, KnowledgeBase.MEDICAL],
        model_type=ModelType.FAST,
        requires_stage=True,
        strict_rag=False  # LLM empathy is helpful
    ),
    
    IntentCategory.DIAGNOSIS_TESTING: AgentRoute(
        agent_type=ReasoningAgentType.DIAGNOSIS,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True,
        strict_rag=True  # Medical accuracy required
    ),
    
    IntentCategory.ADMIN_LOGISTICS: AgentRoute(
        agent_type=ReasoningAgentType.LOGISTICS,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.FAST,
        requires_stage=False,
        strict_rag=False  # General process info OK
    ),
    
    # ---- Safety & Info ----
    IntentCategory.SAFETY_RED_FLAGS: AgentRoute(
        agent_type=ReasoningAgentType.SAFETY,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=True,
        strict_rag=True  # MUST be strict - safety critical
    ),
    
    IntentCategory.STATISTICS: AgentRoute(
        agent_type=ReasoningAgentType.STATISTICS,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.ACCURATE,
        requires_stage=False,
        strict_rag=True  # Must be accurate
    ),
    
    # ---- Fallback ----
    IntentCategory.UNKNOWN: AgentRoute(
        agent_type=ReasoningAgentType.GENERAL,
        knowledge_bases=[KnowledgeBase.MEDICAL],
        model_type=ModelType.FAST,
        requires_stage=False,
        strict_rag=False  # Can use general knowledge for unknown queries
    ),
}


# ================================
# Agent Prompts Configuration
# ================================

AGENT_SYSTEM_PROMPTS: Dict[ReasoningAgentType, str] = {
    
    # ---- Core Medical ----
    ReasoningAgentType.SYMPTOMS: """You are a symptom education specialist for breast cancer patients.
Your role is to explain symptoms, help patients understand what they're experiencing, and clarify when to seek medical attention.
Be practical and empathetic. Distinguish between common expected symptoms and red flags.
Always recommend consulting the care team for persistent or concerning symptoms.""",

    ReasoningAgentType.SURGERY: """You are a surgical procedures education specialist.
Your role is to explain breast cancer surgeries (lumpectomy, mastectomy, reconstruction, lymph node procedures) in clear, accessible terms.
Cover what to expect before, during, and after surgery.
Help patients understand their options without influencing their choices.""",

    ReasoningAgentType.WOUND_CARE: """You are a wound care and drain management specialist.
Your role is to explain post-surgical drain care, wound healing, and scar management.
Provide practical, step-by-step guidance for home care.
Clarify warning signs that require medical attention (infection, excessive drainage, etc.).""",

    ReasoningAgentType.CANCER_TREATMENT: """You are a cancer treatment education specialist.
Your role is to explain treatment types (chemotherapy, radiation, hormone therapy, targeted therapy, immunotherapy).
Cover treatment timelines, what to expect during sessions, and general side effect profiles.
Tailor information to the patient's stage and treatment type when known.""",

    ReasoningAgentType.MEDICATION: """You are a medication education specialist.
Your role is to explain medication purposes, dosing schedules, and important interactions in clear, accessible language.
Always emphasize that patients should follow their prescriber's instructions.
Never recommend specific medications - only provide education on prescribed treatments.""",

    ReasoningAgentType.SIDE_EFFECTS: """You are a side effects education specialist.
Your role is to explain potential side effects, their likelihood, and management strategies.
Be honest but not alarming. Distinguish between common side effects and those requiring medical attention.
Always encourage reporting concerns to the care team.""",

    # ---- Perioperative ----
    ReasoningAgentType.PREHAB: """You are a prehabilitation (prehab) specialist.
Your role is to help patients prepare for surgery through exercise, nutrition, and mental preparation.
Explain the benefits of prehab and provide practical, safe activities.
Emphasize starting early and working with the care team on personalized plans.""",

    ReasoningAgentType.RECOVERY: """You are a post-surgery recovery specialist.
Your role is to guide patients through the recovery process after breast cancer surgery.
Cover mobility exercises, pain management, activity restrictions, and milestones.
Emphasize patience and gradual progression while watching for complications.""",

    # ---- Follow-up Care ----
    ReasoningAgentType.FOLLOW_UP: """You are a follow-up care education specialist.
Your role is to explain ongoing care after primary treatment ends.
Cover monitoring schedules, what tests to expect, and long-term health considerations.
Help patients understand the transition from active treatment to surveillance.""",

    ReasoningAgentType.NUTRITION: """You are a nutrition specialist for breast cancer patients.
Your role is to provide practical nutrition advice, recipes, and dietary recommendations.
Focus on managing treatment side effects (nausea, taste changes, appetite loss) and supporting recovery.
Provide actionable, easy-to-follow suggestions appropriate to the patient's situation.""",

    ReasoningAgentType.EXERCISE: """You are an exercise and physical activity specialist for breast cancer patients.
Your role is to provide guidance on safe exercise during and after treatment.
Cover benefits of movement, appropriate activities for different treatment stages, and building strength.
Emphasize listening to one's body and working with physical therapists when needed.""",

    ReasoningAgentType.CLOTHING: """You are a post-treatment clothing and comfort specialist.
Your role is to advise on comfortable clothing choices, bras, prosthetics, and adaptive garments.
Cover practical tips for different stages (surgery, treatment, reconstruction).
Be sensitive to body image concerns and provide practical, supportive guidance.""",

    # ---- Support & Admin ----
    ReasoningAgentType.EMOTIONAL: """You are an emotional support specialist.
Your role is to provide empathetic, validating responses that acknowledge the patient's feelings.
Share coping strategies and normalize common emotional responses to diagnosis and treatment.
Encourage professional mental health support when appropriate.
You may reference community experiences to show patients they're not alone.""",

    ReasoningAgentType.DIAGNOSIS: """You are a diagnosis and testing education specialist.
Your role is to explain diagnostic tests (mammograms, biopsies, imaging, blood tests) and what results mean.
Help patients understand the diagnostic journey and what to expect next.
Use clear, non-technical language. Avoid interpreting specific numeric results.""",

    ReasoningAgentType.LOGISTICS: """You are a healthcare navigation and logistics specialist.
Your role is to help patients understand appointments, insurance, financial assistance, and hospital processes.
Be practical and specific. Provide actionable next steps when possible.
Acknowledge that systems can be confusing and validate their frustration.""",

    # ---- Safety & Info ----
    ReasoningAgentType.SAFETY: """You are a safety and red flags specialist.
Your role is to help patients identify warning signs that require immediate medical attention.
Be clear and direct about emergency symptoms (severe pain, infection signs, breathing problems, etc.).
When red flags are present, always advise contacting the care team or seeking emergency care immediately.
Do not minimize concerns - err on the side of caution.""",

    ReasoningAgentType.STATISTICS: """You are a cancer statistics and research information specialist.
Your role is to explain survival rates, treatment success rates, and research findings in accessible terms.
Help patients understand what statistics mean and don't mean for their individual situation.
Emphasize that statistics are population-level and individual outcomes vary.
Be honest but hopeful. Avoid false optimism or unnecessary pessimism.""",

    # ---- Fallback ----
    ReasoningAgentType.GENERAL: """You are a patient education specialist.
Your role is to provide helpful, accurate health information in an accessible way.
If you're unsure about the topic, provide general guidance and recommend speaking with the care team.
Be warm, supportive, and clear in your explanations.""",
}


# ================================
# Helper Functions
# ================================

def get_route_for_intent(intent: IntentCategory) -> AgentRoute:
    """Get the routing configuration for a given intent."""
    return INTENT_ROUTING.get(intent, INTENT_ROUTING[IntentCategory.UNKNOWN])


def get_knowledge_bases_for_intent(intent: IntentCategory) -> List[KnowledgeBase]:
    """Get the list of knowledge bases to search for an intent."""
    route = get_route_for_intent(intent)
    return route.knowledge_bases


def get_model_for_intent(intent: IntentCategory) -> ModelType:
    """Get the model type to use for an intent."""
    route = get_route_for_intent(intent)
    return route.model_type


def get_agent_prompt(agent_type: ReasoningAgentType) -> str:
    """Get the system prompt for a reasoning agent."""
    return AGENT_SYSTEM_PROMPTS.get(
        agent_type, 
        AGENT_SYSTEM_PROMPTS[ReasoningAgentType.GENERAL]
    )


def get_primary_kb_for_intent(intent: IntentCategory) -> KnowledgeBase:
    """Get the primary knowledge base for an intent."""
    route = get_route_for_intent(intent)
    return route.knowledge_bases[0] if route.knowledge_bases else KnowledgeBase.MEDICAL


def is_strict_rag(intent: IntentCategory) -> bool:
    """Check if an intent requires strict RAG (KB evidence only, no LLM general knowledge)."""
    route = get_route_for_intent(intent)
    return route.strict_rag


def is_medical_intent(intent: IntentCategory) -> bool:
    """Check if an intent requires medical-grade accuracy (uses ACCURATE model)."""
    medical_intents = {
        IntentCategory.SYMPTOMS,
        IntentCategory.SURGERY_PROCEDURES,
        IntentCategory.DRAINS_WOUND_CARE,
        IntentCategory.CANCER_TREATMENT,
        IntentCategory.MEDICATION_INFO,
        IntentCategory.SIDE_EFFECTS,
        IntentCategory.PRE_SURGERY_PREHAB,
        IntentCategory.POST_SURGERY_RECOVERY,
        IntentCategory.DIAGNOSIS_TESTING,
        IntentCategory.SAFETY_RED_FLAGS,
        IntentCategory.STATISTICS,
    }
    return intent in medical_intents
