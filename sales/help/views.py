"""新版使用說明頁（T-197）。舊版 /help/ 仍由 sales.views.user_guide 提供，全部文章完成後再切換。"""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse

from config.release_notes import CURRENT_VERSION, RELEASES
from sales.access.services import policy_for

from . import article_for_legacy_topic, article_for_route, grouped, search_index, start_stops, tips_for, visible_article, visible_articles
from .articles import GROUPS, START_HERE


def _open_url(route):
    try:
        return reverse(route) if route else ""
    except NoReverseMatch:
        return ""


@login_required
def help_home(request):
    policy = policy_for(request)
    topic = request.GET.get("topic", "")
    if topic:
        # 舊連結 /help/?topic=…：已改寫的轉到新文章，其餘轉到舊版的同一段。
        article = article_for_legacy_topic(policy, topic)
        if article:
            return redirect("help_article", slug=article.slug)
        return redirect(f"{reverse('user_guide_legacy')}?{request.GET.urlencode()}")
    articles = visible_articles(policy)
    from_route = request.GET.get("from", "")
    return render(request, "help/home.html", {
        "groups": grouped(articles),
        "index": search_index(articles),
        "tips": tips_for(policy),
        "release": RELEASES[0],
        "release_version": CURRENT_VERSION,
        "context_article": article_for_route(policy, from_route),
        "start_visible": any(item["article"] for item in start_stops(policy)),
    })


@login_required
def help_start(request):
    policy = policy_for(request)
    stops = start_stops(policy)
    for item in stops:
        item["open_url"] = _open_url(item["stop"].open_route)
    return render(request, "help/start.html", {"stops": stops})


@login_required
def help_article(request, slug):
    policy = policy_for(request)
    article = visible_article(policy, slug)
    if article is None:
        raise Http404("找不到這篇說明。")
    group = next(group for group in GROUPS if group.key == article.group)
    siblings = [item for item in visible_articles(policy) if item.group == article.group]
    related = [item for item in (visible_article(policy, slug) for slug in article.related) if item]
    next_article = visible_article(policy, article.next_slug) if article.next_slug else None
    in_start = [stop.article for stop in START_HERE]
    return render(request, "help/article.html", {
        "article": article, "group": group, "siblings": siblings, "related": related,
        "next_article": next_article, "open_url": _open_url(article.open_route),
        "start_number": in_start.index(article.slug) + 1 if article.slug in in_start else None,
    })
