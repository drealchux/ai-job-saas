# jobs/services.py
import requests
import json
import time
from typing import Dict, List, Optional
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class BrightDataScraper:
    """
    Handles all interaction with Bright Data scraping APIs.
    Abstracts the complexity of submitting jobs and polling results.
    """
    
    BASE_URL = "https://api.brightdata.com/datasets"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.BRIGHT_DATA_API_KEY
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def search_linkedin_jobs(self, query_params: Dict) -> Optional[str]:
        """
        Submit a LinkedIn job search to Bright Data.
        
        Args:
            query_params: {
                'role': 'Machine Learning Engineer',
                'location': 'Paris',
                'remote': 'true',
                'seniority': 'mid'
            }
        
        Returns:
            snapshot_id (str) or None if request failed
        """
        payload = {
            "dataset": "gm2r0d18d62qm2xyt",  # LinkedIn dataset ID (example)
            "call_type": "batch",
            "query": self._build_linkedin_search_url(query_params),
        }
        
        return self._submit_scrape_request(payload)
    
    def search_glassdoor_jobs(self, query_params: Dict) -> Optional[str]:
        """
        Submit a Glassdoor job search to Bright Data.
        
        Args:
            query_params: Dictionary of search parameters
        
        Returns:
            snapshot_id (str) or None if request failed
        """
        payload = {
            "dataset": "gm3ry5e2h0vt2p8r1",  # Glassdoor dataset ID (example)
            "call_type": "batch",
            "query": self._build_glassdoor_search_url(query_params),
        }
        
        return self._submit_scrape_request(payload)
    
    def _submit_scrape_request(self, payload: Dict) -> Optional[str]:
        """
        Generic method to submit a scrape request to Bright Data API.
        Returns immediately with snapshot ID, does not wait for completion.
        """
        try:
            response = requests.post(
                f"{self.BASE_URL}/request",
                json=payload,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            snapshot_id = data.get("snapshot_id")
            
            logger.info(f"Submitted scrape request. Snapshot ID: {snapshot_id}")
            return snapshot_id
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to submit scrape request: {str(e)}")
            return None
    
    def get_snapshot_status(self, snapshot_id: str) -> Dict:
        """
        Check the status of a scraping job.
        
        Returns:
            {
                'id': snapshot_id,
                'status': 'processing' | 'ready' | 'failed',
                'progress': 0-100,
                'data': {...} if ready
            }
        """
        try:
            response = requests.get(
                f"{self.BASE_URL}/{snapshot_id}/status",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            
            return response.json()
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get snapshot status for {snapshot_id}: {str(e)}")
            return {"status": "failed", "error": str(e)}
    
    def fetch_snapshot_data(self, snapshot_id: str, limit: int = 100) -> Optional[List[Dict]]:
        """
        Fetch the actual job listings from a completed snapshot.
        
        Returns:
            List of job dictionaries or None if failed
        """
        try:
            response = requests.get(
                f"{self.BASE_URL}/{snapshot_id}/data",
                headers=self.headers,
                params={"limit": limit},
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            return data.get("results", [])
        
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch snapshot data for {snapshot_id}: {str(e)}")
            return None
    
    def poll_until_ready(self, snapshot_id: str, max_wait_seconds: int = 300) -> bool:
        """
        Poll snapshot status until it's ready or timeout.
        Used mainly for testing. In production, Celery tasks do this.
        
        Returns:
            True if snapshot became ready, False if timeout/error
        """
        start = time.time()
        check_interval = 5  # seconds between checks
        
        while time.time() - start < max_wait_seconds:
            status = self.get_snapshot_status(snapshot_id)
            
            if status.get("status") == "ready":
                return True
            
            if status.get("status") == "failed":
                logger.error(f"Snapshot {snapshot_id} failed: {status.get('error')}")
                return False
            
            logger.info(f"Snapshot {snapshot_id} status: {status.get('status')}, "
                       f"progress: {status.get('progress')}%")
            
            time.sleep(check_interval)
        
        logger.warning(f"Snapshot {snapshot_id} polling timed out after {max_wait_seconds}s")
        return False
    
    @staticmethod
    def _build_linkedin_search_url(params: Dict) -> str:
        """
        Build LinkedIn search URL from extracted parameters.
        In reality, this would construct the actual LinkedIn search URL.
        """
        role = params.get("role", "")
        location = params.get("location", "")
        remote = params.get("remote", False)
        
        base_url = "https://www.linkedin.com/jobs/search"
        query_parts = []
        
        if role:
            query_parts.append(f"keywords={role}")
        if location:
            query_parts.append(f"location={location}")
        if remote:
            query_parts.append("f_WT=2")  # Remote filter
        
        return f"{base_url}?{'&'.join(query_parts)}"
    
    @staticmethod
    def _build_glassdoor_search_url(params: Dict) -> str:
        """
        Build Glassdoor search URL from extracted parameters.
        """
        role = params.get("role", "")
        location = params.get("location", "")
        
        base_url = "https://www.glassdoor.com/Job/jobs.htm"
        query_parts = [f"keyword={role}"] if role else []
        
        if location:
            query_parts.append(f"location={location}")
        
        return f"{base_url}?{'&'.join(query_parts)}"


class JobDataParser:
    """
    Transforms raw Bright Data results into structured JobListing objects.
    """
    
    @staticmethod
    def parse_linkedin_job(raw_data: Dict) -> Dict:
        """
        Extract relevant fields from LinkedIn job listing.
        
        Expected raw_data fields may vary; this is an example.
        """
        return {
            "title": raw_data.get("title", ""),
            "company": raw_data.get("company", ""),
            "location": raw_data.get("location", ""),
            "url": raw_data.get("link", raw_data.get("url", "")),
            "job_type": raw_data.get("job_type", ""),
            "salary": raw_data.get("salary", ""),
            "description": raw_data.get("description", ""),
            "applicants": raw_data.get("applicant_count"),
            "source": "linkedin"
        }
    
    @staticmethod
    def parse_glassdoor_job(raw_data: Dict) -> Dict:
        """
        Extract relevant fields from Glassdoor job listing.
        """
        return {
            "title": raw_data.get("jobTitle", ""),
            "company": raw_data.get("employerName", ""),
            "location": raw_data.get("location", ""),
            "url": raw_data.get("jobLink", ""),
            "job_type": raw_data.get("jobType", ""),
            "salary": raw_data.get("salary", ""),
            "description": raw_data.get("jobDescription", ""),
            "source": "glassdoor"
        }