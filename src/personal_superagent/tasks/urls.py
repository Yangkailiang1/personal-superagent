from django.urls import path
from . import views

urlpatterns = [
    path("", views.task_list, name="task_list"),
    path("tasks/<uuid:task_id>/", views.task_detail, name="task_detail"),
]
