"""React 单页应用静态文件服务。

普通 ``StaticFiles(html=True)`` 只会为真实目录查找 ``index.html``，
不会把 ``/dashboard`` 这类客户端路由回退到前端入口。此类在保留
真实静态文件和 404 行为的同时，为无扩展名的前端页面路径提供
``index.html`` fallback。
"""

from pathlib import Path

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class SPAStaticFiles(StaticFiles):
    """为 React ``BrowserRouter`` 提供安全的 History API fallback。"""

    _NON_SPA_PREFIXES = ("api/", "ws/", "assets/")

    @classmethod
    def _is_spa_route(cls, path: str) -> bool:
        normalized = path.lstrip("/")
        if normalized.startswith(cls._NON_SPA_PREFIXES):
            return False
        # 缺失的 JS、CSS、图片等资源应保持 404，不能返回 HTML。
        return Path(normalized).suffix == ""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if (
                exc.status_code != 404
                or scope["method"] not in ("GET", "HEAD")
                or not self.html
                or not self._is_spa_route(path)
            ):
                raise

            full_path, stat_result = self.lookup_path("index.html")
            if stat_result is None:
                raise
            return FileResponse(full_path, stat_result=stat_result)
