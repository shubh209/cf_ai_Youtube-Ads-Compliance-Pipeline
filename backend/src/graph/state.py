import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class ComplianceIssue(TypedDict, total=False):
    category: str
    description: str
    severity: str
    timestamp: Optional[str]
    citation_source: Optional[str]
    citation_excerpt: Optional[str]
    chunk_id: Optional[str]
    confidence: Optional[str]


class VideoAuditState(TypedDict, total=False):
    video_url: str
    video_id: str
    local_file_path: Optional[str]
    video_metadata: Dict[str, Any]
    transcript: Optional[str]
    ocr_text: List[str]
    ingestion_source: Optional[str]
    policy_version_id: Optional[str]
    platforms: List[str]
    audit_mode: str
    processing_status: str
    compliance_results: Annotated[List[ComplianceIssue], operator.add]
    final_status: str
    final_report: str
    errors: Annotated[List[str], operator.add]
