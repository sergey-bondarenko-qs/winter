import time
import typing

import dataclasses
from django.core.cache import cache as default_cache
from rest_framework.throttling import BaseThrottle

from ..core import annotate_method

if typing.TYPE_CHECKING:
    from ..routing import Route  # noqa: F401


@dataclasses.dataclass
class ThrottlingAnnotation:
    rate: typing.Optional[str]
    scope: typing.Optional[str]


@dataclasses.dataclass
class Throttling:
    num_requests: int
    duration: int
    scope: str


def throttling(rate: typing.Optional[str], scope: typing.Optional[str] = None):
    return annotate_method(ThrottlingAnnotation(rate, scope), single=True)


class BaseRateThrottle:
    cache = default_cache
    cache_format = 'throttle_{scope}_{ident}'

    def __init__(self, throttling_: Throttling):
        self.throttling_ = throttling_

    def allow_request(self, request) -> bool:
        if self.throttling_ is None:
            return True

        ident = self.get_ident(request)
        key = self._get_cache_key(self.throttling_.scope, ident)

        history = self.cache.get(key, [])
        now = time.time()

        while history and history[-1] <= now - self.throttling_.duration:
            history.pop()

        if len(history) >= self.throttling_.num_requests:
            return False

        history.insert(0, now)
        self.cache.set(key, history, self.throttling_.duration)
        return True

    def _get_cache_key(self, scope: str, ident: str) -> str:
        return self.cache_format.format(scope=scope, ident=ident)

    def get_ident(self, request) -> str:
        user_pk = request.user.pk if request.user.is_authenticated else None

        if user_pk is not None:
            return str(user_pk)
        return self.get_ident_from_meta(request)

    def get_ident_from_meta(self, request):
        """
        Identify the machine making the request by parsing HTTP_X_FORWARDED_FOR
        if present. If not use all of HTTP_X_FORWARDED_FOR if it is available,
        if not use REMOTE_ADDR.
        """
        xff = request.META.get('HTTP_X_FORWARDED_FOR')
        remote_addr = request.META.get('REMOTE_ADDR')

        return ''.join(xff.split()) if xff else remote_addr


def _parse_rate(rate: str) -> typing.Tuple[int, int]:
    """
    Given the request rate string, return a two tuple of:
    <allowed number of requests>, <period of time in seconds>
    """
    num, period = rate.split('/')
    num_requests = int(num)
    duration = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[period[0]]
    return num_requests, duration


def create_throttle_class(route: 'Route') -> typing.Optional[BaseRateThrottle]:
    throttling_annotation = route.method.annotations.get_one_or_none(ThrottlingAnnotation)

    if getattr(throttling_annotation, 'rate', None) is None:
        return None

    num_requests, duration = _parse_rate(throttling_annotation.rate)
    throttling_scope = throttling_annotation.scope or route.method.full_name
    throttling_ = Throttling(num_requests, duration, throttling_scope)

    return BaseRateThrottle(throttling_)
