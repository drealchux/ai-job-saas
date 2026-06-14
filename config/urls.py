# config/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

# Health check endpoint for Docker
def health_check(request):
    return JsonResponse({"status": "ok"})

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', health_check),
    
    # Accounts URLs
    path('accounts/', include('accounts.urls')),
    
    # Jobs/Search API URLs
    path('api/jobs/', include('jobs.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

from django.http import JsonResponse

# Move the import to the top