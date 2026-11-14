from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from dashboard import api
from tiweb.security import ThrottledLoginView

urlpatterns = [
    path("login/", ThrottledLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # The admin's own login form isn't throttled: send it through ours.
    path("admin/login/", RedirectView.as_view(pattern_name="login", query_string=True)),
    path("admin/", admin.site.urls),
    path("api/login", api.login),
    path("api/runs/latest", api.latest_run),
    path("api/runs/<int:run_id>/suggestions", api.run_suggestions),
    path("api/tickers/<str:ticker>/suggestions", api.ticker_suggestions),
    path("api/prices", api.prices),
    path("api/citations", api.citations),
    path("api/screen/latest", api.latest_screen),
    path("", include("dashboard.urls")),
]
