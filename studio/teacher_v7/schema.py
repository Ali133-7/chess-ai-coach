"""Strict OpenAI Structured Outputs contract. Every field is required."""
from pydantic import BaseModel, Field, ConfigDict

class LineNote(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scenario_id: str
    explanation_ar: str
    focus_ar: str

class TutorAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title_ar: str
    explanation_ar: str
    benefits_ar: list[str]
    risks_ar: list[str]
    scenario_notes: list[LineNote]
    learning_question_ar: str

# Explicit schema supported by Responses API strict JSON Schema format.
SCHEMA = {
 'type':'object','additionalProperties':False,
 'properties':{
   'title_ar':{'type':'string'},'explanation_ar':{'type':'string'},
   'benefits_ar':{'type':'array','items':{'type':'string'}},
   'risks_ar':{'type':'array','items':{'type':'string'}},
   'scenario_notes':{'type':'array','items':{
      'type':'object','additionalProperties':False,
      'properties':{'scenario_id':{'type':'string'},'explanation_ar':{'type':'string'},'focus_ar':{'type':'string'}},
      'required':['scenario_id','explanation_ar','focus_ar']}},
   'learning_question_ar':{'type':'string'},
 },
 'required':['title_ar','explanation_ar','benefits_ar','risks_ar','scenario_notes','learning_question_ar'],
}
