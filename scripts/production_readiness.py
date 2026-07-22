from __future__ import annotations

import argparse
import json
import math
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REQUIRED_SECURITY_HEADERS = {
    "content-security-policy",
    "permissions-policy",
    "referrer-policy",
    "x-content-type-options",
    "x-frame-options",
}


@dataclass(frozen=True)
class RequestObservation:
    status_code: int
    duration_ms: float
    error: str | None = None


@dataclass(frozen=True)
class LoadTestResult:
    url: str
    requests: int
    successful: int
    failed: int
    error_rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    duration_seconds: float
    requests_per_second: float
    passed: bool
    thresholds: dict[str, float]


def run_load_test(
    url: str,
    *,
    request_count: int,
    concurrency: int,
    timeout_seconds: float,
    max_error_rate: float,
    max_p95_ms: float,
    bearer_token: str = "",
) -> LoadTestResult:
    if not 1 <= request_count <= 10_000:
        raise ValueError("request_count must be between 1 and 10000")
    if not 1 <= concurrency <= 100:
        raise ValueError("concurrency must be between 1 and 100")

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(_observe_request, url, timeout_seconds, bearer_token)
            for _ in range(request_count)
        ]
        observations = [future.result() for future in as_completed(futures)]
    elapsed = max(time.perf_counter() - started, 0.000001)

    successful = sum(
        1 for observation in observations if 200 <= observation.status_code < 400
    )
    durations = sorted(observation.duration_ms for observation in observations)
    error_rate = (request_count - successful) / request_count
    p95_ms = percentile(durations, 95)
    return LoadTestResult(
        url=url,
        requests=request_count,
        successful=successful,
        failed=request_count - successful,
        error_rate=error_rate,
        p50_ms=percentile(durations, 50),
        p95_ms=p95_ms,
        p99_ms=percentile(durations, 99),
        duration_seconds=round(elapsed, 6),
        requests_per_second=round(request_count / elapsed, 3),
        passed=error_rate <= max_error_rate and p95_ms <= max_p95_ms,
        thresholds={"max_error_rate": max_error_rate, "max_p95_ms": max_p95_ms},
    )


def check_security_headers(
    url: str,
    *,
    timeout_seconds: float = 5,
    allow_http: bool = False,
) -> list[str]:
    errors: list[str] = []
    if not allow_http and not url.lower().startswith("https://"):
        errors.append("Production security checks require an HTTPS URL.")
    request = Request(url, method="GET", headers={"User-Agent": "aeai-readiness/1.0"})
    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
            context=ssl.create_default_context(),
        ) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
    except (HTTPError, URLError, TimeoutError) as exc:
        return [f"Unable to reach {url}: {exc}"]

    for header in sorted(REQUIRED_SECURITY_HEADERS - set(headers)):
        errors.append(f"Missing required security header: {header}.")
    if url.lower().startswith("https://") and "strict-transport-security" not in headers:
        errors.append("Missing required security header: strict-transport-security.")
    if headers.get("x-frame-options", "").upper() != "DENY":
        errors.append("x-frame-options must be DENY.")
    if headers.get("x-content-type-options", "").lower() != "nosniff":
        errors.append("x-content-type-options must be nosniff.")
    return errors


def percentile(values: list[float], rank: int) -> float:
    if not values:
        return 0.0
    index = max(math.ceil((rank / 100) * len(values)) - 1, 0)
    return round(values[index], 3)


def _observe_request(url: str, timeout_seconds: float, bearer_token: str) -> RequestObservation:
    headers = {"User-Agent": "aeai-readiness/1.0"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request = Request(url, method="GET", headers=headers)
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response.read(1024)
            return RequestObservation(
                status_code=response.status,
                duration_ms=(time.perf_counter() - started) * 1000,
            )
    except HTTPError as exc:
        return RequestObservation(
            status_code=exc.code,
            duration_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )
    except (URLError, TimeoutError) as exc:
        return RequestObservation(
            status_code=0,
            duration_ms=(time.perf_counter() - started) * 1000,
            error=str(exc),
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run production readiness probes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    load = subparsers.add_parser("load", help="Run a bounded concurrent load test.")
    load.add_argument("--url", required=True)
    load.add_argument("--requests", type=int, default=200)
    load.add_argument("--concurrency", type=int, default=10)
    load.add_argument("--timeout", type=float, default=5)
    load.add_argument("--max-error-rate", type=float, default=0.01)
    load.add_argument("--max-p95-ms", type=float, default=500)
    load.add_argument("--bearer-token", default="")
    load.add_argument("--output", type=Path)

    security = subparsers.add_parser("security", help="Validate public HTTP protections.")
    security.add_argument("--url", required=True)
    security.add_argument("--timeout", type=float, default=5)
    security.add_argument("--allow-http", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "security":
        errors = check_security_headers(
            args.url,
            timeout_seconds=args.timeout,
            allow_http=args.allow_http,
        )
        if errors:
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
            return 1
        print("Security header validation passed.")
        return 0

    result = run_load_test(
        args.url,
        request_count=args.requests,
        concurrency=args.concurrency,
        timeout_seconds=args.timeout,
        max_error_rate=args.max_error_rate,
        max_p95_ms=args.max_p95_ms,
        bearer_token=args.bearer_token,
    )
    payload = json.dumps(asdict(result), indent=2, sort_keys=True)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
