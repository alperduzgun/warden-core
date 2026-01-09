
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, field_validator, ConfigDict
from enum import Enum

class ProjectType(str, Enum):
    APPLICATION = "application"
    LIBRARY = "library"
    MICROSERVICE = "microservice"
    MONOREPO = "monorepo"
    CLI = "cli"
    API = "api"
    FRONTEND = "frontend"
    FULLSTACK = "fullstack"

class ProjectConfig(BaseModel):
    name: str = "project"
    language: str
    frameworks: List[str] = Field(default_factory=list)
    type: ProjectType = ProjectType.APPLICATION
    sdk_version: Optional[str] = None
    
    # Allow extra fields for flexibility
    model_config = ConfigDict(extra="ignore")

class SemanticSearchConfig(BaseModel):
    enabled: bool = False
    provider: str = "local"
    database: str = "chromadb"
    chroma_path: str = ".warden/embeddings"
    collection_name: str = "warden_collection"
    max_context_tokens: int = 4000
    model: str = "all-MiniLM-L6-v2"

class PreAnalysisConfig(BaseModel):
    llm_threshold: float = 0.7
    batch_size: int = 10
    use_llm: bool = True
    cache_enabled: bool = True

class SettingsConfig(BaseModel):
    enable_classification: bool = True
    fail_fast: bool = False
    mode: str = "normal"
    timeout: int = 300
    min_severity: str = "high"
    
    # Nested configs
    pre_analysis: PreAnalysisConfig = Field(default_factory=PreAnalysisConfig)
    
    @field_validator("timeout")
    @classmethod
    def timeout_must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Timeout must be a positive integer")
        return v

class LlmProviderConfig(BaseModel):
    enabled: bool = True
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    default_model: Optional[str] = None
    api_version: Optional[str] = None

class LlmConfig(BaseModel):
    enabled: bool = False
    provider: str = "azure_openai"
    timeout: int = 300
    max_retries: int = 2
    
    # Providers
    providers: Dict[str, LlmProviderConfig] = Field(default_factory=dict)
    
    # Fallback
    fallback_providers: List[str] = Field(default_factory=list)
    
    # For simple configs (legacy/flat structure)
    api_key: Optional[str] = None
    model: Optional[str] = None

class CiOutputConfig(BaseModel):
    format: str
    path: str

class CiConfig(BaseModel):
    enabled: bool = True
    fail_on_blocker: bool = True
    output: List[CiOutputConfig] = Field(default_factory=list)

class WardenConfig(BaseModel):
    """
    Master configuration schema for warden.yaml
    """
    version: Union[str, float, int] = "1.0"
    
    project: Optional[ProjectConfig] = None
    
    dependencies: Dict[str, str] = Field(default_factory=dict)
    
    frames: List[str] = Field(default_factory=list)
    
    frames_config: Dict[str, Any] = Field(default_factory=dict)
    
    llm: LlmConfig = Field(default_factory=LlmConfig)
    
    semantic_search: SemanticSearchConfig = Field(default_factory=SemanticSearchConfig)
    
    settings: SettingsConfig = Field(default_factory=SettingsConfig)
    
    ci: CiConfig = Field(default_factory=CiConfig)
    
    custom_rules: List[str] = Field(default_factory=list)
    
    # Pydantic V2 config
    model_config = ConfigDict(extra="ignore")
