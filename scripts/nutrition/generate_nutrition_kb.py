#!/usr/bin/env python3
"""
Nutrition Knowledge Base Generator

Generates a comprehensive nutrition KB with recipes and dietary advice
tailored to breast cancer patient treatment stages using LLM.

Usage:
    python scripts/nutrition/generate_nutrition_kb.py --output data/intent_qa/nutrition_kb.json
    python scripts/nutrition/generate_nutrition_kb.py --recipes-only
    python scripts/nutrition/generate_nutrition_kb.py --advice-only
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
import asyncio

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import boto3
from dotenv import load_dotenv

from config.nutrition_enums import (
    MealType, CuisineType, DietaryTag, TextureClass, SymptomTag,
    STAGE_CONTEXT, get_all_cuisine_types, get_all_meal_types,
    get_all_dietary_tags, get_all_symptom_tags
)

load_dotenv()


class NutritionKBGenerator:
    """Generates nutrition knowledge base content using LLM."""
    
    def __init__(self, model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"):
        self.bedrock = boto3.client(
            "bedrock-runtime",
            region_name=os.getenv("AWS_REGION", "us-east-1")
        )
        self.model_id = model_id
        self.generated_recipes: List[Dict] = []
        self.generated_advice: List[Dict] = []
    
    def invoke_llm(self, prompt: str, max_tokens: int = 4096) -> str:
        """Invoke Claude via Bedrock."""
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }
        
        response = self.bedrock.invoke_model(
            modelId=self.model_id,
            body=json.dumps(body)
        )
        
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]
    
    def generate_recipes_for_cuisine_and_stage(
        self, 
        cuisine: str, 
        stage_id: str,
        meal_types: List[str],
        count: int = 3
    ) -> List[Dict]:
        """Generate recipes for a specific cuisine and treatment stage."""
        
        stage_info = STAGE_CONTEXT.get(stage_id, {})
        stage_name = stage_info.get("display_name", "General")
        nutrition_focus = stage_info.get("nutrition_focus", "General health")
        common_symptoms = stage_info.get("common_symptoms", [])
        
        prompt = f"""You are an oncology nutrition specialist. Generate {count} {cuisine.replace('_', ' ')} recipes 
suitable for breast cancer patients in the "{stage_name}" stage of treatment.

TREATMENT STAGE CONTEXT:
- Stage: {stage_name}
- Nutrition Focus: {nutrition_focus}
- Common Symptoms to Address: {', '.join(common_symptoms) if common_symptoms else 'General wellness'}

REQUIREMENTS:
Generate recipes as a JSON array. Each recipe must include:

{{
  "title": "Recipe Name",
  "meal_type": "one of: {', '.join(meal_types)}",
  "cuisine_type": "{cuisine}",
  "description": "Brief description of the dish and why it's good for this stage",
  "dietary_tags": ["array of applicable tags from: vegetarian, vegan, gluten_free, dairy_free, nut_free, soy_free, egg_free, halal, kosher, low_salt, low_sugar, low_fat, high_protein, high_fiber, high_calorie, anti_inflammatory"],
  "symptom_support": ["array of symptoms this helps with from: nausea, fatigue, mouth_sores, dry_mouth, constipation, diarrhea, taste_changes, difficulty_swallowing, appetite_loss, weight_loss, neutropenia"],
  "texture_class": "one of: regular, soft, minced, pureed, liquid",
  "nutrition": {{
    "calories_per_serving": number,
    "protein_g": number,
    "fiber_g": number,
    "fat_g": number,
    "carbs_g": number,
    "sugar_g": number,
    "sodium_mg": number
  }},
  "servings": number,
  "prep_time_mins": number,
  "cook_time_mins": number,
  "ingredients": ["array of ingredients with quantities"],
  "instructions": ["array of step-by-step instructions"],
  "clinical_notes": "Why this recipe is beneficial for patients at this stage",
  "allergen_info": "List any allergens or 'none'",
  "tips": "Optional tips for patients (e.g., modifications for symptoms)"
}}

IMPORTANT GUIDELINES:
1. Use evidence-based oncology nutrition principles
2. Consider the treatment stage and common side effects
3. Include a variety of meal types across the recipes
4. Ensure accurate, realistic nutrition values
5. Make recipes practical and achievable for patients who may be fatigued
6. For chemotherapy stages, consider food safety (neutropenic precautions)
7. Include both comfort foods and nutrient-dense options

