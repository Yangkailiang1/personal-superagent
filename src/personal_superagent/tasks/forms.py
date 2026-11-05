from django import forms

from .models import Task


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        # 不接受 owner/status；归属和状态只能由服务端决定。
        fields = ["title", "description"]
        labels = {"title": "任务名称", "description": "任务需求"}
