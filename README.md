# Rerequests

Drop-in replacement for `requests` with default timeouts and retry support

 * `requests` has no timeout by default and can hang unnecessarily
   https://github.com/psf/requests/issues/3070
 * `requests` has poor retry support. Transient errors are not retried by
   default, and retry functionality is buried under "Lower-Lower-Level Classes"
   https://github.com/psf/requests/blob/v2.31.0/docs/api.rst?plain=1#L61-L71
   https://requests.readthedocs.io/en/latest/api/#requests.adapters.HTTPAdapter

[![PyPI - Version](https://img.shields.io/pypi/v/rerequests.svg)](https://pypi.org/project/rerequests)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/rerequests.svg)](https://pypi.org/project/rerequests)

-----

**Table of Contents**

- [Installation](#installation)
- [Notes](#notes)
- [License](#license)

## Installation

```console
pip install rerequests
```

## Notes

`rerequests` only tweaks "convenience" usages (e.g. requests.{get,put,...}):

 * Timeout of 60 seconds (6 sec connect + 54 sec read), by default
 * Conveniently configurable `max_retries` and `Retry()`
 * Retry implements truncated exponential backoff with jitter, by default

And provides the following extensions:

 * Convenient requests.http_raise hook for 4XX and 5XX exceptions

Examples:

```python
import rerequests as requests  # drop-in replacement

# same usage, but with timeouts (and no retries)
requests.get(URL)
requests.get(URL, timeout=(3.05, 27))  # override default

# accessible retry config
requests.post(URL, max_retries=2)  # retries transient errors despite non-idempotent POST
requests.put(URL, max_retries=requests.Retry(5, **more_config))

# inline response.raise_for_status() hook, with logging
requests.delete(URL, hooks=requests.http_raise)
```

Resources:
 * https://en.wikipedia.org/wiki/Exponential_backoff#Truncated_exponential_backoff
 * https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
 * https://findwork.dev/blog/advanced-usage-python-requests-timeouts-retries-hooks/

## License

`rerequests` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
