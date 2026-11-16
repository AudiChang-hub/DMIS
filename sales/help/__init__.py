"""使用說明（T-197）：文章資料在 articles.py，格式在 schema.py。"""
from datetime import date

from .articles import ARTICLES, GROUPS, START_HERE, TIPS

BY_SLUG = {article.slug: article for article in ARTICLES}
BY_ROUTE = {route: article.slug for article in ARTICLES for route in article.routes}
BY_LEGACY_TOPIC = {topic: article.slug for article in ARTICLES for topic in article.replaces}


def _permitted(policy, article):
    from sales.services.audience_content import permitted
    return permitted(policy, article.access) if article.access else policy.active


def visible_articles(policy):
    return [article for article in ARTICLES if _permitted(policy, article)]


def visible_article(policy, slug):
    article = BY_SLUG.get(slug)
    return article if article and _permitted(policy, article) else None


def article_for_route(policy, route_name):
    slug = BY_ROUTE.get(route_name or "")
    return visible_article(policy, slug) if slug else None


def article_for_legacy_topic(policy, topic):
    slug = BY_LEGACY_TOPIC.get((topic or "").removesuffix("-current"))
    return visible_article(policy, slug) if slug else None


def grouped(articles):
    rows = []
    for group in GROUPS:
        items = [article for article in articles if article.group == group.key]
        if items:
            rows.append({"group": group, "articles": items})
    return rows


def plain(text):
    """搜尋與手冊用：拿掉 [[ ]] 與 ** 標記。"""
    return (text or "").replace("[[", "「").replace("]]", "」").replace("**", "")


def search_index(articles):
    entries = []
    for article in articles:
        parts = [article.when, article.example.story, *(f"{label} {value}" for label, value in article.example.facts)]
        for step in article.steps:
            parts += [step.text, step.example, step.note]
        faqs = [{"q": plain(faq.question), "a": plain(faq.answer)} for faq in article.faqs]
        entries.append({
            "slug": article.slug, "title": article.title, "when": article.when,
            "group": next(group.title for group in GROUPS if group.key == article.group),
            "text": plain(" ".join(part for part in parts if part)), "faqs": faqs,
        })
    return entries


def tips_for(policy, today=None, count=4):
    """依日期輪替，同一天看到同一組；連到看不到的文章就不連。"""
    today = today or date.today()
    if not TIPS:
        return []
    start = today.toordinal() % len(TIPS)
    rotated = TIPS[start:] + TIPS[:start]
    picked = []
    for tip in rotated[:count]:
        target = visible_article(policy, tip.article) if tip.article else None
        picked.append({"tip": tip, "article": target})
    return picked


def start_stops(policy):
    stops = []
    for number, stop in enumerate(START_HERE, 1):
        stops.append({"number": number, "stop": stop, "article": visible_article(policy, stop.article)})
    return stops


__all__ = ["ARTICLES", "GROUPS", "START_HERE", "TIPS", "article_for_legacy_topic", "article_for_route", "grouped",
           "plain", "search_index", "start_stops", "tips_for", "visible_article", "visible_articles"]
