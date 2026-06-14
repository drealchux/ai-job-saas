# jobs/models.py
from django.db import models
from django.contrib.auth.models import User
import json

class LLMResult(models.Model):
    """
    Represents a single user job search query and its processing status.
    This is the top-level entity that ties everything together.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('ready', 'Ready'),
        ('failed', 'Failed'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='llm_results')
    prompt = models.TextField(help_text="User's natural language job query")
    title = models.CharField(max_length=255, blank=True, help_text="Extracted/summarized title")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # LLM extraction results (what the agent figured out)
    extracted_params = models.JSONField(
        default=dict,
        help_text="Parsed params: role, location, seniority, remote, etc."
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"LLMResult #{self.id}: {self.prompt[:50]}"


class Snapshot(models.Model):
    """
    Tracks a single Bright Data scraping job.
    One LLMResult can have multiple Snapshots (e.g., one for LinkedIn, one for Glassdoor).
    """
    llm_result = models.ForeignKey(LLMResult, on_delete=models.CASCADE, related_name='snapshots')
    
    source = models.CharField(
        max_length=20,
        choices=[('linkedin', 'LinkedIn'), ('glassdoor', 'Glassdoor')],
        help_text="Which job board was scraped"
    )
    
    snapshot_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="Bright Data snapshot ID (use for status polling)"
    )
    
    ready = models.BooleanField(default=False, help_text="Is snapshot ready to fetch?")
    raw_data = models.JSONField(default=dict, help_text="Raw response from Bright Data")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['snapshot_id']),
            models.Index(fields=['ready']),
        ]
    
    def __str__(self):
        return f"Snapshot {self.snapshot_id} ({self.source})"


class JobListing(models.Model):
    """
    A parsed job listing extracted from Bright Data scraping results.
    Created when Celery worker processes a ready Snapshot.
    """
    llm_result = models.ForeignKey(LLMResult, on_delete=models.CASCADE, related_name='job_listings')
    snapshot = models.ForeignKey(Snapshot, on_delete=models.SET_NULL, null=True, blank=True)
    
    source = models.CharField(max_length=20, choices=[('linkedin', 'LinkedIn'), ('glassdoor', 'Glassdoor')])
    
    title = models.CharField(max_length=255)
    company = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    url = models.URLField()
    job_type = models.CharField(max_length=50, blank=True, help_text="Full-time, Contract, etc.")
    
    salary = models.CharField(max_length=255, blank=True, help_text="Salary range if available")
    description = models.TextField(blank=True, help_text="Job description HTML or plaintext")
    
    # AI-generated summary
    summary = models.TextField(blank=True, help_text="LLM summary of key points")
    relevance_score = models.FloatField(null=True, blank=True, help_text="0.0-1.0 relevance to query")
    
    posted_at = models.DateTimeField(null=True, blank=True)
    applicants = models.IntegerField(null=True, blank=True, help_text="Applicant count if available")
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['llm_result']),
            models.Index(fields=['source']),
        ]
    
    def __str__(self):
        return f"{self.title} at {self.company}"