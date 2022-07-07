"""
Drop-in replacement for `requests` with default timeouts and retry support

 * `requests` has no timeout by default and can hang forever
   https://github.com/psf/requests/issues/3070
 * `requests` has poor retry support. It doesn't retry transient errors by
   default, and it's buried under "Lower-Lower-Level Classes"
   https://requests.readthedocs.io/en/v2.9.1/api/#lower-level-classes
   https://requests.readthedocs.io/en/v2.9.1/api/#requests.adapters.HTTPAdapter

`rerequests` only changes convenience usages (e.g. requests.{get,put,...}):

 * Sensible timeouts by default
 * Conveniently configurable `max_retries` and `Retry()`
 * Retry by default implements truncated exponential backoff with jitter

And provides the following extensions:

 * Convenient requests.http_raise hook for 4XX and 5XX exceptions

Examples:

  >>> import rerequests as requests  # drop-in replacement

  >>> # as normal, but with timeouts by default (and no retries)
  >>> requests.get(URL)
  >>> requests.get(URL, timeout=(3.05, 27))  # override default

  >>> # accessible retry config
  >>> requests.post(URL, max_retries=10)  # retry transient errors despite POST
  >>> requests.put(URL, max_retries=requests.Retry(5, **more_config)

  >>> # automatically response.raise_for_status(), with logging
  >>> requests.delete(URL, hooks=requests.http_raise)

Resources:
 * https://en.wikipedia.org/wiki/Exponential_backoff#Truncated_exponential_backoff
 * https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
 * https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/
"""

from __future__ import annotations
import itertools as it
import logging
import packaging.version as version
import random

import requests
from requests import *  # type: ignore in order to be a true drop-in replacement
import urllib3.util

if version.parse(requests.__version__) >= version.parse('3.0.0'):
    raise ImportError('rerequests is a drop-in replacement for requests 2, re-evaluate for v3')

DEFAULT_TIMEOUT = (6.1, 54)  # (connect, read), see: https://docs.python-requests.org/en/latest/user/advanced/#timeouts
TRANSIENT_ERRORS = frozenset({
    codes.request_timeout,        # 408
    codes.too_many_requests,      # 429 - may have Retry-After header
    codes.internal_server_error,  # 500
    codes.bad_gateway,            # 502
    codes.service_unavailable,    # 503 - may have Retry-After header
    codes.gateway_timeout,        # 504
})
IDEMPOTENT_METHODS = urllib3.util.Retry.DEFAULT_ALLOWED_METHODS


class Retry(urllib3.util.Retry):
    """Retry configuration, with nicer defaults and jitter

    see: https://urllib3.readthedocs.io/en/latest/reference/urllib3.util.html#urllib3.util.Retry
    """

    DEFAULT: Retry = None  # type: ignore and assign later

    def __init__(
        self,
        total=3,                            # num retries, i.e. 4 requests in total
        status_forcelist=TRANSIENT_ERRORS,
        allowed_methods=False,              # retry all methods when instantiating manually
        backoff_factor=1,                   # retry after 1, 2, 4, 8, ...
        **kwargs,
    ):
        super().__init__(
            total=total,
            status_forcelist=status_forcelist,
            allowed_methods=allowed_methods,
            backoff_factor=backoff_factor,
            **kwargs,
        )

    def get_backoff_time(self):
        # We want to consider only the last consecutive errors sequence (Ignore redirects).
        consecutive_errors_len = len(
            list(
                it.takewhile(lambda x: x.redirect_location is None, reversed(self.history))
            )
        )
        if consecutive_errors_len < 1:  # NOTE: differs from super().get_backoff_time()
            return 0.0

        backoff_value = self.backoff_factor * (2 ** (consecutive_errors_len - 1))
        # NOTE: below differs from super().get_backoff_time()
        jittered = random.uniform(0.0, backoff_value * 2.0)  # "Full Jitter"
        return min(self.DEFAULT_BACKOFF_MAX, jittered)

    def __eq__(self, other):
        return isinstance(other, type(self)) and vars(other) == vars(self)

    @classmethod
    def _from_arg(cls, max_retries, **init_kwargs):
        return max_retries if isinstance(max_retries, cls) else cls(max_retries, **init_kwargs)


Retry.DEFAULT = Retry(allowed_methods=IDEMPOTENT_METHODS)  # symmetrical to urllib3.util.retry.DEFAULT


def raise_for_status(response: Response, **kwargs):
    """Response hook for `response.raise_for_status()` and logging

    Example:

    >>> requests.get(URL, hooks={'response': raise_for_status})
    >>> requests.get(URL, hooks=requests.http_raise)  # alternative
    """
    try:
        response.raise_for_status()
    except HTTPError:
        try:
            logging.error(response.json())
        except Exception:
            logging.error(response.text)
        raise
    return response


http_raise = {'response': [raise_for_status]}


class _ReSession(sessions.Session):
    """Still WIP, implementation may change!"""

    def __init__(self, *, timeout=DEFAULT_TIMEOUT, max_retries=Retry.DEFAULT):
        super().__init__()

        self.timeout = timeout
        max_retries = 0 if max_retries is None else max_retries  # same default behavior as requests.HTTPAdapter
        retry = Retry._from_arg(max_retries, allowed_methods=IDEMPOTENT_METHODS)
        adapter = sessions.HTTPAdapter(max_retries=retry)

        self.mount('https://', adapter)
        self.mount('http://', adapter)

    def request(self, method, url, **kwargs):
        timeout = kwargs.pop('timeout', self.timeout)
        return super().request(method, url, timeout=timeout, **kwargs)

    @classmethod
    def _for_convenience_api(cls, kwargs_for_request):
        max_retries = kwargs_for_request.pop('max_retries', None) or 0  # default for convenience api
        return cls(max_retries=Retry._from_arg(max_retries))


