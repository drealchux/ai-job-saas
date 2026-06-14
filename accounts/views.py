# accounts/views.py
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from .forms import UserCreationForm
import logging

logger = logging.getLogger(__name__)


@require_http_methods(['GET', 'POST'])
def signup(request):
    """User registration view"""
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            logger.info(f"New user created: {user.username}")
            login(request, user)
            return redirect('jobs:search_page')
    else:
        form = UserCreationForm()
    
    return render(request, 'accounts/signup.html', {'form': form})


@require_http_methods(['GET', 'POST'])
def login_view(request):
    """User login view"""
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            logger.info(f"User logged in: {username}")
            return redirect('jobs:search_page')
        else:
            logger.warning(f"Failed login attempt: {username}")
    
    return render(request, 'accounts/login.html')


@require_http_methods(['POST'])
@login_required
def logout_view(request):
    """User logout view"""
    username = request.user.username
    logout(request)
    logger.info(f"User logged out: {username}")
    return redirect('accounts:login')