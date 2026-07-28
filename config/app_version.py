import hashlib
from functools import lru_cache
from pathlib import Path

from django.conf import settings


@lru_cache(maxsize=1)
def get_app_version():
    """以實際部署內容產生版本碼，不依賴 Git 或人工更新環境變數。"""
    digest = hashlib.sha256()
    roots = ("config", "sales", "templates", "static")
    extensions = {".py", ".html", ".css", ".js"}
    for root_name in roots:
        root = Path(settings.BASE_DIR) / root_name
        for path in sorted(root.rglob("*")):
            if (
                path.is_file()
                and path.suffix in extensions
                and "__pycache__" not in path.parts
            ):
                digest.update(path.relative_to(settings.BASE_DIR).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()[:12]
