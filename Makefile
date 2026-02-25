up:
	docker compose up -d

logs:
	docker compose logs -f odoo

ps:
	docker compose ps

smoke:
	chmod +x scripts/smoke_odoo.sh || true
	./scripts/smoke_odoo.sh

down:
	docker compose down -v
