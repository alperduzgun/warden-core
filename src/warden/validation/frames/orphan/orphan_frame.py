
import structlog
from typing import List
from pathlib import Path
from warden.validation.domain.frame import ValidationFrame, FrameResult, Finding
from warden.lsp import LSPManager

logger = structlog.get_logger()

class OrphanFrame(ValidationFrame):
    """
    Detects Orphaned (Unused) Code using LSP References.
    
    Precision: High (Uses Reference Count from Language Server)
    """
    
    name = "Orphan Code Detection"
    description = "Identifies unused functions and classes with compiler-grade precision."
    
    async def execute(self, code_file: CodeFile) -> FrameResult:
        findings: List[Finding] = []
        try:
            path = Path(code_file.path)
        except AttributeError:
            path = Path(code_file)
        
        # Only check supported languages
        language = None
        if path.suffix == ".py": language = "python"
        elif path.suffix in [".ts", ".tsx"]: language = "typescript"
        elif path.suffix in [".js", ".jsx"]: language = "javascript"
        
        if not language:
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="passed",
                duration=0.0,
                issues_found=0,
                is_blocker=False,
                findings=[]
            )

        try:
            lsp_manager = LSPManager.get_instance()
            # Root path logic needs improvement in real app (ProjectContext)
            # Defaulting to 2 levels up for now as a heuristic
            client = await lsp_manager.get_client(language, str(path.parent.parent)) 
            
            if not client:
                logger.debug("orphan_lsp_unavailable", file=code_file)
                return FrameResult(
                    frame_id=self.frame_id,
                    frame_name=self.name,
                    status="passed",
                    duration=0.0,
                    issues_found=0,
                    is_blocker=False,
                    findings=[]
                )

            # 1. Get Symbols (Functions/Classes)
            uri = f"file://{code_file}"
            # Ensure file is open in LSP
            await client.send_notification("textDocument/didOpen", {
                "textDocument": {
                    "uri": uri,
                    "languageId": language,
                    "version": 1,
                    "text": path.read_text()
                }
            })
            
            symbols_resp = await client.send_request("textDocument/documentSymbol", {
                "textDocument": {"uri": uri}
            })
            
            if not symbols_resp:
                return FrameResult(
                    frame_id=self.frame_id,
                    frame_name=self.name,
                    status="passed",
                    duration=0.0,
                    issues_found=0,
                    is_blocker=False,
                    findings=[]
                )

            # 2. Check References for each symbol
            for symbol in symbols_resp:
                 await self._check_symbol(client, uri, symbol, findings)

        except Exception as e:
            logger.error("orphan_frame_error", error=str(e), file=code_file)
            return FrameResult(
                 frame_id=self.frame_id,
                 frame_name=self.name,
                 status="failed",
                 duration=0.0,
                 issues_found=0,
                 is_blocker=False,
                 findings=[],
                 metadata={"error": str(e)}
            )
            
        status = "passed" if not findings else "warning"
        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=0.0,
            issues_found=len(findings),
            is_blocker=False,
            findings=findings
        )

    async def _check_symbol(self, client, uri, symbol, findings):
        """Recursively check references for a symbol."""
        kind = symbol.get("kind")
        # 12=Function, 5=Class, 6=Method (LSP kinds)
        if kind in [5, 6, 12]:
            name = symbol.get("name")
            if name.startswith("_"): return
            
            # Request References
            refs = await client.send_request("textDocument/references", {
                "textDocument": {"uri": uri},
                "position": symbol.get("selectionRange", symbol.get("range"))["start"],
                "context": {"includeDeclaration": False}
            })
            
            # If 0 references, it is orphaned
            if not refs or len(refs) == 0:
                line_no = symbol.get("range")["start"]["line"] + 1
                findings.append(Finding(
                    id=f"orphan-{name}-{line_no}",
                    severity="warning",
                    message=f"Symbol '{name}' appears unused (0 references).",
                    location=f"{uri.replace('file://', '')}:{line_no}",
                    line=line_no,
                    is_blocker=False
                ))
        
        if "children" in symbol:
            for child in symbol["children"]:
                await self._check_symbol(client, uri, child, findings)
