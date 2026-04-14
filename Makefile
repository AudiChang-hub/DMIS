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

# 清除 Odoo web assets 快取（CSS/JS 修改後必須執行才會生效）
clear-assets:
	docker compose exec -T db psql -U odoo dmis_dev -c \
	  "DELETE FROM ir_attachment WHERE name LIKE '%.assets%' OR name LIKE '%web.assets_backend%' OR (url LIKE '/web/content%' AND (name LIKE '%.js' OR name LIKE '%.css' OR name LIKE '%.min%'));"
	@echo "Assets cache cleared."

# 清快取 + 重啟（靜態檔案修改後的標準流程）
reload: clear-assets
	docker compose restart odoo
	@echo "Odoo restarted. Waiting 35s..."
	sleep 35
	./scripts/smoke_odoo.sh
