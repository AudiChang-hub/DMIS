"""旁白：Windows 內建中文語音（Microsoft Hanhan，zh-TW），離線產生 WAV。"""
import subprocess
import tempfile
import wave
from pathlib import Path

VOICE = "Microsoft Hanhan Desktop"

_SCRIPT = r"""
param([string]$TextFile, [string]$OutFile, [int]$Rate)
Add-Type -AssemblyName System.Speech
$text = Get-Content -Raw -Encoding UTF8 $TextFile
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice('{voice}')
$s.Rate = $Rate
$s.SetOutputToWaveFile($OutFile)
$s.Speak($text)
$s.Dispose()
"""


def synthesize(text, out_path, rate=1):
    """把一段旁白轉成 WAV；回傳秒數。rate：-10（慢）～10（快）。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        text_file = Path(folder) / "text.txt"
        script_file = Path(folder) / "speak.ps1"
        text_file.write_text(text, encoding="utf-8")
        script_file.write_text(_SCRIPT.replace("{voice}", VOICE), encoding="utf-8-sig")
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_file),
             str(text_file), str(out_path), str(rate)],
            check=True, capture_output=True,
        )
    return duration(out_path)


def duration(path):
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())
