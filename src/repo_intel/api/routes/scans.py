from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from repo_intel.api.deps import get_db_session
from repo_intel.core.enums import Severity
from repo_intel.schemas.scan import (
    AIInsightListResponse,
    AskRequest,
    AskResponse,
    CreateScanRequest,
    CreateScanResponse,
    FindingListResponse,
    GraphResponse,
    ScanArtifactsResponse,
    ScanSummaryResponse,
    ScanStatusResponse,
)
from repo_intel.services.scan_service import ScanService
from repo_intel.ai.validators import AIValidationError
from repo_intel.ai.vertex_client import VertexUnavailableError

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("", response_model=CreateScanResponse, status_code=status.HTTP_201_CREATED)
def create_scan(payload: CreateScanRequest, db: Session = Depends(get_db_session)) -> CreateScanResponse:
    service = ScanService(db)
    scan = service.create_scan(payload)
    return CreateScanResponse(
        scan_id=scan.id,
        status=scan.status,
        repo={"url": scan.repository.repo_url, "ref": scan.requested_ref},
    )


@router.get("/{scan_id}", response_model=ScanStatusResponse)
def get_scan(scan_id: UUID, db: Session = Depends(get_db_session)) -> ScanStatusResponse:
    service = ScanService(db)
    scan = service.get_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scan not found")
    return service.to_scan_status_response(scan)


@router.post("/{scan_id}/run", response_model=ScanStatusResponse)
def run_scan(scan_id: UUID, db: Session = Depends(get_db_session)) -> ScanStatusResponse:
    service = ScanService(db)
    scan = service.run_scan(scan_id)
    if scan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scan not found")
    return service.to_scan_status_response(scan)


@router.get("/{scan_id}/artifacts", response_model=ScanArtifactsResponse)
def get_scan_artifacts(scan_id: UUID, db: Session = Depends(get_db_session)) -> ScanArtifactsResponse:
    service = ScanService(db)
    artifacts = service.get_artifacts(scan_id)
    if artifacts is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scan not found")
    return artifacts


@router.get("/{scan_id}/graph", response_model=GraphResponse)
def get_scan_graph(scan_id: UUID, db: Session = Depends(get_db_session)) -> GraphResponse:
    service = ScanService(db)
    graph = service.get_graph(scan_id)
    if graph is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scan not found")
    return graph


@router.get("/{scan_id}/findings", response_model=FindingListResponse)
def get_scan_findings(
    scan_id: UUID,
    category: str | None = None,
    severity: Severity | None = None,
    db: Session = Depends(get_db_session),
) -> FindingListResponse:
    service = ScanService(db)
    findings = service.get_findings(scan_id, category=category, severity=severity.value if severity else None)
    if findings is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scan not found")
    return findings


@router.get("/{scan_id}/summary", response_model=ScanSummaryResponse)
def get_scan_summary(scan_id: UUID, db: Session = Depends(get_db_session)) -> ScanSummaryResponse:
    service = ScanService(db)
    summary = service.get_summary(scan_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scan not found")
    return summary


@router.get("/{scan_id}/insights", response_model=AIInsightListResponse)
def get_scan_insights(scan_id: UUID, db: Session = Depends(get_db_session)) -> AIInsightListResponse:
    service = ScanService(db)
    insights = service.get_insights(scan_id)
    if insights is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scan not found")
    return insights


@router.post("/{scan_id}/ask", response_model=AskResponse)
def ask_scan(scan_id: UUID, payload: AskRequest, db: Session = Depends(get_db_session)) -> AskResponse:
    service = ScanService(db)
    try:
        answer = service.ask(scan_id, payload.question)
    except VertexUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except AIValidationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if answer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scan not found")
    return answer
