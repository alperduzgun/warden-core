"""
Base Universal Validation Frame.

Provides a foundation for frames that operate on the Universal AST (ASTNode)
rather than language-specific representations.
"""

import structlog
from typing import List, Dict, Any, Optional
from warden.validation.domain.frame import ValidationFrame, FrameResult, CodeFile
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.models import ASTNode, ParseResult
from warden.ast.domain.enums import CodeLanguage, ParseStatus

logger = structlog.get_logger(__name__)

class BaseUniversalFrame(ValidationFrame):
    """
    Base class for cross-language validation frames.
    
    Automates Universal AST retrieval and provides helpers for pattern matching.
    """
    
    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.registry = ASTProviderRegistry()
        # Note: In a real app, the registry would be injected or pre-populated
        # For now, we rely on the FrameExecutor to have registered providers
        # or we manually ensure they are loaded.

    async def get_universal_ast(self, code_file: CodeFile) -> Optional[ASTNode]:
        """
        Retrieve the universal AST for a code file.
        """
        try:
            language = CodeLanguage(code_file.language.lower())
        except ValueError:
            logger.warning("unsupported_language_for_universal_ast", language=code_file.language)
            return None

        provider = self.registry.get_provider(language)
        if not provider:
            logger.warning("no_ast_provider_found", language=language.value)
            return None

        parse_result: ParseResult = await provider.parse(
            source_code=code_file.content,
            language=language,
            file_path=code_file.path
        )

        if parse_result.status in [ParseStatus.SUCCESS, ParseStatus.PARTIAL]:
            return parse_result.ast_root
            
        logger.warning("universal_ast_parse_failed", 
                       file=code_file.path, 
                       status=parse_result.status.value)
        return None

    def find_nodes_by_type(self, root: ASTNode, target_type: Any) -> List[ASTNode]:
        """
        Helper to find all nodes of a specific type in the AST.
        """
        found = []
        
        def walk(node: ASTNode):
            if node.node_type == target_type:
                found.append(node)
            for child in node.children:
                walk(child)
                
        walk(root)
        return found

    def extract_literals(self, root: ASTNode) -> List[str]:
        """
        Helper to extract all string/number literals.
        """
        from warden.ast.domain.enums import ASTNodeType
        literals = []
        
        def walk(node: ASTNode):
            if node.node_type == ASTNodeType.LITERAL:
                if node.value and isinstance(node.value, str):
                    literals.append(node.value)
            for child in node.children:
                walk(child)
                
        walk(root)
        return literals
