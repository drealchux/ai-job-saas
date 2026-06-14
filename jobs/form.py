# jobs/forms.py
from django import forms
from .models import LLMResult


class JobQueryForm(forms.ModelForm):
    """Form for submitting a job search query"""
    
    class Meta:
        model = LLMResult
        fields = ['prompt']
        widgets = {
            'prompt': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., ML engineer in Paris, remote, fintech startup',
                'rows': 4,
                'required': True
            })
        }
        labels = {
            'prompt': 'What kind of job are you looking for?'
        }