Return ONLY valid JSON array, no additional text."""

        try:
            response = self.invoke_llm(prompt)
            # Parse JSON from response
            # Handle potential markdown code blocks
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            
            recipes = json.loads(response.strip())
            
            # Add metadata to each recipe
            for recipe in recipes:
                recipe["recipe_id"] = str(uuid.uuid4())
                recipe["treatment_stages"] = [stage_id]
                recipe["stage_display_names"] = [stage_name]
                recipe["created_at"] = datetime.utcnow().isoformat()
                recipe["source"] = "LLM-generated (oncology nutrition guidelines)"
            
            return recipes
            
        except json.JSONDecodeError as e:
            print(f"  Warning: Failed to parse JSON for {cuisine}/{stage_id}: {e}")
            return []
        except Exception as e:
            print(f"  Error generating recipes for {cuisine}/{stage_id}: {e}")
            return []
    
    def generate_dietary_advice_for_stage(self, stage_id: str) -> List[Dict]:
        """Generate dietary advice for a specific treatment stage."""
        
        stage_info = STAGE_CONTEXT.get(stage_id, {})
        stage_name = stage_info.get("display_name", "General")
        nutrition_focus = stage_info.get("nutrition_focus", "General health")
        common_symptoms = stage_info.get("common_symptoms", [])
        
        prompt = f"""You are an oncology nutrition specialist. Generate comprehensive dietary advice 
for breast cancer patients in the "{stage_name}" stage of treatment.

TREATMENT STAGE CONTEXT:
- Stage: {stage_name}
- Nutrition Focus: {nutrition_focus}
- Common Symptoms: {', '.join(common_symptoms) if common_symptoms else 'General wellness'}

Generate advice as a JSON array. Create 4-6 advice entries covering different aspects.
Each advice entry must include:

{{
  "category": "Advice category name (e.g., 'Managing Nausea During Treatment', 'Building Strength for Surgery')",
  "key_recommendation": "Main recommendation in one sentence",
  "detailed_guidance": "Detailed explanation (2-3 sentences)",
  "do_recommend": ["array of specific foods/actions to include"],
  "avoid_recommend": ["array of foods/actions to avoid"],
  "symptom_tags": ["array of symptoms this addresses from: nausea, fatigue, mouth_sores, dry_mouth, constipation, diarrhea, taste_changes, difficulty_swallowing, appetite_loss, weight_loss, weight_gain, neutropenia"],
  "meal_suggestions": ["2-3 specific meal ideas"],
  "practical_tips": ["2-3 practical tips for implementation"],
  "clinical_context": "Why this advice is important for this stage",
  "evidence_level": "oncology-guideline-based"
}}

ADVICE TOPICS TO COVER:
1. General nutrition priorities for this stage
2. Managing the most common symptoms
3. Food safety considerations (if applicable)
4. Hydration and fluid intake
5. Supplements and special considerations
6. Practical eating strategies

IMPORTANT:
- Base advice on established oncology nutrition guidelines
- Be specific and actionable
- Consider patient fatigue and practical limitations
- Include culturally diverse food options where relevant

