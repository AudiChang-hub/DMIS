#!/usr/bin/env python3
"""在無對外連線的暫存容器還原正式每日備份；不寫入正式資料庫。"""
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone


def run(args, **kwargs):
    return subprocess.run(args, check=True, timeout=600, **kwargs)


def file_hashes(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("備份不可包含符號連結")
        if path.is_file():
            with path.open("rb") as stream:
                result[str(path.relative_to(root))] = hashlib.file_digest(stream, "sha256").hexdigest()
    return result


def dump_counts(path):
    """以 dump 同一快照的 COPY 行數比對，不拿持續變動的正式庫作基準。"""
    counts, table = {}, None
    with gzip.open(path, "rt", encoding="utf-8") as source:
        for line in source:
            if table is not None:
                if line.rstrip("\n") == "\\.":
                    table = None
                else:
                    counts[table] += 1
            else:
                match = re.match(r'^COPY public\.([a-z_][a-z_0-9]*) \(', line)
                if match:
                    table = match[1]
                    counts[table] = 0
    if not counts:
        raise ValueError("備份沒有可核對的資料表")
    return counts


def main():
    os.umask(0o077)
    project = Path(os.environ.get("DMIS_NEXT_PROJECT_DIR", "/home/audi/project/DMIS-next"))
    data = Path(os.environ.get("DMIS_DATA_ROOT", "/srv/dmis-data/dmis-next"))
    status_dir = data / "restore-drills"
    status_dir.mkdir(exist_ok=True)
    lock = (status_dir / ".lock").open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 0
    started = time.monotonic()
    result = {"status": "running", "checked_at": datetime.now(timezone.utc).isoformat()}

    def publish():
        target = status_dir / "latest.json"
        temporary = status_dir / "latest.json.tmp"
        temporary.write_text(json.dumps(result), encoding="utf-8")
        temporary.replace(target)

    def interrupted(signum, frame):
        raise RuntimeError("演練中斷")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    publish()
    token = "dmis-drill-" + uuid.uuid4().hex[:12]
    network, database, app = token, token + "-db", token + "-app"
    work = Path(tempfile.mkdtemp(prefix="dmis-drill-", dir=status_dir))
    stage = "backup"
    try:
        run(["bash", str(project / "scripts/backup_django_data.sh")], stdout=subprocess.DEVNULL)
        backup_root = data / "backups"
        # 防止每日備份同時更新鏡像；只在取快照期間持鎖。
        with (data / ".backup.lock").open("r") as backup_lock:
            fcntl.flock(backup_lock, fcntl.LOCK_EX)
            source = max((backup_root / "postgres/daily").glob("*.sql.gz"), key=lambda p: p.stat().st_mtime)
            if time.time() - source.stat().st_mtime > 86400:
                raise ValueError("備份超過一天")
            dump = work / "database.sql.gz"
            shutil.copyfile(source, dump)
            result["backup_at"] = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat()
            expected_files = file_hashes(backup_root / "media-current")
            archive = work / "media.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                tar.add(backup_root / "media-current", arcname="media")
        stage = "media"
        with tarfile.open(archive) as tar:
            tar.extractall(work / "restored", filter="data")
        if file_hashes(work / "restored/media") != expected_files:
            raise ValueError("附件 SHA-256 不一致")
        expected = dump_counts(dump)
        stage = "database"
        run(["docker", "network", "create", "--internal", network], stdout=subprocess.DEVNULL)
        # 信任驗證只存在於隔離、無發布埠且執行後銷毀的演練資料庫。
        run(["docker", "run", "-d", "--name", database, "--network", network,
             "--memory", "768m", "--cpus", "0.5", "--pids-limit", "128",
             "--tmpfs", "/var/lib/postgresql/data:rw,size=1g",
             "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", "POSTGRES_DB=drill",
             "postgres:16"], stdout=subprocess.DEVNULL)
        for _ in range(60):
            ready = subprocess.run(["docker", "exec", database, "pg_isready", "-U", "postgres"],
                                   timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("演練資料庫啟動逾時")
        with gzip.open(dump, "rb") as compressed, (work / "restore.sql").open("wb") as plain:
            shutil.copyfileobj(compressed, plain)
        with (work / "restore.sql").open("rb") as plain:
            run(["docker", "exec", "-i", database, "psql", "-X", "-v", "ON_ERROR_STOP=1",
                 "-U", "postgres", "-d", "drill"], stdin=plain, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
        queries = " UNION ALL ".join(
            f"SELECT '{table}', count(*) FROM public.\"{table}\"" for table in expected
        ) + ";"
        rows = run(["docker", "exec", database, "psql", "-XAt", "-U", "postgres", "-d", "drill",
                    "-c", queries], capture_output=True, text=True).stdout
        actual = {name: int(count) for name, count in (line.split("|") for line in rows.splitlines())}
        if actual != expected:
            raise ValueError("還原資料筆數與備份不一致")
        stage = "application"
        image = run(["docker", "inspect", "dmis-next-web-1", "--format", "{{.Image}}"],
                    capture_output=True, text=True).stdout.strip()
        env = ["POSTGRES_HOST=" + database, "POSTGRES_DB=drill", "DJANGO_DB_USER=postgres",
               "DJANGO_DB_PASSWORD=drill-only", "DJANGO_ALLOWED_HOSTS=testserver", "DJANGO_DEBUG=1"]
        args = ["docker", "run", "--rm", "--name", app, "--network", network,
                "--memory", "512m", "--cpus", "0.5", "--read-only", "--tmpfs", "/tmp:rw,size=64m"]
        for value in env:
            args.extend(["-e", value])
        smoke = ("from django.core.management import call_command; "
                 "from django.test import Client; from sales.models import SalesOrder; "
                 "call_command('migrate', check=True, verbosity=0); "
                 "assert Client().get('/health/').status_code == 200; "
                 "SalesOrder.objects.count()")
        run(args + [image, "python", "manage.py", "shell", "-c", smoke],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result.update(status="success", tables=len(expected), rows=sum(expected.values()),
                      media_files=len(expected_files))
    except Exception:
        result.update(status="failed", failed_stage=stage)
    finally:
        # 只清除此輪 UUID 名稱，絕不使用 compose down 或全域 prune。
        cleanup_ok = True
        for name in (app, database):
            try:
                exists = subprocess.run(["docker", "inspect", name], timeout=20, capture_output=True)
                if exists.returncode == 0:
                    run(["docker", "rm", "-f", "-v", name], stdout=subprocess.DEVNULL)
            except Exception:
                cleanup_ok = False
        try:
            exists = subprocess.run(["docker", "network", "inspect", network], timeout=20, capture_output=True)
            if exists.returncode == 0:
                run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL)
            if work.parent.resolve() != status_dir.resolve() or not work.name.startswith("dmis-drill-"):
                raise ValueError("清理範圍不正確")
            shutil.rmtree(work)
        except Exception:
            cleanup_ok = False
        if not cleanup_ok:
            result.update(status="failed", failed_stage="cleanup")
        result.update(duration_seconds=round(time.monotonic() - started),
                      checked_at=datetime.now(timezone.utc).isoformat())
        publish()
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
