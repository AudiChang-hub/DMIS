import logging
import uuid


logger = logging.getLogger("dmis.request")


class RequestIdMiddleware:
    """為每個請求建立不含個資的查修編號。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = uuid.uuid4().hex[:12].upper()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        if response.status_code >= 500:
            logger.error(
                "request_failed request_id=%s method=%s path=%s status=%s",
                request.request_id,
                request.method,
                request.path,
                response.status_code,
            )
        return response
