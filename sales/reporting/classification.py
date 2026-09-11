"""報表車種分類：嚴格快照驗證、唯讀 SQL 分類及版本化寫入。"""
import copy
import hashlib
import json
import re
import uuid
from contextvars import ContextVar

from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, CharField, Count, F, Min, Value, When
from django.utils import timezone

from .models import ReportClassification, ReportClassificationRevision

MATCHES = {'exact':'精確型號', 'prefix':'文字開頭', 'numeric':'系列＋數字', 'series':'系列＋數字／-代碼'}
FALLBACK = 'other'
_request_snapshot = ContextVar('report_classification_snapshot', default=None)


def initial_snapshot():
    from .source_compatibility import MOTOR_TYPE_GROUPS
    colors = ['#737373', '#7ac36a', '#faa75a', '#f15a60', '#5a9bd4', '#a86e11']
    categories, rules = [], []
    for index, (models, label) in enumerate(MOTOR_TYPE_GROUPS):
        category = f'category-{index}'
        categories.append({'id':category, 'name':label, 'color':colors[index], 'order':index, 'enabled':True})
        for text in models:
            rules.append({'id':f'rule-{len(rules)}', 'match':'exact', 'text':text, 'category':category, 'enabled':True})
    categories.append({'id':FALLBACK, 'name':'其他', 'color':colors[5], 'order':99, 'enabled':True})
    for text in ('UQ', 'UC', 'UG', 'UT', 'GSX', 'DS'):
        rules.append({'id':f'rule-{len(rules)}', 'match':'numeric' if text in ('UQ','UC','UG','UT') else 'series', 'text':text,
                      'category':'category-3' if text in ('UQ','UC','UG','UT') else 'category-4', 'enabled':True})
    return {'categories':categories, 'rules':rules}


