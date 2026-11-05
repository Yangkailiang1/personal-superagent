from django.urls import path
from . import views
from personal_superagent.execution import views as execution_views

urlpatterns = [
    path("", views.task_list, name="task_list"),
    path("tasks/<uuid:task_id>/", views.task_detail, name="task_detail"),
    path("tasks/<uuid:task_id>/start/", execution_views.start, name="attempt_start"),
    path("tasks/<uuid:task_id>/attempts/<uuid:attempt_id>/cancel/", execution_views.cancel, name="attempt_cancel"),
    path("tasks/<uuid:task_id>/attempts/<uuid:attempt_id>/events/", execution_views.events, name="attempt_events"),
    path("tasks/<uuid:task_id>/attempts/<uuid:attempt_id>/approvals/<int:approval_id>/", execution_views.decision, name="approval_decide"),
    path("tasks/<uuid:task_id>/attempts/<uuid:attempt_id>/resume/", execution_views.restore, name="attempt_resume"),
    path("tasks/<uuid:task_id>/attempts/<uuid:attempt_id>/artifacts/<int:artifact_id>/", execution_views.artifact, name="artifact"),
]
