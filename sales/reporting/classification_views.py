from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import OperationalError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .classification import MATCHES, FALLBACK, apply_change, impact, preview_token, unclassified
from .models import ReportClassification
from .views import editor_required


class CategoryForm(forms.Form):
    id = forms.CharField(required=False, widget=forms.HiddenInput)
    name = forms.CharField(label='類別名稱', max_length=40)
    color = forms.RegexField(label='圖形顏色', regex=r'^#[0-9a-fA-F]{6}$', initial='#4257a5', widget=forms.TextInput(attrs={'type':'color'}))
    order = forms.IntegerField(label='清單順序', min_value=0, max_value=999, initial=10, help_text='圖表排序仍依設計器設定。')
    enabled = forms.BooleanField(label='啟用類別', required=False, initial=True)


class RuleForm(forms.Form):
    id = forms.CharField(required=False, widget=forms.HiddenInput)
    match = forms.ChoiceField(label='比對方式', choices=MATCHES.items())
    text = forms.CharField(label='型號／系列文字', max_length=120, strip=False,
                           help_text='大小寫敏感。精確型號優先；文字開頭會包含所有後續文字，不需輸入 * 或 regex。')
    category = forms.ChoiceField(label='歸入類別')
    enabled = forms.BooleanField(label='啟用規則', required=False, initial=True)

    def __init__(self, *args, categories, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].choices = [(c['id'], c['name'] + ('' if c['enabled'] else '（已停用）')) for c in categories]


@editor_required
@require_http_methods(['GET','POST'])
def manage(request):
    state = get_object_or_404(ReportClassification, pk=1)
    categories = sorted(state.draft['categories'], key=lambda c:(c['order'], c['id']))
    edit_category = next((c for c in categories if c['id'] == request.GET.get('category')), None)
    edit_rule = next((r for r in state.draft['rules'] if r['id'] == request.GET.get('rule')), None)
    category_form = CategoryForm(initial=edit_category, prefix='category')
    rule_form = RuleForm(initial=edit_rule, categories=categories, prefix='rule')
    error = ''; preview = None; token = ''; status = 200
    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            version = int(request.POST.get('version', ''))
            if version != state.version:
                raise ValidationError('分類版本已變更，請重新整理後再操作。')
            data = {}
            if action in ('category','rule'):
                if action == 'category':
                    category_form = CategoryForm(request.POST, prefix='category'); form = category_form
                else:
                    rule_form = RuleForm(request.POST, categories=categories, prefix='rule'); form = rule_form
                if not form.is_valid():
                    raise ValidationError('請修正欄位內容，尚未儲存。')
                data = form.cleaned_data
            elif action in ('delete_category','delete_rule'):
                data = {'id':request.POST.get('id','')}
            elif action == 'batch':
                data = {'models':request.POST.getlist('models'), 'category':request.POST.get('category','')}
            elif action == 'restore':
                data = {'revision':int(request.POST.get('revision',''))}
            elif action == 'publish':
                data = {'token':request.POST.get('token','')}
                if request.POST.get('confirm') != 'yes':
                    raise ValidationError('請確認此變更會重算歷史報表分類。')
            elif action == 'preview':
                preview = impact(state.published, state.draft)
                token = preview_token(state, request.user, preview)
            else:
                raise ValidationError('操作不正確。')
            if action != 'preview':
                apply_change(version, action, data, request.user)
                messages.success(request, '分類已發布，正式報表改用新版本。' if action == 'publish' else '草稿已更新；請試算後發布，正式報表尚未變更。')
                return redirect('report_classification')
        except (ValidationError, ValueError) as exc:
            error = '；'.join(exc.messages) if isinstance(exc, ValidationError) else '版本參數不正確。'
            status = 400
        except OperationalError:
            error = '資料庫忙碌或另一個視窗正在更新，請重新整理後重試。'
            status = 409
    counts = {c['id']:sum(r['category'] == c['id'] for r in state.draft['rules']) for c in categories}
    category_rows = [dict(c, rule_count=counts[c['id']]) for c in categories]
    names = {c['id']:c['name'] for c in categories}
    rule_search = request.GET.get('rule_search','')[:120].strip()
    rules = [dict(r, category_name=names[r['category']], match_name=MATCHES[r['match']]) for r in state.draft['rules']
             if not rule_search or rule_search.casefold() in r['text'].casefold() or rule_search in names[r['category']]]
    search = request.GET.get('q','')[:120].strip()
    page = Paginator(unclassified(state.draft, search), 50).get_page(request.GET.get('page'))
    labels = {'initial':'初始版本','category':'編輯類別','rule':'編輯規則','delete_category':'刪除未使用類別',
              'delete_rule':'刪除規則','batch':'批次指定型號','restore':'還原為草稿','publish':'發布分類'}
    history = list(state.revisions.all()[:30])
    for revision in history:
        revision.action_label = labels.get(revision.action, revision.action)
    return render(request, 'sales/reporting/classification.html', {
        'state':state, 'category_form':category_form, 'rule_form':rule_form,
        'categories':category_rows, 'rules':rules, 'error':error, 'preview':preview, 'publish_token':token,
        'page':page, 'search':search, 'rule_search':rule_search, 'fallback':FALLBACK,
        'has_changes':state.draft != state.published,
        'published_history':state.revisions.filter(action__in=['initial','publish'])[:30],
        'history':history,
    }, status=status)
