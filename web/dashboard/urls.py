from django.urls import path

from dashboard import views

urlpatterns = [
    path("", views.home, name="home"),
    path("t/<str:ticker>/", views.ticker_detail, name="ticker"),
    path("c/<int:chunk_id>/", views.citation, name="citation"),
    path("status/", views.status, name="status"),
]
