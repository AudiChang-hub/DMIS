"""
OrderProcessor 自動匯入 Scheduled Action 邏輯。

掃描 /mnt/order_backup/ 下各資料夾的 result.json，
建立草稿 dms.sale.order 並紀錄 dms.sync.log。
"""
import json
import logging
import os
import re
import time

from odoo import models

_logger = logging.getLogger(__name__)

BACKUP_DIR = '/mnt/order_backup'
MTIME_MIN_SECONDS = 60   # result.json 寫入後需靜置 60 秒才視為完整


class OrderSyncAction(models.AbstractModel):
    _name = 'dms.order.sync'
    _description = 'OrderProcessor 自動匯入'

    # ── 公開方法（Scheduled Action 呼叫）─────────────────
    def run_sync(self):
        """每次由 ir.cron 呼叫，靜默掃描並匯入。"""
        if not os.path.isdir(BACKUP_DIR):
            _logger.warning('[OrderSync] 備份目錄不存在：%s', BACKUP_DIR)
            return

        # 已處理資料夾（去重）
        existing = set(
            self.env['dms.sync.log'].search([]).mapped('folder_name')
        )

        for folder_name in sorted(os.listdir(BACKUP_DIR)):
            folder_path = os.path.join(BACKUP_DIR, folder_name)
            if not os.path.isdir(folder_path):
                continue
            if folder_name in existing:
                continue
            try:
                self._process_folder(folder_path, folder_name)
            except Exception:
                _logger.exception('[OrderSync] 資料夾處理失敗：%s', folder_name)

    # ── 歷史資料一次性標記──────────────────────────────
    def mark_all_existing_ignored(self):
        """將目前所有未處理的資料夾標記為 ignored，不建立訂單。"""
        if not os.path.isdir(BACKUP_DIR):
            return 0
        existing = set(
            self.env['dms.sync.log'].search([]).mapped('folder_name')
        )
        count = 0
        for folder_name in os.listdir(BACKUP_DIR):
            folder_path = os.path.join(BACKUP_DIR, folder_name)
            if not os.path.isdir(folder_path):
                continue
            if folder_name in existing:
                continue
            self.env['dms.sync.log'].create({
                'folder_name': folder_name,
                'state': 'ignored',
                'error_msg': '手動標記為歷史資料，不匯入',
            })
            count += 1
        return count

    # ── 內部：處理單一資料夾 ──────────────────────────
    def _process_folder(self, folder_path, folder_name):
        result_path = os.path.join(folder_path, 'result.json')
        if not os.path.isfile(result_path):
            self._write_log(folder_name, 'skip', error_msg='找不到 result.json')
            return

        # mtime 保護
        if (time.time() - os.path.getmtime(result_path)) < MTIME_MIN_SECONDS:
            # 尚未穩定，不寫 log → 下次再試
            return

        try:
            with open(result_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self._write_log(folder_name, 'fail', error_msg=f'JSON 解析失敗：{e}')
            return

        try:
            vals = self._build_order_vals(data, folder_name)
        except Exception as e:
            self._write_log(folder_name, 'fail', error_msg=f'欄位解析失敗：{e}')
            return

        try:
            order = self.env['dms.sale.order'].create(vals)
            self._write_log(folder_name, 'success', order_id=order.id)
        except Exception as e:
            self._write_log(folder_name, 'fail', error_msg=f'建立訂單失敗：{e}')

    # ── 內部：解析 result.json → 訂單欄位 ────────────
    def _build_order_vals(self, data, folder_name):
        text_map = data.get('text_map') or data.get('docx', {}).get('text_map', {}) or {}
        front = data.get('front') or {}
        back = data.get('back') or {}

        # ── 客戶身分 ──────────────────────────────────
        customer_name = (front.get('姓名') or '').strip() or '（未知）'
        id_number = (front.get('身分證字號') or '').strip()
        birthday_raw = (front.get('出生年月日') or '').strip()
        address_registered = (back.get('住址') or '').strip()

        # 生日：民國 → AD Date
        birthday_ad = None
        bd_match = re.match(r'(\d{2,3})\s*[./年]\s*(\d{1,2})\s*[./月]\s*(\d{1,2})', birthday_raw)
        if bd_match:
            try:
                roc_y, m, d = int(bd_match.group(1)), int(bd_match.group(2)), int(bd_match.group(3))
                birthday_ad = f'{roc_y + 1911}-{m:02d}-{d:02d}'
            except Exception:
                pass

        # ── 聯絡 ──────────────────────────────────────
        customer_phone = (
            text_map.get('車主電話') or text_map.get('聯絡電話') or ''
        ).strip()
        customer_email = (
            text_map.get('車主Email') or text_map.get('Email') or ''
        ).strip()

        # ── 車款 ──────────────────────────────────────
        model_raw = (text_map.get('車輛型號') or '').strip()
        source_product_name = model_raw
        product_id = False
        color_id = False

        if model_raw:
            sku_match = re.search(r'\(([A-Z0-9\-]+)\)', model_raw)
            if sku_match:
                sku = sku_match.group(1)
                product = self.env['dms.product'].search(
                    [('model', '=', sku)], limit=1)
                if not product:
                    product = self.env['dms.product'].search(
                        [('model', 'ilike', sku)], limit=1)
                if product:
                    product_id = product.id

        # ── 顏色 ──────────────────────────────────────
        color_raw = (text_map.get('車輛顏色') or '').strip()
        if color_raw:
            color_name = re.sub(r'\s*\(.*?\)', '', color_raw).strip()
            domain = [('name', 'ilike', color_name)]
            if product_id:
                domain.append(('product_id', '=', product_id))
            color = self.env['dms.product.color'].search(domain, limit=1)
            if color:
                color_id = color.id

        # ── 車行 ──────────────────────────────────────
        dealer_raw = (text_map.get('車行名稱') or '').strip()
        dealer_id = False
        sale_type = 'store'

        if dealer_raw:
            dealer = self.env['dms.dealer'].search(
                [('name', '=', dealer_raw)], limit=1)
            if not dealer:
                dealer = self.env['dms.dealer'].search(
                    [('name', 'ilike', dealer_raw)], limit=1)
            if dealer:
                dealer_id = dealer.id
                sale_type = 'dealer'
            else:
                # 找不到車行 → 嘗試帶入「馭盛」
                fallback = self.env['dms.dealer'].search(
                    [('name', 'ilike', '馭盛')], limit=1)
                if fallback:
                    dealer_id = fallback.id
                    sale_type = 'dealer'
                # 否則維持 store

        # ── 分期 ──────────────────────────────────────
        installment_raw = (text_map.get('是否有分期') or '').strip()
        payment_method = 'cash'
        finance_company = False
        if installment_raw and installment_raw not in ('無', '否', ''):
            payment_method = 'installment'
            # 嘗試從分期公司欄位取得
            fc_raw = (text_map.get('分期公司') or installment_raw).strip()
            if fc_raw and fc_raw not in ('有', '是'):
                finance_company = fc_raw

        # ── 汰舊 ──────────────────────────────────────
        trade_in_raw = (text_map.get('是否有汰舊') or '').strip()
        is_trade_in = bool(trade_in_raw and trade_in_raw not in ('否', '無', ''))

        # ── 配件/備註 ─────────────────────────────────
        extra_other = (text_map.get('配件') or '').strip()
        extra_note = (text_map.get('備註') or '').strip()

        vals = {
            'sale_origin': 'order_processor',
            'source_folder': folder_name,
            'source_product_name': source_product_name,
            'customer_name': customer_name,
            'id_number': id_number,
            'address_registered': address_registered,
            'customer_phone': customer_phone,
            'customer_email': customer_email,
            'product_id': product_id,
            'color_id': color_id,
            'dealer_id': dealer_id,
            'sale_type': sale_type,
            'payment_method': payment_method,
            'finance_company': finance_company,
            'is_trade_in': is_trade_in,
            'extra_other': extra_other or False,
            'extra_note': extra_note or False,
        }
        if birthday_ad:
            vals['birthday_ad'] = birthday_ad

        return vals

    # ── 內部：寫 log ──────────────────────────────────
    def _write_log(self, folder_name, state, order_id=None, error_msg=None):
        vals = {
            'folder_name': folder_name,
            'state': state,
        }
        if order_id:
            vals['order_id'] = order_id
        if error_msg:
            vals['error_msg'] = error_msg
        self.env['dms.sync.log'].create(vals)
