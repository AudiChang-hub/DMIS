from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .access.services import AccessPolicy, policy_for
from .models import UserAppearancePreference
from .services.home_favorites import favorite_context


def validate_selection(post, context):
    selected = post.getlist("favorite")
    allowed = {item["key"] for item in context["favorite_options"]}
    if len(selected) != len(set(selected)) or any(key not in allowed for key in selected):
        raise ValidationError("選取內容包含重複、已停用或沒有權限的功能，請重新確認。")
    order = post.get("order", "")
    if order:
        ordered = order.split(",")
        if len(ordered) != len(selected) or set(ordered) != set(selected):
            raise ValidationError("排序與勾選內容不一致，請重新整理後再試。")
        return ordered
    return [key for key in context["favorite_keys"] if key in selected] + [key for key in selected if key not in context["favorite_keys"]]


@login_required
@require_http_methods(["GET", "POST"])
def home_favorites(request):
    preference = UserAppearancePreference.objects.filter(user=request.user).first()
    context = favorite_context(request.user, preference, policy=policy_for(request))
    status = 200
    if request.method == "POST":
        try:
            expected_version = int(request.POST.get("expected_version", ""))
            with transaction.atomic():
                user = get_user_model().objects.select_for_update().get(pk=request.user.pk)
                preference, _ = UserAppearancePreference.objects.select_for_update().get_or_create(user=user)
                # 重新讀取權限，不信任 GET 時或客戶端送回的可用清單。
                current = favorite_context(user, preference, policy=AccessPolicy(user))
                if expected_version != preference.home_favorites_version:
                    context = current
                    status = 409
                    raise ValidationError("收藏已被另一個視窗更新，本次未覆寫。下方已載入目前設定，請確認後再儲存。")
                selected = validate_selection(request.POST, current)
                preference.home_favorites = selected
                preference.home_favorites_version += 1
                preference.save(update_fields=["home_favorites", "home_favorites_version", "updated_at"])
            messages.success(request, "我的最愛已儲存，其他裝置登入此帳號也會套用。")
            return redirect("dashboard")
        except (ValueError, ValidationError) as exc:
            status = status if status == 409 else 400
            context["favorite_error"] = "設定版本無效，請重新整理。" if isinstance(exc, ValueError) else exc.messages[0]
            if status != 409:
                fresh = favorite_context(request.user, preference, policy=AccessPolicy(request.user), selected=request.POST.getlist("favorite"))
                context.update(fresh)
    return render(request, "sales/home_favorites.html", context, status=status)
