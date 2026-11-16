"""說明截圖專用的示範伺服器（只在本機重拍截圖時用）。

示範環境沒有 Google Vision 與 Redis：證件辨識換成回傳合成證件內容的替身（自動裁切仍用真的），
背景工作改在同一個程序直接執行。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "help_demo_settings")

import django  # noqa: E402

django.setup()

import django_rq  # noqa: E402
from django.core.management import call_command  # noqa: E402

import sales.jobs as jobs  # noqa: E402
from sales.services import id_ocr  # noqa: E402

DEMO_OWNER = {"name": "王小明", "birth_date": "1990-05-12", "id_number": "A123456789", "id_number_valid": True,
              "address": "示範市中正區示範路100號"}


def fake_recognize_id_card(front_bytes, back_bytes, document_type="national_id", crops=None):
    crop = {}
    for side, data in (("front", front_bytes), ("back", back_bytes)):
        try:
            crop[side] = id_ocr._crop_params(id_ocr._load_image(data), (crops or {}).get(side), side)
        except Exception:  # 合成照片偵測不到卡片時，照正式流程改用整張圖
            crop[side] = None
    return {"fields": dict(DEMO_OWNER), "warnings": [], "rotation": {"front": 0, "back": 0}, "crop": crop}


class ImmediateQueue:
    count = 0

    def enqueue(self, function, *args, **kwargs):
        function(*args)


jobs.recognize_id_card = fake_recognize_id_card
django_rq.get_queue = lambda *args, **kwargs: ImmediateQueue()

if __name__ == "__main__":
    call_command("runserver", f"127.0.0.1:{sys.argv[1] if len(sys.argv) > 1 else '8796'}", use_reloader=False)
