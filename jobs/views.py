# jobs/views.py
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.db.models import Q
import json
import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status as http_status

from .models import LLMResult, Snapshot, JobListing
from .agents import JobSearchAgent
from .tasks import poll_snapshot_status

logger = logging.getLogger(__name__)


@login_required
def job_search_page(request):
    """
    Render the main job search form page.
    """
    return render(request, 'jobs/search.html')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_job_query(request):
    """
    API endpoint to submit a job search query.
    
    Request body:
        {
            "query": "ML engineer in Paris, remote, fintech startup"
        }
    
    Response:
        {
            "success": true,
            "llm_result_id": 123,
            "status": "pending",
            "message": "Search submitted. Check results below..."
        }
    
    This endpoint returns IMMEDIATELY and queues async tasks.
    The user polls for status updates.
    """
    
    try:
        data = request.data
        user_query = data.get('query', '').strip()
        
        if not user_query:
            return Response(
                {"error": "Query cannot be empty"},
                status=http_status.HTTP_400_BAD_REQUEST
            )
        
        # Create LLMResult immediately (status = pending)
        llm_result = LLMResult.objects.create(
            user=request.user,
            prompt=user_query,
            status='pending'
        )
        
        logger.info(f"Created LLMResult {llm_result.id} for user {request.user.id}")
        
        # Queue agent execution as a background task
        execute_job_search_agent.delay(llm_result.id)
        
        return Response({
            "success": True,
            "llm_result_id": llm_result.id,
            "status": "pending",
            "message": f"Search submitted. Your job listings will appear shortly."
        }, status=http_status.HTTP_202_ACCEPTED)
    
    except Exception as e:
        logger.error(f"Error in submit_job_query: {str(e)}")
        return Response(
            {"error": str(e)},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_search_status(request, llm_result_id: int):
    """
    Poll for the status of a job search.
    
    Response:
        {
            "status": "pending" | "processing" | "ready" | "failed",
            "total_jobs": 25,
            "snapshot_count": 2,
            "snapshots_ready": 1,
            "job_listings": [...]  (only if status == ready)
        }
    """
    
    try:
        llm_result = get_object_or_404(LLMResult, id=llm_result_id, user=request.user)
        
        response_data = {
            "id": llm_result.id,
            "status": llm_result.status,
            "prompt": llm_result.prompt,
            "created_at": llm_result.created_at.isoformat(),
            "total_jobs": JobListing.objects.filter(llm_result=llm_result).count(),
            "snapshot_count": Snapshot.objects.filter(llm_result=llm_result).count(),
            "snapshots_ready": Snapshot.objects.filter(llm_result=llm_result, ready=True).count(),
        }
        
        # If status is ready, include job listings
        if llm_result.status == 'ready':
            jobs = JobListing.objects.filter(llm_result=llm_result)
            response_data["job_listings"] = [
                {
                    "id": job.id,
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "url": job.url,
                    "salary": job.salary,
                    "job_type": job.job_type,
                    "source": job.source,
                    "summary": job.summary,
                    "created_at": job.created_at.isoformat(),
                }
                for job in jobs[:100]  # Limit to 100 for API response
            ]
        
        return Response(response_data)
    
    except Exception as e:
        logger.error(f"Error in get_search_status: {str(e)}")
        return Response(
            {"error": str(e)},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@login_required
def results_page(request, llm_result_id: int):
    """
    Display job search results page.
    This is a traditional server-rendered view.
    """
    
    llm_result = get_object_or_404(LLMResult, id=llm_result_id, user=request.user)
    
    # Get related snapshots and job listings
    snapshots = Snapshot.objects.filter(llm_result=llm_result)
    job_listings = JobListing.objects.filter(llm_result=llm_result).order_by('-created_at')
    
    context = {
        "llm_result": llm_result,
        "snapshots": snapshots,
        "job_listings": job_listings,
        "total_jobs": job_listings.count(),
    }
    
    return render(request, 'jobs/results.html', context)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_search_history(request):
    """
    Get user's search history with pagination.
    """
    
    user_results = LLMResult.objects.filter(user=request.user).order_by('-created_at')
    
    # Pagination
    page = request.query_params.get('page', 1)
    per_page = request.query_params.get('per_page', 20)
    
    start = (int(page) - 1) * int(per_page)
    end = start + int(per_page)
    
    total = user_results.count()
    results = user_results[start:end]
    
    response_data = {
        "total": total,
        "page": int(page),
        "per_page": int(per_page),
        "results": [
            {
                "id": r.id,
                "prompt": r.prompt,
                "status": r.status,
                "job_count": JobListing.objects.filter(llm_result=r).count(),
                "created_at": r.created_at.isoformat(),
            }
            for r in results
        ]
    }
    
    return Response(response_data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def job_listing_detail(request, job_id: int):
    """
    Get detailed info about a single job listing.
    """
    
    job = get_object_or_404(JobListing, id=job_id)
    
    # Check user owns this job's search
    if job.llm_result.user != request.user:
        return Response(
            {"error": "Not authorized"},
            status=http_status.HTTP_403_FORBIDDEN
        )
    
    response_data = {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "job_type": job.job_type,
        "salary": job.salary,
        "source": job.source,
        "summary": job.summary,
        "description": job.description,
        "applicants": job.applicants,
        "created_at": job.created_at.isoformat(),
    }
    
    return Response(response_data)


# Celery task that's called from submit_job_query
from .tasks import poll_snapshot_status as poll_snapshot_task

@shared_task
def execute_job_search_agent(llm_result_id: int):
    """
    Background task that executes the LangChain agent.
    Called immediately after user submits a query.
    """
    try:
        llm_result = LLMResult.objects.get(id=llm_result_id)
        
        # Update status to processing
        llm_result.status = 'processing'
        llm_result.save()
        
        logger.info(f"Executing job search agent for LLMResult {llm_result_id}")
        
        # Run the LangChain agent
        agent = JobSearchAgent()
        result = agent.run_agent(llm_result.prompt)
        
        if not result.get("success"):
            llm_result.status = 'failed'
            llm_result.save()
            logger.error(f"Agent execution failed for LLMResult {llm_result_id}")
            return
        
        # Store extracted parameters
        llm_result.extracted_params = result.get("extracted_params", {})
        llm_result.title = llm_result.extracted_params.get("role", "Job Search")
        llm_result.save()
        
        # The agent should have called tools which create Snapshot objects
        # Now queue tasks to poll those snapshots
        snapshots = Snapshot.objects.filter(llm_result=llm_result)
        
        for snapshot in snapshots:
            logger.info(f"Queuing poll task for snapshot {snapshot.snapshot_id}")
            poll_snapshot_task.delay(snapshot.snapshot_id)
    
    except Exception as e:
        logger.error(f"Error executing job search agent: {str(e)}")


# Import this at the top
from celery import shared_task