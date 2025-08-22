from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/stocksearch/", views.searchStock, name="searchStock"),
    path("api/stockbasicmetrics/", views.getBasicFinancialMetrics, name="getBasicFinancialMetrics")
]