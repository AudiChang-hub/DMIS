"""訂單列表唯讀排序；欄位白名單與既有財務公式。"""
from django.db.models import Case, CharField, DecimalField, F, Func, Value, When
from django.db.models.functions import Coalesce, NullIf

from sales.models import OrderOperationsProfile, SalesOrder


COLUMNS = (
    ('owner_name', '車主'), ('number', '訂單編號'), ('machine', '機種'),
    ('color', '顏色'), ('registration_date', '領牌日期'),
    ('established_on', '訂單成立日期'), ('plate', '車號'), ('profit', '淨利'),
    ('source', '車行／平台'), ('status', '狀態'), ('note', '備註'),
)
FIELDS = dict(owner_name='owner_name', number='number', machine='_sort_machine',
              color='color__name', registration_date='registration_date',
              established_on='established_on', plate='final_plate_number',
              profit='_sort_profit', source='_sort_source', status='_sort_status', note='note')


def parse_sort(raw):
    result, seen = [], set()
    for token in raw[:500].split(','):
        key = token.lstrip('-')
        if token not in (key, '-' + key) or key not in FIELDS or key in seen:
            continue
        seen.add(key)
        result.append(token)
    return result


def sort_orders(orders, tokens):
    if not tokens:
        return orders.order_by('-order_date', '-created_at', '-pk')
    keys = {token.lstrip('-') for token in tokens}
    annotations = {}
    if 'machine' in keys:
        annotations['_sort_machine'] = Coalesce(NullIf('vehicle_model__family__name', Value('')), 'vehicle_model__name')
    if 'source' in keys:
        annotations['_sort_source'] = Coalesce(NullIf('source__name', Value('')), Case(
            *[When(source_type=value, then=Value(label)) for value, label in SalesOrder.SourceType.choices], output_field=CharField()))
    if 'status' in keys:
        annotations['_sort_status'] = Case(*[When(status=value, then=Value(label)) for value, label in SalesOrder.Status.choices], output_field=CharField())
    if 'profit' in keys:
        money = DecimalField(max_digits=20, decimal_places=4)
        def amount(field):
            return Coalesce(F('operations__' + field), Value(0), output_field=money)
        # 平坦加總避免舊版 SQLite 對數十層括號的 parser stack 限制。
        profit = Func(amount('actual_disbursement'), -amount('vehicle_cost'),
                      *[-amount(f) for f in OrderOperationsProfile.EXPENSE_FIELDS],
                      *[amount(f) for f in (*OrderOperationsProfile.INCOME_FIELDS, *OrderOperationsProfile.INCENTIVE_FIELDS)],
                      template='(%(expressions)s)', arg_joiner=' + ', output_field=money)
        annotations['_sort_profit'] = Case(When(operations__isnull=False, then=profit), output_field=money)
    orders = orders.annotate(**annotations)
    return orders.order_by(*[F(FIELDS[t.lstrip('-')]).desc(nulls_last=True) if t.startswith('-') else F(FIELDS[t]).asc(nulls_last=True) for t in tokens], '-pk')


def sort_context(params, tokens):
    columns = []
    active = {token.lstrip('-'): (i + 1, token.startswith('-')) for i, token in enumerate(tokens)}
    for key, label in COLUMNS:
        rank, descending = active.get(key, (None, False))
        query = params.copy()
        query.pop('page', None)
        next_token = key if descending else '-' + key if rank else key
        next_tokens = [next_token if token.lstrip('-') == key else token for token in tokens] if rank else [*tokens, key]
        query['sort'] = ','.join(next_tokens)
        columns.append({'key':key, 'label':label, 'rank':rank, 'direction':'▼' if descending else '▲',
                        'aria_sort':('descending' if descending else 'ascending') if rank == 1 else 'none', 'url':'?' + query.urlencode()})
    return {'sort_value':','.join(tokens), 'sort_columns':columns,
            'sort_number_column':next(column for column in columns if column['key'] == 'number'),
            'sort_active':sorted((column for column in columns if column['rank']), key=lambda column:column['rank'])}
