from django.contrib.auth import views as auth_views
from django.urls import include, path
from . import dashboard, board
from personal_superagent.collaboration import views as collaboration_views, assets
from personal_superagent.intake import views as intake_views
from personal_superagent.devices import views as device_views

urlpatterns = [
    path("app/", dashboard.index, name="dashboard"),
    path("app/assets/<path:path>", dashboard.asset),
    path("api/device/<str:action>/", device_views.endpoint),
    path("api/intake/<str:action>/", intake_views.endpoint),
    path("api/dashboard/", board.dashboard),
    path("api/collaboration/<str:action>/",collaboration_views.endpoint),
    path("api/images/<int:id>/",assets.image),
    path("api/<str:action>/", dashboard.api),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("personal_superagent.tasks.urls")),
]
