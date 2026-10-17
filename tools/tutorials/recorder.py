"""教學影片錄製：Playwright 操作畫面並錄影，旁白（Hanhan）與字幕以 ffmpeg 合成 MP4（1920×1080，畫面 1600×900 置中、下方字幕帶）。

每一段旁白先產生語音、量好秒數，錄影時動作配合旁白長度等待，最後把每段語音放在對應時間點並燒入字幕。
"""
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg

from tts import synthesize

VIEWPORT = {"width": 1600, "height": 900}
SCALE = 1  # Playwright 錄影以 CSS 像素為準（放大倍率不會讓畫面變清楚）；錄 1600×900 原尺寸放進 1920×1080，不縮放。
FONT_FILE = Path(r"C:\Windows\Fonts\msjh.ttc")

# 畫面上的游標與點擊漣漪（Playwright 不會錄到系統游標）。
CURSOR_SCRIPT = """
(() => {
  const install = () => {
    if (document.getElementById('tut-cursor')) return;
    const style = document.createElement('style');
    style.textContent = `
      #tut-cursor{position:fixed;z-index:2147483647;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;
        background:rgba(52,70,240,.28);border:2px solid rgba(52,70,240,.9);box-shadow:0 2px 8px rgba(0,0,0,.25);pointer-events:none;
        transition:transform .12s ease}
      #tut-cursor.is-down{transform:scale(.7)}
      .tut-ripple{position:fixed;z-index:2147483646;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;
        border:3px solid rgba(52,70,240,.85);pointer-events:none;animation:tut-ripple .55s ease-out forwards}
      @keyframes tut-ripple{to{transform:scale(4);opacity:0}}
      .tut-focus{outline:4px solid rgba(255,170,0,.95)!important;outline-offset:3px!important;border-radius:10px;transition:outline-color .2s}
      #tut-title{position:fixed;z-index:2147483645;inset:0;display:grid;place-items:center;background:rgba(14,20,40,.78);
        color:#fff;font-family:"Microsoft JhengHei",sans-serif;text-align:center;pointer-events:none;transition:opacity .5s}
      #tut-title h1{margin:0 0 12px;font-size:56px;letter-spacing:.04em}
      #tut-title p{margin:0;font-size:26px;opacity:.85}`;
    document.head.appendChild(style);
    const dot = document.createElement('div');
    dot.id = 'tut-cursor';
    dot.style.left = (window.__tutX || 800) + 'px';
    dot.style.top = (window.__tutY || 450) + 'px';
    document.body.appendChild(dot);
    addEventListener('mousemove', e => { window.__tutX = e.clientX; window.__tutY = e.clientY; dot.style.left = e.clientX + 'px'; dot.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      dot.classList.add('is-down');
      const ripple = document.createElement('div'); ripple.className = 'tut-ripple';
      ripple.style.left = e.clientX + 'px'; ripple.style.top = e.clientY + 'px';
      document.body.appendChild(ripple); setTimeout(() => ripple.remove(), 600);
    }, true);
    addEventListener('mouseup', () => dot.classList.remove('is-down'), true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
})();
"""


@dataclass
class Cue:
    start: float
    end: float
    text: str
    audio: Path


