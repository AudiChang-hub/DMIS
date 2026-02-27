up:
	docker compose up -d

logs:
	docker compose logs -f odoo

ps:
	docker compose ps

smoke:
	chmod +x scripts/smoke_odoo.sh || true
	./scripts/smoke_odoo.sh

validate-views:
	python scripts/validate_views_fields.py

ci-checks: validate-views
	@echo "CI checks passed"

down:
	docker compose down -v
