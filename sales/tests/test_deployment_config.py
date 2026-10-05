from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class CloudflareTunnelDeploymentTests(SimpleTestCase):
    def test_production_connector_uses_http2_and_token_file(self):
        compose = (PROJECT_ROOT / "docker-compose.django.prod.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("cloudflared:", compose)
        self.assertIn("- http2", compose)
        self.assertIn("- --token-file", compose)
        self.assertIn(
            "./secrets/cloudflare-tunnel.token:/run/secrets/cloudflare-tunnel.token:ro",
            compose,
        )
        self.assertNotIn("CLOUDFLARE_TUNNEL_TOKEN", compose)

    def test_deploy_script_requires_and_verifies_connector(self):
        script = (PROJECT_ROOT / "scripts" / "deploy_django.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("TUNNEL_TOKEN_FILE=", script)
        self.assertIn("up -d --no-deps cloudflared", script)
        self.assertIn("protocol=http2", script)

    def test_deploy_backup_never_prunes_root_owned_backups(self):
        deploy = (PROJECT_ROOT / "scripts" / "deploy_django.sh").read_text(encoding="utf-8")
        backup = (PROJECT_ROOT / "scripts" / "backup_django_data.sh").read_text(encoding="utf-8")

        self.assertIn("DMIS_BACKUP_SKIP_PRUNE=1 ./scripts/backup_django_data.sh", deploy)
        guard = backup.index('if [[ "$SKIP_PRUNE" == "1" ]]; then')
        prune_lines = [line for line in backup.splitlines() if line.strip().startswith("find ") and line.endswith("-delete")]
        self.assertEqual(len(prune_lines), 5)
        for line in prune_lines:
            self.assertGreater(backup.index(line), guard)
            self.assertTrue(line.startswith("    find "))