class Recorder:
    def __init__(self, page, work_dir, t0):
        self.page = page
        self.work = Path(work_dir)
        self.t0 = t0
        self.cues = []
        self.deadline = 0.0
        self.mouse = (640, 360)

    def now(self):
        return time.monotonic() - self.t0

    # ---- 旁白 ----
    def say(self, text, *, rate=1):
        """開始一段旁白；接下來的動作與這段語音同時進行，wait() 等語音講完。"""
        self.wait()
        index = len(self.cues) + 1
        audio = self.work / "voice" / f"{index:02d}.wav"
        seconds = synthesize(text, audio, rate=rate)
        start = self.now()
        self.cues.append(Cue(start, start + seconds, text, audio))
        self.deadline = start + seconds

    def wait(self, pad=0.35):
        remaining = self.deadline - self.now() + pad
        if remaining > 0:
            time.sleep(remaining)

    def pause(self, seconds):
        time.sleep(seconds)

    # ---- 操作 ----
    def _move_to(self, locator):
        locator.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'smooth'})")
        time.sleep(0.6)
        box = locator.bounding_box()
        if not box:
            return None
        target = (box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        self.page.mouse.move(*target, steps=24)
        self.mouse = target
        return target

    def highlight(self, locator, seconds=0.9):
        self._move_to(locator)
        locator.evaluate("el => el.classList.add('tut-focus')")
        time.sleep(seconds)
        locator.evaluate("el => el.classList.remove('tut-focus')")

    def click(self, locator, *, after=0.6):
        self._move_to(locator)
        time.sleep(0.25)
        self.page.mouse.down()
        time.sleep(0.08)
        self.page.mouse.up()
        time.sleep(after)

    def type(self, locator, text, *, delay=110):
        self.click(locator, after=0.2)
        locator.press_sequentially(text, delay=delay)
        time.sleep(0.4)

    def pick(self, field_id, search_text, option_text):
        """可搜尋的下拉選單：點搜尋框、輸入關鍵字，再點選選項。"""
        search = self.page.locator(f"#{field_id}-search")
        self.click(search, after=0.3)
        if search_text:
            search.press_sequentially(search_text, delay=120)
            time.sleep(0.5)
        option = self.page.locator(f"#{field_id}-search-options [role=option]", has_text=option_text).first
        self.click(option, after=0.6)

    def choose(self, locator, label):
        """一般下拉選單：移到欄位、標示後選擇。"""
        self.highlight(locator, 0.5)
        locator.select_option(label=label)
        time.sleep(0.6)

    def scroll_by(self, pixels, seconds=1.6):
        steps = 16
        for _ in range(steps):
            self.page.mouse.wheel(0, pixels / steps)
            time.sleep(seconds / steps)

    def title(self, heading, subtitle, seconds=3.2):
        self.page.evaluate(
            """([h, s]) => { const el = document.createElement('div'); el.id = 'tut-title';
               el.innerHTML = '<div><h1></h1><p></p></div>'; el.querySelector('h1').textContent = h;
               el.querySelector('p').textContent = s; document.body.appendChild(el); }""",
            [heading, subtitle],
        )
        time.sleep(seconds)
        self.page.evaluate("() => { const el = document.getElementById('tut-title'); if (el) { el.style.opacity = 0; setTimeout(() => el.remove(), 600); } }")
        time.sleep(0.6)


def _srt_time(seconds):
    millis = int(round(seconds * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _subtitle_lines(text, width=26):
    """字幕每行最多約 26 個字，在標點處換行。"""
    lines, line = [], ""
    for char in text:
        line += char
        if len(line) >= width and char in "，。、；：！？）」":
            lines.append(line)
            line = ""
    if line:
        lines.append(line)
    merged = []
    for item in lines:
        if merged and len(merged[-1]) + len(item) <= width:
            merged[-1] += item
        else:
            merged.append(item)
    return "\n".join(merged[:3])


def save_cues(cues, path):
    import json
    Path(path).write_text(json.dumps([[c.start, c.end, c.text, str(c.audio)] for c in cues], ensure_ascii=False), encoding="utf-8")


def load_cues(path):
    import json
    return [Cue(start, end, text, Path(audio)) for start, end, text, audio in json.loads(Path(path).read_text(encoding="utf-8"))]


def build_video(raw_video, cues, out_path, work_dir):
    """把錄好的畫面、各段旁白與字幕合成 MP4。"""
    work = Path(work_dir)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    srt = work / "subtitles.srt"
    srt.write_text(
        "\n".join(
            f"{index}\n{_srt_time(cue.start)} --> {_srt_time(cue.end + 0.2)}\n{_subtitle_lines(cue.text)}\n"
            for index, cue in enumerate(cues, 1)
        ),
        encoding="utf-8",
    )
    fonts = work / "fonts"
    fonts.mkdir(exist_ok=True)
    if FONT_FILE.exists():
        shutil.copy(FONT_FILE, fonts / FONT_FILE.name)
    inputs = ["-i", str(Path(raw_video).resolve())]
    parts = []
    for index, cue in enumerate(cues, 1):
        inputs += ["-i", str(cue.audio.resolve())]
        delay = int(cue.start * 1000)
        parts.append(f"[{index}:a]adelay={delay}|{delay}[a{index}]")
    mix = "".join(f"[a{index}]" for index in range(1, len(cues) + 1))
    # 畫面維持錄影原尺寸置中，下方留深色字幕帶：字幕不會蓋到畫面上的按鈕與文字，
    # 也不用底框（BorderStyle=3 每行各畫一塊，兩行時會互相重疊）。
    style = ("FontName=Microsoft JhengHei,FontSize=14,Bold=1,PrimaryColour=&H00FFFFFF,"
             "BorderStyle=1,Outline=0,Shadow=0,MarginV=10")
    filters = ";".join(parts + [
        f"{mix}amix=inputs={len(cues)}:normalize=0:dropout_transition=0,apad[aout]",
        f"[0:v]pad=1920:1080:160:12:color=0x0e1428,subtitles=subtitles.srt:fontsdir=fonts:force_style='{style}'[vout]",
    ])
    # 以錄影長度為準（apad 會讓聲音無限延長，不能靠 -shortest 結束）。
    _frames, seconds = imageio_ffmpeg.count_frames_and_secs(str(Path(raw_video).resolve()))
    seconds = max(seconds, cues[-1].end + 1.0)
    command = [ffmpeg, "-y", *inputs, "-filter_complex", filters, "-map", "[vout]", "-map", "[aout]",
               "-t", f"{seconds:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(Path(out_path).resolve())]
    subprocess.run(command, check=True, cwd=work, capture_output=True)
    return out_path
