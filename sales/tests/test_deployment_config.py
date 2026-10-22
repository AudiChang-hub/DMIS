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


class BlueGreenDeploymentTests(SimpleTestCase):
    def read(self, *parts):
        return PROJECT_ROOT.joinpath(*parts).read_text(encoding="utf-8")

    def test_two_web_colors_share_base_config_without_host_ports(self):
        compose = self.read("docker-compose.django.prod.yml")
        for color in ("web-blue", "web-green"):
            block = compose.split(f"  {color}:\n", 1)[1].split("\n\n", 1)[0]
            self.assertIn("service: web", block)
            self.assertIn("<<: *web_color", block)
            self.assertIn("ports: !reset []", block)
        self.assertIn('DMIS_RUN_MIGRATIONS: "0"', compose)
        self.assertIn("stop_grace_period: 30s", compose)

    def test_production_web_is_management_container_for_existing_exec_commands(self):
        compose = self.read("docker-compose.django.prod.yml")
        web = compose.split("  web:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn('command: ["sleep", "infinity"]', web)
        self.assertIn("ports: !reset []", web)
        self.assertIn("disable: true", web)
        for unit in ("calendar-sync", "official-catalog-check", "price-list-distribution"):
            service = self.read("deployment", "systemd", f"dmis-next-{unit}.service")
            self.assertIn("exec -T web python manage.py", service)

    def test_proxy_owns_local_port_and_reads_active_color_from_mounted_directory(self):
        compose = self.read("docker-compose.django.prod.yml")
        proxy = compose.split("  tunnel-proxy:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn('"127.0.0.1:${DJANGO_PORT:-19999}:8069"', proxy)
        self.assertIn("./deployment/nginx:/etc/nginx/conf.d:ro", proxy)
        self.assertIn(":/etc/nginx/dmis-upstream:ro", proxy)
        self.assertNotIn("tunnel-proxy.conf:/etc/nginx", proxy)
        self.assertNotIn("depends_on", proxy)

        conf = self.read("deployment", "nginx", "tunnel-proxy.conf")
        self.assertIn("set $dmis_backend web-blue:8000;", conf)
        self.assertLess(
            conf.index("set $dmis_backend web-blue:8000;"),
            conf.index("include /etc/nginx/dmis-upstream/*.conf;"),
        )
        self.assertIn("proxy_set_header Upgrade $http_upgrade;", conf)
        self.assertIn("error_page 502 = @unavailable;", conf)
        # 登入節流靠來源位址：只送 Cloudflare 覆寫的 CF-Connecting-IP，不附加用戶端自帶的 XFF。
        self.assertIn("map $http_cf_connecting_ip $dmis_client_ip", conf)
        self.assertIn("proxy_set_header X-Forwarded-For $dmis_client_ip;", conf)
        self.assertNotIn("$proxy_add_x_forwarded_for", conf)

    def test_deploy_migrates_and_starts_new_color_before_switching(self):
        script = self.read("scripts", "deploy_web_bluegreen.sh")
        deploy = script.split("deploy() {", 1)[1].split("\nrollback() {", 1)[0]
        order = [
            '"${compose[@]}" build "$target"',
            "check_migration_compat",
            'migrate_with "$target"',
            'start_color "$target"',
            'switch_to "$target"',
            'sleep "$DRAIN_SECONDS"',
            '已停止並保留',
            "finish_support_services",
        ]
        positions = [deploy.index(step) for step in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("nginx -s reload", script)
        self.assertIn('docker start "$id"', script)
        self.assertIn('run -d --no-deps --use-aliases --name "$BRIDGE" tunnel-proxy', script)
        for forbidden in ('}" down', "prune", "rm -rf", "restart db", "restart redis"):
            self.assertNotIn(forbidden, script)

    def test_deploy_script_delegates_to_blue_green_and_keeps_safety_steps(self):
        script = self.read("scripts", "deploy_django.sh")
        self.assertIn("./scripts/deploy_web_bluegreen.sh deploy", script)
        self.assertIn("./scripts/deploy_web_bluegreen.sh rollback", script)
        self.assertNotIn("--force-recreate tunnel-proxy", script)
        self.assertLess(
            script.index("DMIS_BACKUP_SKIP_PRUNE=1 ./scripts/backup_django_data.sh"),
            script.index('git merge --ff-only "origin/$DEPLOY_BRANCH"'),
        )
        self.assertLess(
            script.index('python3 scripts/check_release.py --tag "v${release_version}"'),
            script.index("./scripts/deploy_web_bluegreen.sh deploy"),
        )
        self.assertIn('exec ./scripts/deploy_django.sh "$@"', script)

    def test_static_files_are_collected_at_build_not_on_start(self):
        start = self.read("scripts", "start_django.sh")
        self.assertNotIn("collectstatic", start)
        self.assertIn('if [ "${DMIS_RUN_MIGRATIONS:-1}" = "1" ]; then', start)
        dockerfile = self.read("Dockerfile.django")
        self.assertIn("python manage.py collectstatic --noinput", dockerfile)
        self.assertLess(dockerfile.index("USER dmis"), dockerfile.index("collectstatic"))
        base = self.read("docker-compose.django.yml")
        self.assertIn("start_interval: 2s", base)