########
# Below this point, source is identical to requests.api, save for one usage of _ReSession
########


def request(method, url, **kwargs):
    """Constructs and sends a :class:`Request <Request>`.

    :param method: method for the new :class:`Request` object: ``GET``, ``OPTIONS``, ``HEAD``, ``POST``, ``PUT``, ``PATCH``, or ``DELETE``.
    :param url: URL for the new :class:`Request` object.
    :param params: (optional) Dictionary, list of tuples or bytes to send
        in the query string for the :class:`Request`.
    :param data: (optional) Dictionary, list of tuples, bytes, or file-like
        object to send in the body of the :class:`Request`.
    :param json: (optional) A JSON serializable Python object to send in the body of the :class:`Request`.
    :param headers: (optional) Dictionary of HTTP Headers to send with the :class:`Request`.
    :param cookies: (optional) Dict or CookieJar object to send with the :class:`Request`.
    :param files: (optional) Dictionary of ``'name': file-like-objects`` (or ``{'name': file-tuple}``) for multipart encoding upload.
        ``file-tuple`` can be a 2-tuple ``('filename', fileobj)``, 3-tuple ``('filename', fileobj, 'content_type')``
        or a 4-tuple ``('filename', fileobj, 'content_type', custom_headers)``, where ``'content-type'`` is a string
        defining the content type of the given file and ``custom_headers`` a dict-like object containing additional headers
        to add for the file.
    :param auth: (optional) Auth tuple to enable Basic/Digest/Custom HTTP Auth.
    :param timeout: (optional) How many seconds to wait for the server to send data
        before giving up, as a float, or a :ref:`(connect timeout, read
        timeout) <timeouts>` tuple.
    :type timeout: float or tuple
    :param allow_redirects: (optional) Boolean. Enable/disable GET/OPTIONS/POST/PUT/PATCH/DELETE/HEAD redirection. Defaults to ``True``.
    :type allow_redirects: bool
    :param proxies: (optional) Dictionary mapping protocol to the URL of the proxy.
    :param verify: (optional) Either a boolean, in which case it controls whether we verify
            the server's TLS certificate, or a string, in which case it must be a path
            to a CA bundle to use. Defaults to ``True``.
    :param stream: (optional) if ``False``, the response content will be immediately downloaded.
    :param cert: (optional) if String, path to ssl client cert file (.pem). If Tuple, ('cert', 'key') pair.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response

    Usage::

      >>> import requests
      >>> req = requests.request('GET', 'https://httpbin.org/get')
      >>> req
      <Response [200]>
    """

    # By using the 'with' statement we are sure the session is closed, thus we
    # avoid leaving sockets open which can trigger a ResourceWarning in some
    # cases, and look like a memory leak in others.
    with _ReSession._for_convenience_api(kwargs) as session:
        return session.request(method=method, url=url, **kwargs)


def get(url, params=None, **kwargs):
    r"""Sends a GET request.

    :param url: URL for the new :class:`Request` object.
    :param params: (optional) Dictionary, list of tuples or bytes to send
        in the query string for the :class:`Request`.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    kwargs.setdefault('allow_redirects', True)
    return request('get', url, params=params, **kwargs)


def options(url, **kwargs):
    r"""Sends an OPTIONS request.

    :param url: URL for the new :class:`Request` object.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    kwargs.setdefault('allow_redirects', True)
    return request('options', url, **kwargs)


def head(url, **kwargs):
    r"""Sends a HEAD request.

    :param url: URL for the new :class:`Request` object.
    :param \*\*kwargs: Optional arguments that ``request`` takes. If
        `allow_redirects` is not provided, it will be set to `False` (as
        opposed to the default :meth:`request` behavior).
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    kwargs.setdefault('allow_redirects', False)
    return request('head', url, **kwargs)


def post(url, data=None, json=None, **kwargs):
    r"""Sends a POST request.

    :param url: URL for the new :class:`Request` object.
    :param data: (optional) Dictionary, list of tuples, bytes, or file-like
        object to send in the body of the :class:`Request`.
    :param json: (optional) json data to send in the body of the :class:`Request`.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    return request('post', url, data=data, json=json, **kwargs)


def put(url, data=None, **kwargs):
    r"""Sends a PUT request.

    :param url: URL for the new :class:`Request` object.
    :param data: (optional) Dictionary, list of tuples, bytes, or file-like
        object to send in the body of the :class:`Request`.
    :param json: (optional) json data to send in the body of the :class:`Request`.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    return request('put', url, data=data, **kwargs)


def patch(url, data=None, **kwargs):
    r"""Sends a PATCH request.

    :param url: URL for the new :class:`Request` object.
    :param data: (optional) Dictionary, list of tuples, bytes, or file-like
        object to send in the body of the :class:`Request`.
    :param json: (optional) json data to send in the body of the :class:`Request`.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    return request('patch', url, data=data, **kwargs)


def delete(url, **kwargs):
    r"""Sends a DELETE request.

    :param url: URL for the new :class:`Request` object.
    :param \*\*kwargs: Optional arguments that ``request`` takes.
    :return: :class:`Response <Response>` object
    :rtype: requests.Response
    """

    return request('delete', url, **kwargs)
