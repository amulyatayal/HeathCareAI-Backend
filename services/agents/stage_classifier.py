
import logging
import math
from typing import List, Dict, Optional, Tuple, Any
import json
import os

from services.knowledge_base import EmbeddingService
from services.patient_stage_service import PatientStageService
from models.patient_stages import TreatmentStage

logger = logging.getLogger(__name__)

class StageClassifierAgent:
    """
    Agent that maps unstructured text to specific clinical stages
    using semantic vector embeddings.
    """
    
    def __init__(self, stage_service: Optional[PatientStageService] = None):
        """
        Initialize the classifier agent.
        
        Args:
            stage_service: Optional injected service (mostly for testing)
        """
        self.stage_service = stage_service or PatientStageService()
        self.embedding_service = EmbeddingService()
        
        # Cache for stage embeddings: {stage_id: [float, ...]}
        self._stage_embeddings: Dict[str, List[float]] = {}
        self._initialized = False

    async def initialize(self):
        """
        Hydrate the stage embeddings cache.
        This should be called at startup or lazily on first request.
        """
        if self._initialized:
            return

        logger.info("Initializing StageClassifierAgent: Computing embeddings for all stages...")
        
        # Ensure stages are loaded
        # Accessing protected member _ensure_loaded is necessary as it's not exposed publicly 
        # but is idempotent. Ideally PatientStageService should have a public load method.
        # We'll trigger a read to ensure load.
        _ = self.stage_service.get_all_stages() 
        
        stages = self.stage_service.get_all_stages()
        
        count = 0
        for stage in stages:
            stage_id = stage.stage_id
            
            # Create a rich semantic representation of the stage
            # "Stage Name: Description. Notes."
            stage_text = f"{stage.name}: {stage.description}"
            if stage.transition_notes:
                stage_text += f" Note: {stage.transition_notes}"
                
            embedding = self.embedding_service.create_embedding(stage_text)
            if embedding:
                self._stage_embeddings[stage_id] = embedding
                count += 1
            else:
                logger.warning(f"Failed to generate embedding for stage {stage_id}")
                
        self._initialized = True
        logger.info(f"StageClassifierAgent initialized with {count} stage embeddings.")

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
            
        dot_product = sum(a * b for a, b in zip(v1, v2))
        magnitude_v1 = math.sqrt(sum(a * a for a in v1))
        magnitude_v2 = math.sqrt(sum(b * b for b in v2))
        
        if magnitude_v1 == 0 or magnitude_v2 == 0:
            return 0.0
            
        return dot_product / (magnitude_v1 * magnitude_v2)

    async def classify(
        self, 
        text: str, 
        current_stage_id: Optional[str] = None,
        top_k: int = 3
    ) -> List[Tuple[TreatmentStage, float]]:
        """
        Classify input text to the most likely clinical stages.
        
        Args:
            text: User input (e.g., "I just started radiation")
            current_stage_id: Optional current stage ID to restrict search (Graph Constraint)
            top_k: Number of results to return
            
        Returns:
            List of (Stage, Score) tuples, sorted by score descending.
        """
        if not self._initialized:
            await self.initialize()
            
        # 1. Embed input text
        input_embedding = self.embedding_service.create_embedding(text)
        if not input_embedding:
            logger.error("Failed to embed input text for classification")
            return []
            
        # 2. Determine candidate pool (Constraint Logic)
        candidates = self._get_candidates(current_stage_id)
        
        # 3. Compute Scores
        results = []
        for stage_id in candidates:
            # Skip if no embedding (shouldn't happen if initialized correctly)
            if stage_id not in self._stage_embeddings:
                continue
                
            stage_embedding = self._stage_embeddings[stage_id]
            score = self._cosine_similarity(input_embedding, stage_embedding)
            
            stage = self.stage_service.get_stage_by_id(stage_id)
            if stage:
                results.append((stage, score))
                
        # 4. Sort and Return
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _get_candidates(self, current_stage_id: Optional[str]) -> List[str]:
        """
        Get list of valid candidate stage IDs based on current state constraints.
        
        If current_stage_id is None, return ALL stages (Global Search).
        If provided, return:
          - Current stage (Status Quo)
          - Child stages (Drill down)
          - Next stages (Progression)
          - Parent stage (Backtrack/Correction)
        """
        all_stages_list = self.stage_service.get_all_stages()
        all_stages_map = {s.stage_id: s for s in all_stages_list}
        
        if not current_stage_id or current_stage_id not in all_stages_map:
            return list(all_stages_map.keys())
            
        current_stage = all_stages_map[current_stage_id]
        candidates = {current_stage_id} # Always include current
        
        # Add Children
        if current_stage.child_stage_ids:
            candidates.update(current_stage.child_stage_ids)
            
        # Add Next Stages (After)
        if current_stage.after_stages:
            candidates.update(current_stage.after_stages)
            
        # Add Parent (in case user wants to move up/correction)
        if current_stage.parent_stage_id:
            candidates.add(current_stage.parent_stage_id)
            
        # Filter out invalid IDs (just in case)
        return [cid for cid in candidates if cid in all_stages_map]
