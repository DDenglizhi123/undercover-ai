# chat/routing.py
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # 加上 ^ 和 $ 确保精确匹配 ws/chat/lobby/
    re_path(r'^ws/chat/(?P<room_name>\w+)/$', consumers.ChatConsumer.as_asgi()),
]