Drop-in replacement for [`requests`](https://github.com/psf/requests) with default timeouts and retry support

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

```python
>>> import utils.rerequests as requests  # drop-in replacement

>>> # as normal, but with timeouts by default (and no retries)
>>> requests.get(URL)
>>> requests.get(URL, timeout=(3.05, 27))  # override default

>>> # accessible retry config
>>> requests.post(URL, max_retries=10)  # retry transient errors despite POST
>>> requests.put(URL, max_retries=requests.Retry(5, **more_config))

>>> # automatically response.raise_for_status(), with logging
>>> requests.delete(URL, hooks=requests.http_raise)
```

Resources:
 * https://en.wikipedia.org/wiki/Exponential_backoff#Truncated_exponential_backoff
 * https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
 * https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/