def validate_snapshot(snapshot):
    def fail(message):
        raise ValidationError(message)
    if not isinstance(snapshot, dict) or set(snapshot) != {'categories','rules'}:
        fail('分類設定格式不正確。')
    categories, rules = snapshot['categories'], snapshot['rules']
    if not isinstance(categories, list) or not 1 <= len(categories) <= 50 or not isinstance(rules, list) or len(rules) > 500:
        fail('最多 50 個類別與 500 條規則。')
    ids, names, rule_ids, expressions = set(), set(), set(), set()
    for c in categories:
        if not isinstance(c, dict) or set(c) != {'id','name','color','order','enabled'}:
            fail('類別欄位不正確。')
        if not isinstance(c['id'], str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', c['id']) or c['id'] in ids:
            fail('類別識別碼重複或不正確。')
        if not isinstance(c['name'], str) or not c['name'].strip() or len(c['name']) > 40 or c['name'] != c['name'].strip() or c['name'] in names:
            fail('類別名稱不可空白、重複或超過 40 字。')
        if not isinstance(c['color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', c['color']) or type(c['order']) is not int or not 0 <= c['order'] <= 999 or type(c['enabled']) is not bool:
            fail('類別顏色、順序或啟用狀態不正確。')
        ids.add(c['id']); names.add(c['name'])
    fallback = next((c for c in categories if c['id'] == FALLBACK), None)
    if not fallback or not fallback['enabled'] or fallback['name'] != '其他':
        fail('「其他」是保留類別，不能移除、改名或停用。')
    for r in rules:
        if not isinstance(r, dict) or set(r) != {'id','match','text','category','enabled'}:
            fail('規則欄位不正確。')
        if not isinstance(r['id'], str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', r['id']) or r['id'] in rule_ids:
            fail('規則識別碼重複或不正確。')
        if not isinstance(r['match'], str) or r['match'] not in MATCHES or not isinstance(r['text'], str) or not r['text'].strip() or len(r['text']) > 120 or any(ord(c) < 32 for c in r['text']):
            fail('型號規則不可空白、含控制字元或超過 120 字。')
        if not isinstance(r['category'], str) or r['category'] not in ids or type(r['enabled']) is not bool:
            fail('規則對應的類別或啟用狀態不正確。')
        identity = (r['match'], r['text'])
        if identity in expressions:
            fail(f'重複規則：{r["text"]}。請編輯既有規則。')
        expressions.add(identity); rule_ids.add(r['id'])
    active_ids = {c['id'] for c in categories if c['enabled']}
    active = [r for r in rules if r['enabled'] and r['category'] in active_ids and r['match'] != 'exact']
    for index, a in enumerate(active):
        for b in active[index+1:]:
            if a['category'] != b['category'] and (a['text'].startswith(b['text']) or b['text'].startswith(a['text'])):
                fail(f'系列規則「{a["text"]}」與「{b["text"]}」重疊且類別不同；請改用精確型號例外或停用其中一條。')
    return snapshot


def published_snapshot():
    cache = _request_snapshot.get()
    if cache is not None and 'value' in cache:
        return cache['value']
    row = ReportClassification.objects.filter(pk=1).values('published','published_version').first()
    result = (row['published'], row['published_version']) if row else (initial_snapshot(), 1)
    if cache is not None:
        cache['value'] = result
    return result


class ClassificationSnapshotMiddleware:
    """同一次請求的圖表、下鑽連結與 CSV 固定使用同一發布版。"""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request_snapshot.set({})
        try:
            return self.get_response(request)
        finally:
            _request_snapshot.reset(token)


def classification_expression(snapshot=None, *, identifiers=False):
    snapshot = snapshot if snapshot is not None else published_snapshot()[0]
    categories = {c['id']:c for c in snapshot['categories']}
    rules = sorted(snapshot['rules'], key=lambda r:(r['match'] != 'exact', -len(r['text']), r['id']))
    cases = []
    for r in rules:
        category = categories[r['category']]
        if not r['enabled'] or not category['enabled']:
            continue
        if r['match'] == 'exact':
            lookup = {'report_source_model':r['text']}
        else:
            suffix = {'prefix':'', 'numeric':'[0-9]', 'series':'([0-9]|-[A-Z0-9])'}[r['match']]
            lookup = {'report_source_model__regex':'^' + re.escape(r['text']) + suffix}
        cases.append(When(**lookup, then=Value(category['id'] if identifiers else category['name'])))
    return Case(*cases, default=Value(FALLBACK if identifiers else categories[FALLBACK]['name']), output_field=CharField())


def inventory():
    from sales.models import SalesOrder
    from .source_compatibility import source_model_query
    return source_model_query(SalesOrder.objects.exclude(status__in=['draft','cancel_refund_pending','cancelled']))


def unclassified(snapshot, search=''):
    query = inventory().annotate(classification_id=classification_expression(snapshot, identifiers=True)).filter(classification_id=FALLBACK)
    if search:
        query = query.filter(report_source_model__icontains=search)
    return query.values('report_source_model').annotate(count=Count('pk'), master=Min('vehicle_model__name')).order_by('-count','report_source_model')


def impact(before, after):
    validate_snapshot(after)
    query = inventory().annotate(before=classification_expression(before), after=classification_expression(after))
    rows = query.exclude(before=F('after')).values('report_source_model','before','after').annotate(count=Count('pk')).order_by('report_source_model','before','after')
    # 每型號彙總；不讀取客戶資料。摘要涵蓋全部型號，畫面最多列 200 列。
    digest = hashlib.sha256(); result = []; total = 0; groups = 0
    for row in rows.iterator(chunk_size=500):
        digest.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode())
        total += row['count']; groups += 1
        if len(result) < 200:
            result.append(row)
    return {'rows':result, 'total':total, 'groups':groups, 'digest':digest.hexdigest()}


def preview_token(state, user, result):
    return signing.dumps({'version':state.version, 'user':user.pk, 'impact':result['digest'],
                          'draft':hashlib.sha256(json.dumps(state.draft, sort_keys=True).encode()).hexdigest()}, salt='report-classification')


def apply_change(version, action, data, user):
    """所有變更限於分類設定；版本檢查避免多視窗覆寫。"""
    with transaction.atomic():
        state = ReportClassification.objects.select_for_update().get(pk=1)
        if state.version != version:
            raise ValidationError('分類版本已變更，請重新整理後再操作。')
        draft = copy.deepcopy(state.draft)
        key = data.get('id', '')
        if action in ('category','rule'):
            collection = draft['categories' if action == 'category' else 'rules']
            existing = next((item for item in collection if item['id'] == key), None)
            if key and not existing:
                raise ValidationError('找不到要編輯的項目。')
            item = {k:v for k,v in data.items() if k != 'id'}
            item['id'] = key or uuid.uuid4().hex
            if existing:
                collection[collection.index(existing)] = item
            else:
                collection.append(item)
        elif action in ('delete_category','delete_rule'):
            collection = draft['categories' if action == 'delete_category' else 'rules']
            if not any(item['id'] == key for item in collection):
                raise ValidationError('項目不存在。')
            if action == 'delete_category':
                used = any(r['category'] == key for r in draft['rules'])
                histories = state.revisions.filter(action__in=['publish','initial']).values_list('snapshot', flat=True)
                used = used or any(any(r['category'] == key for r in s['rules']) for s in histories)
                if key == FALLBACK or used:
                    raise ValidationError('此類別已被規則使用或曾發布，不能刪除；請停用或移轉規則。')
            collection[:] = [item for item in collection if item['id'] != key]
        elif action == 'batch':
            models = list(dict.fromkeys(data['models']))
            if not 1 <= len(models) <= 100:
                raise ValidationError('請選取 1–100 個非空白型號。')
            for text in models:
                rule = next((r for r in draft['rules'] if r['match'] == 'exact' and r['text'] == text), None)
                if rule:
                    rule.update(category=data['category'], enabled=True)
                else:
                    draft['rules'].append({'id':uuid.uuid4().hex, 'match':'exact', 'text':text, 'category':data['category'], 'enabled':True})
        elif action == 'restore':
            revision = state.revisions.filter(version=data['revision'], action__in=['publish','initial']).first()
            if not revision:
                raise ValidationError('找不到可還原的發布版本。')
            draft = copy.deepcopy(revision.snapshot)
        elif action != 'publish':
            raise ValidationError('不支援的操作。')
        validate_snapshot(draft)
        changes = {'draft':draft, 'version':version+1, 'updated_at':timezone.now()}
        if action == 'publish':
            if draft == state.published:
                raise ValidationError('草稿與發布版相同，不需要重新發布。')
            try:
                signed = signing.loads(data['token'], salt='report-classification', max_age=1800)
            except signing.BadSignature as error:
                raise ValidationError('試算已過期或不正確，請重新試算。') from error
            result = impact(state.published, draft)
            expected = signing.loads(preview_token(state, user, result), salt='report-classification')
            if signed != expected:
                raise ValidationError('草稿或資料已變更，請重新試算後發布。')
            changes.update(published=draft, published_version=version+1)
        if ReportClassification.objects.filter(pk=1, version=version).update(**changes) != 1:
            raise ValidationError('另一個視窗已更新，請重新整理。')
        ReportClassificationRevision.objects.create(classification=state, version=version+1, action=action, snapshot=draft,
                                                     actor=user, actor_name=user.get_username())
        return version+1
