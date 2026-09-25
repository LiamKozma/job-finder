from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status


def request_json(url: str, method: str = "GET", payload: dict | None = None,
                 headers: dict | None = None, timeout: float = 25, retries: int = 2):
    data = json.dumps(payload).encode() if payload is not None else None
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = HttpError(e.code, url)
            if e.code in (400, 401, 403, 404, 410, 422):
                raise last
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


def get_text(url: str, timeout: float = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")
