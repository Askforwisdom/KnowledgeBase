"""
Knowledge management API routes
Provides unified import interface for files and directories with parallel processing
"""
import logging
import asyncio
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Form

from src.services.import_ import (
    knowledge_importer,
    KnowledgeImportRequest,
    KnowledgeManageRequest,
    ManageAction,
)
from src.services.search.vector_searcher import vector_searcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge"])


@router.post("/import")
async def import_knowledge(
    source_path: str = Form(...),
):
    """
    Unified knowledge import API
    Automatically uses pipeline mode with embedding generation
    
    Args:
        source_path: File or directory path
    """
    try:
        path = Path(source_path)
        
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"Path not found: {source_path}")
        
        if path.is_dir():
            results = await knowledge_importer.import_directory_pipeline(
                directory=path,
            )
            
            success_count = sum(1 for r in results if r.success)
            error_count = len(results) - success_count
            
            return {
                "success": error_count == 0,
                "total_knowledge": success_count,
                "total_chunks": success_count,
                "error_count": error_count,
                "errors": [r.errors for r in results if not r.success],
                "processing_time_ms": 0,
                "results": [
                    {
                        "file_path": r.file_path,
                        "status": "success" if r.success else "failed",
                        "knowledge_id": None,
                        "knowledge_name": None,
                        "chunks_count": r.knowledge_count if r.success else 0,
                        "error_message": "; ".join(r.errors) if not r.success else None,
                    }
                    for r in results
                ],
            }
        
        request = KnowledgeImportRequest(
            source_path=source_path,
        )
        
        response = await knowledge_importer.import_knowledge(request)
        
        return {
            "success": response.success,
            "total_knowledge": response.total_knowledge,
            "total_chunks": response.total_chunks,
            "error_count": response.error_count,
            "errors": response.errors,
            "processing_time_ms": response.processing_time_ms,
            "results": [
                {
                    "file_path": r.file_path,
                    "status": r.status,
                    "knowledge_id": r.knowledge_id,
                    "knowledge_name": r.knowledge_name,
                    "chunks_count": r.chunks_count,
                    "error_message": r.error_message,
                }
                for r in response.results
            ],
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.post("/rebuild-index")
async def rebuild_knowledge_index():
    """
    Rebuild knowledge index API
    """
    try:
        request = KnowledgeManageRequest(action=ManageAction.REBUILD_INDEX)
        response = await knowledge_importer.manage_knowledge(request)
        
        return {
            "success": response.success,
            "message": response.message,
        }
    
    except Exception as e:
        logger.error(f"Rebuild index failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Rebuild failed: {str(e)}")


@router.delete("/clear")
async def clear_knowledge():
    """
    Clear all knowledge API
    """
    try:
        request = KnowledgeManageRequest(action=ManageAction.CLEAR_ALL)
        response = await knowledge_importer.manage_knowledge(request)
        
        return {
            "success": response.success,
            "message": response.message,
        }
    
    except Exception as e:
        logger.error(f"Clear knowledge failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Clear failed: {str(e)}")


@router.post("/search")
async def search_knowledge(
    queries: List[str] = Form(..., description="Multiple query texts"),
    knowledge_type: str = Form(..., description="Knowledge type: form_structure or sdk_doc"),
):
    """
    Unified vector search API
    Supports multiple queries with parallel search, returns deduplicated document paths
    
    Args:
        queries: List of query texts
        knowledge_type: Knowledge type (form_structure, sdk_doc)
    """
    try:
        from src.models.knowledge import KnowledgeType, get_knowledge_type_config
        
        try:
            kt = KnowledgeType(knowledge_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid knowledge_type: {knowledge_type}")
        
        config = get_knowledge_type_config(kt)
        if not config:
            raise HTTPException(status_code=400, detail=f"No config found for knowledge_type: {knowledge_type}")
        
        query_list = [q.strip() for q in queries if q.strip()]
        
        search_tasks = [
            vector_searcher.search(
                query=q,
                k=config.search_k,
                min_score=config.search_min_score,
                knowledge_types=[kt],
            )
            for q in query_list
        ]
        
        all_results = await asyncio.gather(*search_tasks)
        
        seen_paths = set()
        unique_docs = []
        for results in all_results:
            for r in results:
                if r.doc_path and r.doc_path not in seen_paths:
                    seen_paths.add(r.doc_path)
                    unique_docs.append({
                        "doc_path": r.doc_path,
                        "doc_summary": r.doc_summary,
                    })
        
        return {
            "success": True,
            "knowledge_type": knowledge_type,
            "results": unique_docs,
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")
