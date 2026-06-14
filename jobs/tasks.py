# jobs/tasks.py
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging
import time

from .models import LLMResult, Snapshot, JobListing
from .services import BrightDataScraper, JobDataParser
from .agents import JobSearchAgent

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5)
def poll_snapshot_status(self, snapshot_id: str, max_attempts: int = 60):
    """
    Poll a Bright Data snapshot until it's ready.
    Celery will retry this task if it fails.
    
    This is non-blocking - the user sees immediate feedback via LLMResult status updates.
    """
    scraper = BrightDataScraper()
    
    try:
        snapshot = Snapshot.objects.get(snapshot_id=snapshot_id)
    except Snapshot.DoesNotExist:
        logger.error(f"Snapshot {snapshot_id} not found in database")
        return
    
    try:
        status_response = scraper.get_snapshot_status(snapshot_id)
        current_status = status_response.get("status")
        
        logger.info(f"Snapshot {snapshot_id} status: {current_status}")
        
        # If ready, trigger data fetch
        if current_status == "ready":
            snapshot.ready = True
            snapshot.save()
            
            # Trigger next task to fetch and process data
            fetch_and_process_snapshot.delay(snapshot_id)
            return
        
        # If failed, mark the LLMResult as failed
        elif current_status == "failed":
            snapshot.llm_result.status = 'failed'
            snapshot.llm_result.save()
            logger.error(f"Snapshot {snapshot_id} failed")
            return
        
        # Still processing, retry this task
        elif current_status == "processing":
            # Calculate exponential backoff
            countdown = min(2 ** self.request.retries, 60)  # Max 60 seconds
            raise self.retry(countdown=countdown)
    
    except Exception as e:
        logger.error(f"Error polling snapshot {snapshot_id}: {str(e)}")
        # Retry with exponential backoff
        try:
            self.retry(exc=e, countdown=min(2 ** self.request.retries, 60))
        except self.MaxRetriesExceededError:
            snapshot.llm_result.status = 'failed'
            snapshot.llm_result.save()


@shared_task
def fetch_and_process_snapshot(snapshot_id: str):
    """
    Fetch results from a ready snapshot and create JobListing objects.
    This runs after poll_snapshot_status confirms the snapshot is ready.
    """
    scraper = BrightDataScraper()
    
    try:
        snapshot = Snapshot.objects.get(snapshot_id=snapshot_id)
    except Snapshot.DoesNotExist:
        logger.error(f"Snapshot {snapshot_id} not found")
        return
    
    try:
        # Fetch the actual job data
        job_data = scraper.fetch_snapshot_data(snapshot_id)
        
        if not job_data:
            logger.warning(f"No job data returned for snapshot {snapshot_id}")
            return
        
        # Store raw data in snapshot for auditing
        snapshot.raw_data = {"jobs": job_data, "count": len(job_data)}
        snapshot.save()
        
        # Parse and create JobListing objects
        parser = JobDataParser()
        created_count = 0
        
        for job_item in job_data:
            # Choose parser based on source
            if snapshot.source == "linkedin":
                parsed = parser.parse_linkedin_job(job_item)
            elif snapshot.source == "glassdoor":
                parsed = parser.parse_glassdoor_job(job_item)
            else:
                continue
            
            # Create or update JobListing
            job_listing, created = JobListing.objects.get_or_create(
                llm_result=snapshot.llm_result,
                url=parsed.get("url"),
                defaults={
                    "snapshot": snapshot,
                    "source": snapshot.source,
                    "title": parsed.get("title", ""),
                    "company": parsed.get("company", ""),
                    "location": parsed.get("location", ""),
                    "job_type": parsed.get("job_type", ""),
                    "salary": parsed.get("salary", ""),
                    "description": parsed.get("description", ""),
                    "applicants": parsed.get("applicants"),
                }
            )
            
            if created:
                created_count += 1
        
        logger.info(f"Created {created_count} job listings from snapshot {snapshot_id}")
        
        # Trigger LLM summarization for newly created listings
        summarize_job_listings.delay(snapshot.llm_result.id)
    
    except Exception as e:
        logger.error(f"Error processing snapshot {snapshot_id}: {str(e)}")


@shared_task
def summarize_job_listings(llm_result_id: int):
    """
    Use LLM to generate summaries for job listings.
    This adds value by extracting key points from job descriptions.
    """
    try:
        llm_result = LLMResult.objects.get(id=llm_result_id)
    except LLMResult.DoesNotExist:
        return
    
    agent = JobSearchAgent()
    
    # Get all job listings without summaries
    jobs_to_summarize = JobListing.objects.filter(
        llm_result=llm_result,
        summary=""
    )
    
    for job in jobs_to_summarize:
        if not job.description:
            continue
        
        try:
            # Create summarization prompt
            summary_prompt = f"""Summarize this job posting in 2-3 sentences, focusing on key responsibilities and requirements:

Title: {job.title}
Company: {job.company}
Description: {job.description[:1000]}"""  # Limit to first 1000 chars
            
            # Use LLM to summarize
            from langchain_openai import ChatOpenAI
            from django.conf import settings
            
            llm = ChatOpenAI(
                model="gpt-3.5-turbo",
                temperature=0.3,
                api_key=settings.OPENAI_API_KEY
            )
            
            response = llm.invoke(summary_prompt)
            job.summary = response.content if hasattr(response, 'content') else str(response)
            job.save()
            
            logger.info(f"Summarized job listing {job.id}")
        
        except Exception as e:
            logger.error(f"Failed to summarize job {job.id}: {str(e)}")
            continue
    
    # Check if all snapshots are ready and processed
    all_snapshots_ready = not Snapshot.objects.filter(
        llm_result=llm_result,
        ready=False
    ).exists()
    
    if all_snapshots_ready:
        llm_result.status = 'ready'
        llm_result.save()
        logger.info(f"LLMResult {llm_result_id} is now ready for user display")


@shared_task
def cleanup_old_snapshots(days: int = 7):
    """
    Periodic task to clean up old snapshots and raw data.
    Run this via Celery Beat on a schedule (e.g., daily).
    """
    cutoff_date = timezone.now() - timedelta(days=days)
    
    old_snapshots = Snapshot.objects.filter(created_at__lt=cutoff_date)
    count = old_snapshots.count()
    
    old_snapshots.delete()
    
    logger.info(f"Deleted {count} old snapshots")