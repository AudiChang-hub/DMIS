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
