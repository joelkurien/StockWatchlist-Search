from django.urls import path
from .StockState import StockState

websocket_urlpatterns = [
    path("ws/stock/<str:stockTick>/", StockState.as_asgi())
]