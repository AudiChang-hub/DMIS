from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from sales.models import SalesOrder, VehicleModel, VehicleColor
from sales.services.order_sorting import COLUMNS, parse_sort, sort_orders


class OrderSortingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser('sort-admin', password='test-only')
        model = VehicleModel.objects.create(brand='測試', name='排序機種', energy_type='gas')
        color = VehicleColor.objects.create(vehicle_model=model, name='白')
        cls.orders = []
        for name, day in [('BetaSort',date(2020,1,1)), ('AlphaSort',date(2020,1,1)), ('AlphaSort',date(2020,1,2)), ('GammaSort',None)]:
            order = SalesOrder.objects.create(owner_name=name, owner_phone='0912345678', owner_address='合成測試地址', owner_id_number='A123456789', vehicle_model=model, color=color, established_on=day)
            cls.orders.append(order)

    def test_multi_direction_nulls_and_stable_ties(self):
        a,b,c,d = self.orders
        self.assertEqual(list(sort_orders(SalesOrder.objects.all(), ['established_on','owner_name'])), [b,a,c,d])
        self.assertEqual(list(sort_orders(SalesOrder.objects.all(), ['-established_on','-owner_name'])), [c,a,b,d])
        self.assertEqual(list(sort_orders(SalesOrder.objects.filter(owner_name='AlphaSort'), ['owner_name'])), [c,b])

    def test_whitelist_and_all_columns(self):
        self.assertEqual(parse_sort('bad,--number,number,-number,-established_on'), ['number','-established_on'])
        for key, _ in COLUMNS:
            with self.subTest(key=key):
                self.assertEqual(sort_orders(SalesOrder.objects.all(), [key]).count(), 4)
                self.assertEqual(len(list(sort_orders(SalesOrder.objects.all(), ['-'+key]))), 4)

    def test_registration_date_null_position_and_secondary_sort(self):
        a, b, c, d = self.orders
        SalesOrder.objects.filter(pk=a.pk).update(registration_date=date(2020, 1, 1))
        SalesOrder.objects.filter(pk=c.pk).update(registration_date=date(2020, 1, 2))
        orders = SalesOrder.objects.all()
        self.assertEqual(list(sort_orders(orders, ['registration_date', 'owner_name'])), [a, c, b, d])
        self.assertEqual(list(sort_orders(orders, ['-registration_date', 'owner_name'])), [b, d, c, a])
        self.assertEqual(list(sort_orders(orders, ['-registration_date', '-owner_name'])), [d, b, c, a])
        self.assertEqual(list(sort_orders(orders, ['owner_name', '-registration_date'])), [b, c, a, d])

    def test_registration_date_pagination_keeps_unregistered_orders(self):
        self.client.force_login(self.user)
        pending = self.orders[-1]
        SalesOrder.objects.exclude(pk=pending.pk).update(registration_date=date(2020, 1, 1))
        template = self.orders[0]
        for index in range(23):
            SalesOrder.objects.create(
                owner_name=f'PageSort{index}', owner_phone=template.owner_phone,
                owner_address=template.owner_address, owner_id_number=template.owner_id_number,
                vehicle_model=template.vehicle_model, color=template.color,
                registration_date=date(2020, 1, 2),
            )
        for token, pending_page in [('registration_date', 2), ('-registration_date', 1)]:
            seen = []
            for page in (1, 2):
                response = self.client.get(reverse('order_list'), {'sort': token, 'per_page': 25, 'page': page})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['page_obj'].paginator.count, 27)
                rows = list(response.context['orders'])
                seen.extend(order.pk for order in rows)
                if page == pending_page:
                    self.assertEqual(rows[0 if token.startswith('-') else -1].pk, pending.pk)
            self.assertEqual(len(set(seen)), 27)
            self.assertEqual(set(seen), set(SalesOrder.objects.values_list('pk', flat=True)))

    def test_profit_sort_matches_model_with_fractional_values(self):
        for index, order in enumerate(self.orders):
            p = order.operations
            p.actual_disbursement = Decimal('100') + index
            p.legacy_card_fee_expense = Decimal('0.064')
            p.save()
        sorted_rows = list(sort_orders(SalesOrder.objects.select_related('operations'), ['-profit']))
        self.assertEqual([o.pk for o in sorted_rows], [o.pk for o in reversed(self.orders)])
        for order in sorted_rows:
            self.assertAlmostEqual(order._sort_profit, order.operations.net_profit, places=4)

    def test_view_preserves_sort_and_resets_page_links(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('order_list'), {'sort':'owner_name,-established_on','q':'AlphaSort','page':2,'per_page':25})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sort_value'], 'owner_name,-established_on')
        self.assertEqual(list(response.context['orders']), [self.orders[2], self.orders[1]])
        self.assertContains(response, 'name="sort" value="owner_name,-established_on"', count=2)
        self.assertContains(response, '登出系統')
        for column in response.context['sort_columns']:
            self.assertNotIn('page', parse_qs(urlsplit(column['url']).query))
            self.assertIn('q=', column['url'])
        links = {column['key']:parse_qs(urlsplit(column['url']).query)['sort'][0] for column in response.context['sort_columns']}
        self.assertEqual(links['owner_name'], '-owner_name,-established_on')
        self.assertEqual(links['established_on'], 'owner_name,established_on')
        self.assertEqual(links['profit'], 'owner_name,-established_on,profit')
        self.assertNotContains(response, 'data-sort-append')
        self.assertNotContains(response, 'Shift')
        self.assertContains(response, '<th scope="col"', count=10)
        self.assertContains(response, 'class="order-table-owner"', count=2)
        self.assertContains(response, f'<a class="order-owner-link" href="{reverse("order_detail", args=[self.orders[1].pk])}"><strong>AlphaSort</strong><small>{self.orders[1].number}</small></a>', html=True)

    def test_merged_header_retains_number_sort_and_empty_colspan(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('order_list'), {'sort':'-number'})
        self.assertContains(response, '<th scope="col" aria-sort="descending">', count=1)
        self.assertContains(response, 'class="order-number-sort"')
        self.assertEqual(response.context['sort_number_column']['rank'], 1)
        empty = self.client.get(reverse('order_list'), {'q':'no-matching-order-xyz'})
        self.assertContains(empty, 'colspan="10"')
