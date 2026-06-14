# jobs/urls.py
from django.urls import path
from . import views

app_name = 'jobs'

urlpatterns = [
    # Web pages
    path('search/', views.job_search_page, name='search_page'),
    path('results/<int:llm_result_id>/', views.results_page, name='results_page'),
    
    # API endpoints
    path('submit/', views.submit_job_query, name='submit_query'),
    path('status/<int:llm_result_id>/', views.get_search_status, name='get_status'),
    path('history/', views.user_search_history, name='search_history'),
    path('listing/<int:job_id>/', views.job_listing_detail, name='listing_detail'),
]