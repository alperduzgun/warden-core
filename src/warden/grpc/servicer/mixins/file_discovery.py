"""
File Discovery Mixin

Endpoints: DiscoverFiles, GetFilesByType, DetectFrameworks, GetProjectStats
"""

from pathlib import Path
from typing import Dict

try:
    from warden.grpc.generated import warden_pb2
except ImportError:
    warden_pb2 = None

from warden.grpc.converters import ProtoConverters

try:
    from warden.shared.infrastructure.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class FileDiscoveryMixin:
    """File discovery endpoints (4 endpoints)."""

    async def DiscoverFiles(self, request, context) -> "warden_pb2.DiscoverResponse":
        """Discover project files."""
        logger.info("grpc_discover_files", path=request.path)

        try:
            if hasattr(self.bridge, 'discover_files'):
                result = await self.bridge.discover_files(
                    path=request.path,
                    max_depth=request.max_depth or 0,
                    use_gitignore=request.use_gitignore
                )

                response = warden_pb2.DiscoverResponse(
                    success=True,
                    total_files=result.get("total_files", 0),
                    analyzable_files=result.get("analyzable_files", 0)
                )

                for file in result.get("files", []):
                    response.files.append(ProtoConverters.convert_discovered_file(file))

                for fw in result.get("frameworks", []):
                    response.frameworks.append(ProtoConverters.convert_framework(fw))

                return response

            path = Path(request.path)
            if not path.exists():
                return warden_pb2.DiscoverResponse(
                    success=False,
                    error_message=f"Path not found: {request.path}"
                )

            files = []
            for p in path.rglob("*"):
                if p.is_file():
                    files.append({
                        "path": str(p),
                        "size_bytes": p.stat().st_size,
                        "language": self._detect_language(p)
                    })

            response = warden_pb2.DiscoverResponse(
                success=True,
                total_files=len(files),
                analyzable_files=len([f for f in files if f["language"]])
            )

            for file in files[:1000]:
                response.files.append(ProtoConverters.convert_discovered_file(file))

            return response

        except Exception as e:
            logger.error("grpc_discover_files_error: %s", str(e))
            return warden_pb2.DiscoverResponse(
                success=False,
                error_message=str(e)
            )

    async def GetFilesByType(self, request, context) -> "warden_pb2.DiscoverResponse":
        """Get files filtered by type."""
        logger.info("grpc_get_files_by_type", types=list(request.types))

        try:
            type_to_ext = {
                warden_pb2.PYTHON: ".py",
                warden_pb2.JAVASCRIPT: ".js",
                warden_pb2.TYPESCRIPT: ".ts",
                warden_pb2.JAVA: ".java",
                warden_pb2.CSHARP: ".cs",
                warden_pb2.GO: ".go",
                warden_pb2.RUST: ".rs",
                warden_pb2.CPP: ".cpp",
                warden_pb2.RUBY: ".rb",
                warden_pb2.PHP: ".php",
                warden_pb2.KOTLIN: ".kt",
                warden_pb2.SWIFT: ".swift",
                warden_pb2.SCALA: ".scala"
            }

            extensions = [type_to_ext.get(t) for t in request.types if t in type_to_ext]

            path = self.bridge.project_root
            files = []

            for ext in extensions:
                for p in path.rglob(f"*{ext}"):
                    if p.is_file():
                        files.append({
                            "path": str(p),
                            "size_bytes": p.stat().st_size,
                            "language": ext[1:]
                        })

            response = warden_pb2.DiscoverResponse(
                success=True,
                total_files=len(files),
                analyzable_files=len(files)
            )

            for file in files[:1000]:
                response.files.append(ProtoConverters.convert_discovered_file(file))

            return response

        except Exception as e:
            logger.error("grpc_get_files_by_type_error: %s", str(e))
            return warden_pb2.DiscoverResponse(
                success=False,
                error_message=str(e)
            )

    async def DetectFrameworks(self, request, context) -> "warden_pb2.DiscoverResponse":
        """Detect frameworks used in project."""
        logger.info("grpc_detect_frameworks", path=request.path)

        try:
            if hasattr(self.bridge, 'detect_frameworks'):
                result = await self.bridge.detect_frameworks(path=request.path)

                response = warden_pb2.DiscoverResponse(success=True)

                for fw in result.get("frameworks", []):
                    response.frameworks.append(ProtoConverters.convert_framework(fw))

                return response

            path = Path(request.path)
            frameworks = []

            if (path / "requirements.txt").exists() or (path / "setup.py").exists():
                frameworks.append({
                    "name": "Python",
                    "language": "python",
                    "confidence": 0.9
                })
            if (path / "package.json").exists():
                frameworks.append({
                    "name": "Node.js",
                    "language": "javascript",
                    "confidence": 0.9
                })
            if (path / "Cargo.toml").exists():
                frameworks.append({
                    "name": "Rust",
                    "language": "rust",
                    "confidence": 0.9
                })
            if (path / "go.mod").exists():
                frameworks.append({
                    "name": "Go",
                    "language": "go",
                    "confidence": 0.9
                })

            response = warden_pb2.DiscoverResponse(success=True)
            for fw in frameworks:
                response.frameworks.append(ProtoConverters.convert_framework(fw))

            return response

        except Exception as e:
            logger.error("grpc_detect_frameworks_error: %s", str(e))
            return warden_pb2.DiscoverResponse(
                success=False,
                error_message=str(e)
            )

    async def GetProjectStats(self, request, context) -> "warden_pb2.ProjectStats":
        """Get project statistics."""
        logger.info("grpc_get_project_stats")

        try:
            path = self.bridge.project_root

            files_by_language: Dict[str, int] = {}
            lines_by_language: Dict[str, int] = {}
            total_size = 0
            total_lines = 0
            total_files = 0

            for p in path.rglob("*"):
                if p.is_file() and not any(part.startswith('.') for part in p.parts):
                    lang = self._detect_language(p)
                    if lang:
                        total_files += 1
                        total_size += p.stat().st_size
                        files_by_language[lang] = files_by_language.get(lang, 0) + 1

                        try:
                            line_count = len(p.read_text(errors='ignore').splitlines())
                            total_lines += line_count
                            lines_by_language[lang] = (
                                lines_by_language.get(lang, 0) + line_count
                            )
                        except Exception:
                            pass

            stats = warden_pb2.ProjectStats(
                total_files=total_files,
                total_lines=total_lines,
                total_size_bytes=total_size
            )
            stats.files_by_language.update(files_by_language)
            stats.lines_by_language.update(lines_by_language)

            return stats

        except Exception as e:
            logger.error("grpc_get_project_stats_error: %s", str(e))
            return warden_pb2.ProjectStats()

    def _detect_language(self, path: Path) -> str:
        """Detect language from file extension."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".java": "java",
            ".cs": "csharp",
            ".go": "go",
            ".rs": "rust",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
            ".hpp": "cpp",
            ".rb": "ruby",
            ".php": "php",
            ".kt": "kotlin",
            ".swift": "swift",
            ".scala": "scala"
        }
        return ext_map.get(path.suffix.lower(), "")