Return ONLY valid JSON array, no additional text."""

        try:
            response = self.invoke_llm(prompt)
            
            # Parse JSON from response
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                response = response.split("```")[1].split("```")[0]
            
            advice_list = json.loads(response.strip())
            
            # Add metadata
            for advice in advice_list:
                advice["advice_id"] = str(uuid.uuid4())
                advice["treatment_stages"] = [stage_id]
                advice["stage_display_names"] = [stage_name]
                advice["created_at"] = datetime.utcnow().isoformat()
                advice["source"] = "LLM-generated (oncology nutrition guidelines)"
            
            return advice_list
            
        except json.JSONDecodeError as e:
            print(f"  Warning: Failed to parse advice JSON for {stage_id}: {e}")
            return []
        except Exception as e:
            print(f"  Error generating advice for {stage_id}: {e}")
            return []
    
    def generate_full_kb(
        self,
        cuisines: Optional[List[str]] = None,
        stages: Optional[List[str]] = None,
        recipes_per_cuisine_stage: int = 2
    ) -> Dict:
        """Generate the complete nutrition knowledge base."""
        
        if cuisines is None:
            cuisines = ["indian", "mediterranean", "mexican", "asian", "american", "middle_eastern"]
        
        if stages is None:
            # Focus on key treatment stages
            stages = ["1", "2", "3", "5", "7", "8", "9"]
        
        meal_types = get_all_meal_types()
        
        print("=" * 60)
        print("NUTRITION KNOWLEDGE BASE GENERATOR")
        print("=" * 60)
        print(f"Cuisines: {len(cuisines)}")
        print(f"Stages: {len(stages)}")
        print(f"Recipes per cuisine/stage: {recipes_per_cuisine_stage}")
        print("=" * 60)
        
        # Generate recipes
        print("\n[1/2] GENERATING RECIPES...")
        all_recipes = []
        
        for cuisine in cuisines:
            print(f"\n  Cuisine: {cuisine.upper()}")
            for stage_id in stages:
                stage_name = STAGE_CONTEXT.get(stage_id, {}).get("display_name", stage_id)
                print(f"    Stage: {stage_name}...", end=" ")
                
                recipes = self.generate_recipes_for_cuisine_and_stage(
                    cuisine=cuisine,
                    stage_id=stage_id,
                    meal_types=meal_types,
                    count=recipes_per_cuisine_stage
                )
                
                all_recipes.extend(recipes)
                print(f"Generated {len(recipes)} recipes")
        
        self.generated_recipes = all_recipes
        print(f"\n  Total recipes generated: {len(all_recipes)}")
        
        # Generate advice
        print("\n[2/2] GENERATING DIETARY ADVICE...")
        all_advice = []
        
        for stage_id in stages:
            stage_name = STAGE_CONTEXT.get(stage_id, {}).get("display_name", stage_id)
            print(f"  Stage: {stage_name}...", end=" ")
            
            advice = self.generate_dietary_advice_for_stage(stage_id)
            all_advice.extend(advice)
            print(f"Generated {len(advice)} advice entries")
        
        self.generated_advice = all_advice
        print(f"\n  Total advice entries generated: {len(all_advice)}")
        
        # Compile KB
        kb = {
            "version": "1.0",
            "generated_at": datetime.utcnow().isoformat(),
            "generator": "generate_nutrition_kb.py",
            "source": "LLM-generated based on oncology nutrition guidelines",
            "statistics": {
                "total_recipes": len(all_recipes),
                "total_advice": len(all_advice),
                "cuisines_covered": cuisines,
                "stages_covered": stages
            },
            "recipes": all_recipes,
            "advice": all_advice
        }
        
        print("\n" + "=" * 60)
        print("GENERATION COMPLETE")
        print("=" * 60)
        
        return kb
    
    def generate_recipes_only(
        self,
        cuisines: Optional[List[str]] = None,
        stages: Optional[List[str]] = None,
        recipes_per_cuisine_stage: int = 2
    ) -> List[Dict]:
        """Generate only recipes."""
        kb = self.generate_full_kb(cuisines, stages, recipes_per_cuisine_stage)
        return kb["recipes"]
    
    def generate_advice_only(
        self,
        stages: Optional[List[str]] = None
    ) -> List[Dict]:
        """Generate only dietary advice."""
        if stages is None:
            stages = ["1", "2", "3", "5", "7", "8", "9"]
        
        print("GENERATING DIETARY ADVICE...")
        all_advice = []
        
        for stage_id in stages:
            stage_name = STAGE_CONTEXT.get(stage_id, {}).get("display_name", stage_id)
            print(f"  Stage: {stage_name}...", end=" ")
            
            advice = self.generate_dietary_advice_for_stage(stage_id)
            all_advice.extend(advice)
            print(f"Generated {len(advice)} advice entries")
        
        return all_advice


def main():
    parser = argparse.ArgumentParser(
        description="Generate nutrition knowledge base for breast cancer patients"
    )
    parser.add_argument(
        "--output", "-o",
        default="data/intent_qa/nutrition_kb.json",
        help="Output file path (default: data/intent_qa/nutrition_kb.json)"
    )
    parser.add_argument(
        "--recipes-only",
        action="store_true",
        help="Generate only recipes"
    )
    parser.add_argument(
        "--advice-only",
        action="store_true",
        help="Generate only dietary advice"
    )
    parser.add_argument(
        "--cuisines",
        nargs="+",
        default=None,
        help="Cuisines to generate (default: indian, mediterranean, mexican, asian, american, middle_eastern)"
    )
    parser.add_argument(
        "--stages",
        nargs="+",
        default=None,
        help="Treatment stages to cover (default: 1, 2, 3, 5, 7, 8, 9)"
    )
    parser.add_argument(
        "--recipes-per-combo",
        type=int,
        default=2,
        help="Recipes per cuisine/stage combination (default: 2)"
    )
    parser.add_argument(
        "--model",
        default="anthropic.claude-3-haiku-20240307-v1:0",
        help="Bedrock model ID to use"
    )
    
    args = parser.parse_args()
    
    # Initialize generator
    generator = NutritionKBGenerator(model_id=args.model)
    
    # Generate content
    if args.recipes_only:
        content = generator.generate_recipes_only(
            cuisines=args.cuisines,
            stages=args.stages,
            recipes_per_cuisine_stage=args.recipes_per_combo
        )
        output_data = {"recipes": content}
    elif args.advice_only:
        content = generator.generate_advice_only(stages=args.stages)
        output_data = {"advice": content}
    else:
        output_data = generator.generate_full_kb(
            cuisines=args.cuisines,
            stages=args.stages,
            recipes_per_cuisine_stage=args.recipes_per_combo
        )
    
    # Write output
    output_path = args.output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nOutput written to: {output_path}")
    print(f"File size: {os.path.getsize(output_path) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
