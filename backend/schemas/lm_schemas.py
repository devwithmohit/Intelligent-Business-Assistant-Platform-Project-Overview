from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str = Field(..., example="user")  # user | assistant | system
    content: str = Field(..., example="Hello, how can I help?")


class LLMRequest(BaseModel):
    """
    Generic LLM request used by services/llm_service.py.
    - task: high level task type (chat, content, embeddings, etc.)
    - prompt: raw prompt / input for non-chat tasks
    - model_hint: optional model string to prefer
    - params: provider-specific generation params (temperature, max_tokens, etc.)
    """
    task: str = Field(..., example="chat")
    prompt: Optional[str] = Field(None, example="Summarize the following...")
    messages: Optional[List[ChatMessage]] = None
    model_hint: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class GenerationChoice(BaseModel):
    """
    Represents a single generation/completion choice from a provider.
    """
    text: Optional[str] = None
    index: Optional[int] = None
    finish_reason: Optional[str] = None
    delta: Optional[Dict[str, Any]] = None  # for streaming


class LLMResponse(BaseModel):
    """
    Normalized response returned by llm_service.generate(...)
    - text: best-effort concatenated text result
    - choices: raw normalized choices list
    - provider: source provider name (openrouter|deepseek|fallback)
    - raw: original provider response
    - meta: optional metadata, timings, model used, etc.
    """
    text: str = ""
    choices: Optional[List[GenerationChoice]] = None
    provider: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None
    meta: Optional[Dict[str, Any]] = None


class EmbeddingRequest(BaseModel):
    model: str = Field(..., example="deeps-embed-1")
    inputs: List[str] = Field(..., example=["hello world", "another text"])


class EmbeddingResponse(BaseModel):
    embeddings: List[List[float]]
    model: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None
