# jobs/admin.py
from django.contrib import admin
from .models import LLMResult, Snapshot, JobListing


@admin.register(LLMResult)
class LLMResultAdmin(admin.ModelAdmin):
    """Admin interface for LLMResult"""
    list_display = ['id', 'user', 'prompt_preview', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['prompt', 'user__username']
    readonly_fields = ['created_at', 'updated_at', 'extracted_params']
    fieldsets = (
        ('Query Info', {
            'fields': ('user', 'prompt', 'title')
        }),
        ('Processing', {
            'fields': ('status', 'extracted_params')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def prompt_preview(self, obj):
        """Show truncated prompt in list view"""
        return obj.prompt[:50] + '...' if len(obj.prompt) > 50 else obj.prompt
    prompt_preview.short_description = 'Prompt'


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    """Admin interface for Snapshot"""
    list_display = ['id', 'llm_result', 'source', 'snapshot_id', 'ready', 'created_at']
    list_filter = ['source', 'ready', 'created_at']
    search_fields = ['snapshot_id', 'llm_result__prompt']
    readonly_fields = ['created_at', 'updated_at', 'snapshot_id', 'raw_data']
    fieldsets = (
        ('Scraping Job', {
            'fields': ('llm_result', 'source', 'snapshot_id')
        }),
        ('Status', {
            'fields': ('ready',)
        }),
        ('Data', {
            'fields': ('raw_data',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(JobListing)
class JobListingAdmin(admin.ModelAdmin):
    """Admin interface for JobListing"""
    list_display = ['id', 'title', 'company', 'location', 'source', 'created_at']
    list_filter = ['source', 'created_at', 'job_type']
    search_fields = ['title', 'company', 'location']
    readonly_fields = ['created_at', 'llm_result']
    fieldsets = (
        ('Job Info', {
            'fields': ('title', 'company', 'location', 'url')
        }),
        ('Details', {
            'fields': ('job_type', 'salary', 'source')
        }),
        ('Content', {
            'fields': ('description', 'summary'),
            'classes': ('collapse',)
        }),
        ('Analysis', {
            'fields': ('relevance_score', 'applicants'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('llm_result', 'snapshot', 'posted_at', 'created_at'),
            'classes': ('collapse',)
        }),
    )