from collections import namedtuple
from contextlib import contextmanager
import functools as ft
from unittest.mock import patch

import pytest
import urllib3

import utils.rerequests as requests
from utils.rerequests import Retry


def retry_obj(session):
    return session.adapters['https://'].max_retries


@contextmanager
def capture_retry_and_timeout():
    RuntimeCapture = namedtuple('RuntimeCapture', ['capture_retry', 'capture_timeout'])

    orig_from_request_kwargs = requests._ReSession._for_convenience_api
    captures = {}

    @ft.wraps(orig_from_request_kwargs)
    def wrapped_orig(*args, **kwargs):
        session = orig_from_request_kwargs(*args, **kwargs)
        captures['session'] = session
        return session

    with patch.object(requests._ReSession, '_for_convenience_api') as mock_from_request:
        mock_from_request.side_effect = wrapped_orig

        with patch.object(requests.Session, 'request') as request_meth:

            yield RuntimeCapture(
                capture_retry=lambda: retry_obj(captures['session']),  # session obj from convenience api
                capture_timeout=lambda: request_meth.mock_calls[0][-1]['timeout'],  # timeout arg as passed to request()
            )


def test_retry_equality():
    assert Retry(3) == Retry(3)
    assert Retry() == Retry()
    assert Retry(1) != Retry(2)
    assert Retry(2) != urllib3.util.retry.Retry(2)
    assert urllib3.util.retry.Retry(2) != Retry(2)


def test_retry_backoff():
    retries = [Retry(9)]
    for _ in range(9):
        retry = retries[-1].increment()
        assert isinstance(retry, Retry)
        retries.append(retry)

    with patch('random.uniform') as mock_random_uniform:
        mock_random_uniform.side_effect = lambda a, b: (a + b) / 2  # i.e. expected value
        assert [r.get_backoff_time() for r in retries] == [0, 1, 2, 4, 8, 16, 32, 64, 120, 120]

    jittered_backoffs = {retries[3].get_backoff_time() for _ in range(10_000)}
    assert len(jittered_backoffs) == 10_000
    assert all(0 <= t <= 8 for t in jittered_backoffs)
    assert 3.5 < sum(jittered_backoffs) / 10_000 < 4.5


def test_init_defaults():
    assert Retry.DEFAULT.total and Retry.DEFAULT.total > 0
    assert Retry.DEFAULT == Retry(allowed_methods=requests.IDEMPOTENT_METHODS)

    http = requests._ReSession()
    assert retry_obj(http) is Retry.DEFAULT
    assert http.timeout == requests.DEFAULT_TIMEOUT
    connect_ttl, read_ttl = requests.DEFAULT_TIMEOUT
    assert connect_ttl > 0 and read_ttl > 0

    created_retry = Retry()
    for method in ['GET', 'OPTIONS', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE']:
        for err_status_code in range(400, 600):
            is_transient = err_status_code in requests.TRANSIENT_ERRORS
            is_idempotent = method in requests.IDEMPOTENT_METHODS
            assert created_retry.is_retry(method, err_status_code) == is_transient
            assert Retry.DEFAULT.is_retry(method, err_status_code) == (is_transient and is_idempotent)


def test_convenience_api():
    with patch.object(requests.Session, 'request') as request_meth:
        requests.get('https://instacart.com', max_retries=2, timeout=29, foo='bar')

        _, _, kwargs = request_meth.mock_calls[0]
        assert 'max_retries' not in kwargs, "Should remove max_retries from kwargs before passing to request()"
        assert kwargs['timeout'] == 29, "Should pass timeout to request()"
        assert kwargs['foo'] == 'bar', "Should leave other kwargs untouched"

    with capture_retry_and_timeout() as objs:
        requests.get('https://instacart.com')

        assert objs.capture_timeout() == requests.DEFAULT_TIMEOUT
        assert objs.capture_retry() == Retry(0), "Convenience API should have 0 retries by default"

    with capture_retry_and_timeout() as objs:
        requests.put('https://instacart.com', max_retries=2, timeout=5)

        assert objs.capture_timeout() == 5
        assert objs.capture_retry() == Retry(2)

    with capture_retry_and_timeout() as objs:
        retry = Retry()
        requests.post('https://instacart.com', max_retries=retry, timeout=(6, 7))

        assert objs.capture_timeout() == (6, 7)
        assert objs.capture_retry() is retry

    with capture_retry_and_timeout() as objs:
        requests.delete('https://instacart.com', max_retries=None, timeout=None)

        assert objs.capture_timeout() is None
        assert objs.capture_retry() == Retry(0)


@pytest.mark.skip(reason='ReSession is private, behavior is WIP')
def test_resession_construction():
    http = requests._ReSession()
    assert http.adapters['https://'] is http.adapters['http://'], "Other tests depend on this"

    with pytest.raises(TypeError):
        requests._ReSession(1, 2)  # type: ignore


@pytest.mark.skip(reason='ReSession is private, behavior is WIP')
def test_resession_timeout():
    def resolved_timeout(session={}, request={}):
        with capture_retry_and_timeout() as objs:
            with requests._ReSession(**session) as http:
                http.get('https://instacart.com', **request)
                return objs.capture_timeout()

    assert resolved_timeout() == requests.DEFAULT_TIMEOUT
    assert resolved_timeout(session={'timeout': (9, 8)}) == (9, 8)
    assert resolved_timeout(session={'timeout': 0}) == 0
    assert resolved_timeout(session={'timeout': None}) is None

    assert resolved_timeout(request={'timeout': 4}) == 4
    assert resolved_timeout(request={'timeout': 0}) == 0
    assert resolved_timeout(request={'timeout': None}) is None

    assert resolved_timeout(session={'timeout': 3}) == 3
    assert resolved_timeout(session={'timeout': 3}, request={'timeout': (1, 2)}) == (1, 2)
    assert resolved_timeout(session={'timeout': 3}, request={'timeout': 0}) is 0
    assert resolved_timeout(session={'timeout': 3}, request={'timeout': None}) is None


@pytest.mark.skip(reason='ReSession is private, behavior is WIP')
def test_resession_retry():
    assert retry_obj(requests._ReSession()) is Retry.DEFAULT
    assert retry_obj(requests._ReSession(max_retries=8)) == Retry(8)

    assert retry_obj(requests._ReSession(max_retries=None)) is not urllib3.util.retry.Retry.DEFAULT  # type: ignore
    assert retry_obj(requests._ReSession(max_retries=None)) == Retry(0), "Should reproduce requests.HTTPAdapter default"

    retry_eleven = Retry(11)
    with requests._ReSession(max_retries=retry_eleven) as http:
        assert retry_obj(http) is retry_eleven, "Should pass Retry obj through"
