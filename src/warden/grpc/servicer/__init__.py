"""
Warden gRPC Servicer

Modular implementation of WardenService with 51 endpoints.
"""

from warden.grpc.servicer.base import WardenServicerBase
from warden.grpc.servicer.mixins.pipeline import PipelineMixin
from warden.grpc.servicer.mixins.issue_management import IssueManagementMixin
from warden.grpc.servicer.mixins.result_analysis import ResultAnalysisMixin
from warden.grpc.servicer.mixins.report_generation import ReportGenerationMixin
from warden.grpc.servicer.mixins.semantic_search import SemanticSearchMixin
from warden.grpc.servicer.mixins.file_discovery import FileDiscoveryMixin
from warden.grpc.servicer.mixins.llm_operations import LlmOperationsMixin
from warden.grpc.servicer.mixins.cleanup import CleanupMixin
from warden.grpc.servicer.mixins.fortification import FortificationMixin
from warden.grpc.servicer.mixins.suppression import SuppressionMixin
from warden.grpc.servicer.mixins.configuration import ConfigurationMixin
from warden.grpc.servicer.mixins.health_status import HealthStatusMixin

# Import generated protobuf code
try:
    from warden.grpc.generated import warden_pb2_grpc
except ImportError:
    warden_pb2_grpc = None


class WardenServicer(
    PipelineMixin,
    IssueManagementMixin,
    ResultAnalysisMixin,
    ReportGenerationMixin,
    SemanticSearchMixin,
    FileDiscoveryMixin,
    LlmOperationsMixin,
    CleanupMixin,
    FortificationMixin,
    SuppressionMixin,
    ConfigurationMixin,
    HealthStatusMixin,
    WardenServicerBase,
    warden_pb2_grpc.WardenServiceServicer if warden_pb2_grpc else object
):
    """
    Complete gRPC service implementation with 51 endpoints.

    Combines all mixins to provide full WardenService functionality.
    """
    pass


__all__ = ["WardenServicer"]
