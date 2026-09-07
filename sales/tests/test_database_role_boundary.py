import os
import subprocess
import sys

from django.test import SimpleTestCase


class DatabaseRoleBoundaryTests(SimpleTestCase):
    def _production_env(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_DEBUG": "0",
                "DJANGO_ENV": "production",
                "DJANGO_SECRET_KEY": "test-only-long-secret-key-for-settings-check",
                "DJANGO_ALLOWED_HOSTS": "dmis.example.test",
                "POSTGRES_HOST": "database.invalid",
                "POSTGRES_DB": "dmis_test",
                "POSTGRES_USER": "cluster_admin",
                "POSTGRES_PASSWORD": "admin-password-not-used-by-runtime",
                "DJANGO_DB_USER": "dmis_app",
                "DJANGO_DB_PASSWORD": "runtime-password-for-test-only",
            }
        )
        return env

    def test_runtime_prefers_non_superuser_application_credentials(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from config.settings import DATABASES; "
                    "db=DATABASES['default']; "
                    "print(db['USER']); "
                    "print(db['PASSWORD']=='runtime-password-for-test-only')"
                ),
            ],
            cwd=os.getcwd(),
            env=self._production_env(),
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )

        self.assertEqual(
            result.stdout.splitlines(),
            ["dmis_app", "True"],
        )

    def test_production_rejects_example_application_password(self):
        env = self._production_env()
        env["DJANGO_DB_PASSWORD"] = "請替換為應用程式資料庫強密碼"

        result = subprocess.run(
            [sys.executable, "-c", "import config.settings"],
            cwd=os.getcwd(),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("正式環境必須設定非預設資料庫密碼", result.stderr)

    def test_production_requires_separate_application_credentials(self):
        for missing_key in ("DJANGO_DB_USER", "DJANGO_DB_PASSWORD"):
            with self.subTest(missing_key=missing_key):
                env = self._production_env()
                env.pop(missing_key)
                result = subprocess.run(
                    [sys.executable, "-c", "import config.settings"],
                    cwd=os.getcwd(),
                    env=env,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("必須設定獨立的 DJANGO_DB_USER", result.stderr)

    def test_production_rejects_application_role_equal_to_admin_role(self):
        env = self._production_env()
        env["DJANGO_DB_USER"] = env["POSTGRES_USER"]

        result = subprocess.run(
            [sys.executable, "-c", "import config.settings"],
            cwd=os.getcwd(),
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("不可使用 PostgreSQL 管理角色", result.stderr)
