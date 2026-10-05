from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from sales.reporting.models import ReportDefinition

SKIP_PREFIXES = ("admin/", "django-rq/", "logout", "health")


def parameterless_paths(patterns=None, prefix=""):
    for pattern in patterns if patterns is not None else get_resolver().url_patterns:
        route = str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            if "<" not in route and "(?P" not in route:
                yield from parameterless_paths(pattern.url_patterns, prefix + route)
        elif isinstance(pattern, URLPattern) and "<" not in route and "(?P" not in route:
            path = (prefix + route).lstrip("^").rstrip("$")
            if not path.startswith(SKIP_PREFIXES):
                yield "/" + path


class EmptySystemPagesTests(TestCase):
    """清空業務資料後，只剩帳號時所有無參數頁面都不可 500。"""

    def test_every_parameterless_page_renders_without_server_error(self):
        root = get_user_model().objects.create_superuser("admin", password="Empty-root-925!")
        self.client.force_login(root)
        call_command("seed_report_templates", stdout=StringIO())
        report_paths = [reverse("report_display", args=[pk]) for pk in ReportDefinition.objects.values_list("pk", flat=True)]
        self.assertTrue(report_paths)
        failures = []
        for path in sorted(set(parameterless_paths())) + report_paths:
            response = self.client.get(path)
            if response.status_code >= 500:
                failures.append(f"{path} -> {response.status_code}")
        self.assertEqual(failures, [])
