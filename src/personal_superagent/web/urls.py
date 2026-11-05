from django.contrib.auth import views as auth_views
from django.urls import include, path
from . import dashboard
from personal_superagent.devices import views as device_views

urlpatterns = [
    path("app/", dashboard.index, name="dashboard"),
    path("app/assets/<path:path>", dashboard.asset),
    path("api/device/<str:action>/", device_views.endpoint),
    path("api/<str:action>/", dashboard.api),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("personal_superagent.tasks.urls")),
]
