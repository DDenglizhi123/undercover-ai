# core/asgi.py
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# 1. 必须先初始化 Django 的 HTTP 处理器！
# 这一步必须在导入 channels 之前完成
django_asgi_app = get_asgi_application()

# 2. 然后再导入 Channels 相关的模块和你的路由
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import chat.routing

# 3. 定义核心路由规则：
# - 如果是普通的 http 请求，交给 django_asgi_app 处理
# - 如果是 websocket 请求，交给 AuthMiddlewareStack 和你的 chat.routing 处理
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            chat.routing.websocket_urlpatterns
        )
    ),
})