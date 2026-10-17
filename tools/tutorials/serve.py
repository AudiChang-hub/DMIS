"""教學影片專用的示範伺服器（只在本機錄影時使用，不影響正式程式）。

示範環境沒有 Google Vision 與背景工作程式，這裡把證件辨識換成回傳示範證件內容的替身，
並讓辨識工作直接在同一個程序執行，教學片才能呈現正常的「上傳 → 自動帶入 → 人工核對」流程。

用法：PYTHONPATH=<含 tutorial_settings.py 的資料夾> python tools/tutorials/serve.py [port]
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tutorial_settings")

import django  # noqa: E402

django.setup()

import django_rq  # noqa: E402
from django.core.management import call_command  # noqa: E402

import sales.jobs as jobs  # noqa: E402

DEMO_OWNER = {
    "name": "王小明",
    "birth_date": "1991-05-20",
    "id_number": "A123456789",
    "id_number_valid": True,
    "address": "新北市示範區示範路1號",
}


def fake_recognize_id_card(front_bytes, back_bytes, document_type="national_id"):
    return {"fields": dict(DEMO_OWNER), "warnings": [], "rotation": {"front": 0, "back": 0}}


class ImmediateQueue:
    """代替 Redis 佇列：加入工作時直接執行。"""

    count = 0

    def enqueue(self, function, *args, **kwargs):
        function(*args)


jobs.recognize_id_card = fake_recognize_id_card
django_rq.get_queue = lambda *args, **kwargs: ImmediateQueue()

if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else "8792"
    call_command("runserver", f"127.0.0.1:{port}", use_reloader=False)
