#!/usr/bin/env python3
"""Fast, resumable public app-review collector for the IMOTION app list.

The program deliberately keeps the raw snapshot small and analysis-friendly:
it stores review text, ratings, dates, versions, helpfulness, and developer
replies when a store exposes them. Reviewer display names and profile-image
URLs are not written to either the raw normalized snapshot or cleaned CSVs.

It is designed for public reviews only. Store-side pagination, locale filters,
rate limits, deleted reviews, and access controls can prevent any scraper from
guaranteeing that literally every historical review is publicly retrievable.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import logging
import re
import socket
import sys
import threading
import time
import traceback
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import parse_qs, urlparse


LOGGER = logging.getLogger("imotion_reviews")
STATE_LOCK = threading.Lock()

CLEAN_COLUMNS = [
    "platform",
    "app_name",
    "tier",
    "app_id",
    "review_id",
    "review_date",
    "rating",
    "review_title",
    "review_text",
    "developer_reply",
    "developer_reply_date",
    "app_version",
    "thumbs_up_count",
    "is_edited",
    "fetch_locale",
    "source_url",
    "fetched_at",
]


@dataclass(frozen=True)
class AppRecord:
    name: str
    tier: str
    google_id: str
    apple_id: str
    slug: str


@dataclass(frozen=True)
class Job:
    app: AppRecord
    platform: str

    @property
    def key(self) -> str:
        return f"{self.app.slug}__{self.platform}"

    @property
    def app_id(self) -> str:
        return self.app.google_id if self.platform == "google_play" else self.app.apple_id


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "unnamed_app"


def normalize_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value)).replace("\x00", " ")
    # Store feeds occasionally contain HTML snippets in review bodies.
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value).strip()
    if not text:
        return ""
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return str(value)


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return normalize_date(value)
    return str(value)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8"
    )
    temporary.replace(path)


def configure_logging(output_dir: Path) -> Path:
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(threadName)s | %(message)s")
    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)
    return log_path


def load_apps(input_path: Path) -> tuple[list[AppRecord], list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError("openpyxl is missing. Run run_imotion_reviews.bat install first.") from exc

    workbook = load_workbook(input_path, read_only=True, data_only=True)
    apps: list[AppRecord] = []
    issues: list[str] = []

    for sheet in workbook.worksheets:
        current_tier = ""
        header: Optional[dict[str, int]] = None
        for row_number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
            cells = [normalize_text(value) for value in values]
            nonempty = [cell for cell in cells if cell]
            if not nonempty:
                continue

            tier_match = next((cell for cell in nonempty if re.match(r"^tier\s+\d+", cell, re.I)), None)
            if tier_match:
                current_tier = tier_match

            lowered = [cell.lower() for cell in cells]
            app_col = next((idx for idx, cell in enumerate(lowered) if cell == "app name"), None)
            google_col = next(
                (idx for idx, cell in enumerate(lowered) if "google play" in cell and "package" in cell),
                None,
            )
            apple_col = next(
                (idx for idx, cell in enumerate(lowered) if "apple app store" in cell and "id" in cell),
                None,
            )
            if app_col is not None:
                header = {"app": app_col, "google": google_col, "apple": apple_col}
                continue
            if header is None or header["app"] >= len(values):
                continue

            name = normalize_text(values[header["app"]])
            if not name or name.lower().startswith("tier"):
                continue
            google_id = normalize_id(values[header["google"]]) if header["google"] is not None and header["google"] < len(values) else ""
            apple_id = normalize_id(values[header["apple"]]) if header["apple"] is not None and header["apple"] < len(values) else ""
            if not google_id and not apple_id:
                issues.append(f"{sheet.title}!row {row_number}: {name} has neither a Google Play nor Apple ID")
                continue
            apps.append(
                AppRecord(
                    name=name,
                    tier=current_tier or "Unclassified",
                    google_id=google_id,
                    apple_id=apple_id,
                    slug=slugify(name),
                )
            )

    # Keep the first row for a duplicate app name/ID and report the duplicate.
    unique: list[AppRecord] = []
    seen = set()
    for app in apps:
        key = (app.name.lower(), app.google_id, app.apple_id)
        if key in seen:
            issues.append(f"duplicate input row ignored: {app.name}")
            continue
        seen.add(key)
        unique.append(app)
    return unique, issues


def parse_google_locales(args: argparse.Namespace) -> list[tuple[str, str]]:
    if not args.google_locales:
        return [(args.google_lang, args.google_country)]
    locales: list[tuple[str, str]] = []
    for token in args.google_locales.split(","):
        token = token.strip()
        if not token:
            continue
        parts = re.split(r"[:/]", token, maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Invalid --google-locales value {token!r}; use lang:country, e.g. id:id,en:us")
        locales.append((parts[0].strip(), parts[1].strip()))
    return locales or [(args.google_lang, args.google_country)]


def source_record(
    *,
    job: Job,
    review_id: Any,
    review_date: Any,
    rating: Any,
    review_title: Any = "",
    review_text: Any = "",
    developer_reply: Any = "",
    developer_reply_date: Any = "",
    app_version: Any = "",
    thumbs_up_count: Any = "",
    is_edited: Any = "",
    fetch_locale: str = "",
    source_url: str = "",
) -> dict[str, Any]:
    return {
        "platform": job.platform,
        "app_name": job.app.name,
        "tier": job.app.tier,
        "app_id": job.app_id,
        "review_id": normalize_text(review_id),
        "review_date": normalize_date(review_date),
        "rating": rating,
        "review_title": normalize_text(review_title),
        "review_text": normalize_text(review_text),
        "developer_reply": normalize_text(developer_reply),
        "developer_reply_date": normalize_date(developer_reply_date),
        "app_version": normalize_text(app_version),
        "thumbs_up_count": thumbs_up_count,
        "is_edited": is_edited,
        "fetch_locale": fetch_locale,
        "source_url": source_url,
        "fetched_at": now_iso(),
    }


def record_key(record: dict[str, Any]) -> str:
    review_id = normalize_text(record.get("review_id"))
    prefix = f"{record.get('platform', '')}|{record.get('app_id', '')}|"
    if review_id:
        return prefix + review_id
    material = "|".join(
        normalize_text(record.get(field))
        for field in ("review_date", "rating", "review_title", "review_text", "developer_reply")
    )
    return prefix + hashlib.sha256(material.encode("utf-8")).hexdigest()


def read_raw_keys(raw_path: Path) -> set[str]:
    keys: set[str] = set()
    if not raw_path.exists():
        return keys
    with raw_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                item = json.loads(line)
                keys.add(record_key(item))
            except (json.JSONDecodeError, TypeError):
                continue
    return keys


def append_raw(raw_path: Path, records: Iterable[dict[str, Any]]) -> int:
    records = list(records)
    if not records:
        return 0
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, default=json_default) + "\n")
    return len(records)


def backoff_sleep(args: argparse.Namespace, attempt: int) -> None:
    if args.retry_wait <= 0:
        return
    time.sleep(min(args.retry_wait * (2 ** max(attempt - 1, 0)), 60.0))


def write_job_state(state_path: Path, state: dict[str, Any]) -> None:
    with STATE_LOCK:
        write_json_atomic(state_path, state)


def base_state(job: Job, raw_path: Path) -> dict[str, Any]:
    return {
        "job_key": job.key,
        "platform": job.platform,
        "app_name": job.app.name,
        "tier": job.app.tier,
        "app_id": job.app_id,
        "raw_file": str(raw_path),
        "status": "not_started",
        "started_at": "",
        "finished_at": "",
        "attempts": 0,
        "pages": 0,
        "fetched_records": 0,
        "new_raw_records": 0,
        "errors": [],
        "warnings": [],
    }


def job_paths(output_dir: Path, job: Job) -> tuple[Path, Path]:
    return output_dir / "raw" / f"{job.key}.jsonl", output_dir / "state" / f"{job.key}.json"


def run_google_job(job: Job, args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    raw_path, state_path = job_paths(output_dir, job)
    state = base_state(job, raw_path)
    state["started_at"] = now_iso()
    existing_keys = read_raw_keys(raw_path)
    state["existing_raw_records"] = len(existing_keys)
    errors: list[str] = []
    warnings: list[str] = []
    fetched_records = 0
    pages = 0
    attempts = 0
    new_records = 0
    try:
        from google_play_scraper import Sort, reviews

        locales = parse_google_locales(args)
        state["locales"] = [f"{lang}:{country}" for lang, country in locales]
        seen_tokens: set[str] = set()
        for lang, country in locales:
            continuation = None
            while True:
                if args.max_pages and pages >= args.max_pages:
                    warnings.append(f"max-pages reached ({args.max_pages})")
                    break
                page_result: Optional[list[dict[str, Any]]] = None
                next_token = None
                page_error: Optional[Exception] = None
                for attempt in range(1, args.retries + 1):
                    attempts += 1
                    try:
                        socket.setdefaulttimeout(args.timeout)
                        page_result, continuation_obj = reviews(
                            job.app.google_id,
                            lang=lang,
                            country=country,
                            sort=Sort.NEWEST,
                            count=min(args.google_page_size, 4500),
                            continuation_token=continuation,
                        )
                        next_token = getattr(continuation_obj, "token", None)
                        page_error = None
                        break
                    except Exception as exc:  # package raises several custom exception types
                        page_error = exc
                        LOGGER.warning("%s Google page failed (attempt %s/%s): %s", job.key, attempt, args.retries, exc)
                        if attempt < args.retries:
                            backoff_sleep(args, attempt)
                if page_error is not None or page_result is None:
                    errors.append(f"{lang}:{country} page {pages + 1}: {page_error}")
                    break
                pages += 1
                fetched_records += len(page_result)
                normalized: list[dict[str, Any]] = []
                for item in page_result:
                    normalized.append(
                        source_record(
                            job=job,
                            review_id=item.get("reviewId"),
                            review_date=item.get("at"),
                            rating=item.get("score"),
                            review_text=item.get("content"),
                            developer_reply=item.get("replyContent"),
                            developer_reply_date=item.get("repliedAt"),
                            app_version=item.get("appVersion") or item.get("reviewCreatedVersion"),
                            thumbs_up_count=item.get("thumbsUpCount"),
                            fetch_locale=f"{lang}:{country}",
                            source_url=(
                                f"https://play.google.com/store/apps/details?id={job.app.google_id}"
                                f"&hl={lang}&gl={country}"
                            ),
                        )
                    )
                fresh = []
                for item in normalized:
                    key = record_key(item)
                    if key not in existing_keys:
                        existing_keys.add(key)
                        fresh.append(item)
                new_records += append_raw(raw_path, fresh)
                if args.throttle_ms:
                    time.sleep(args.throttle_ms / 1000.0)
                if not next_token:
                    break
                token_key = str(next_token)
                if token_key in seen_tokens:
                    warnings.append("pagination token repeated; stopped safely")
                    break
                seen_tokens.add(token_key)
                # The package's continuation token carries the locale and page size.
                continuation = continuation_obj
            if args.max_pages and pages >= args.max_pages:
                break
        if errors and fetched_records:
            status = "partial"
        elif errors:
            status = "failed"
        elif fetched_records == 0:
            status = "success_empty"
            warnings.append(
                "No reviews returned; verify the store ID/availability and retry with another locale if needed"
            )
        else:
            status = "success"
    except Exception as exc:
        errors.append(f"fatal: {type(exc).__name__}: {exc}")
        status = "failed"
        LOGGER.error("%s failed: %s", job.key, traceback.format_exc())
    state.update(
        {
            "status": status,
            "finished_at": now_iso(),
            "attempts": attempts,
            "pages": pages,
            "fetched_records": fetched_records,
            "new_raw_records": new_records,
            "errors": errors,
            "warnings": warnings,
        }
    )
    write_job_state(state_path, state)
    LOGGER.info("%s: %s; fetched=%s; new raw=%s", job.key, status, fetched_records, new_records)
    return state


def value_from_dict(data: Any, keys: Iterable[str]) -> Any:
    if not isinstance(data, dict):
        return ""
    lowered = {str(key).lower(): value for key, value in data.items()}
    for key in keys:
        if key.lower() in lowered and lowered[key.lower()] not in (None, ""):
            return lowered[key.lower()]
    return ""


def recursive_developer_response(attributes: dict[str, Any], item: dict[str, Any], payload: dict[str, Any]) -> tuple[Any, Any]:
    """Best-effort extraction; public Apple review feeds often omit replies."""

    candidate_objects: list[Any] = []
    for container in (attributes, item):
        if not isinstance(container, dict):
            continue
        for key, value in container.items():
            lowered = str(key).lower()
            if any(term in lowered for term in ("developer", "response", "reply")):
                candidate_objects.append(value)
    for included in payload.get("included", []) if isinstance(payload, dict) else []:
        if isinstance(included, dict) and "developer" in str(included.get("type", "")).lower():
            candidate_objects.append(included.get("attributes", included))

    for candidate in candidate_objects:
        if isinstance(candidate, dict):
            text = value_from_dict(candidate, ("body", "response", "reply", "text", "content", "message"))
            date = value_from_dict(candidate, ("date", "createdDate", "repliedAt", "responseDate"))
            if text:
                return text, date
        elif isinstance(candidate, str) and candidate.strip():
            return candidate, ""
    return "", ""


def apple_slug(name: str) -> str:
    return slugify(name).replace("_", "-")


def parse_country_from_url(url: str, fallback: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    return parts[0].lower() if parts else fallback


class AppleClient:
    def __init__(self, args: argparse.Namespace):
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests is missing. Run run_imotion_reviews.bat install first.") from exc
        self.requests = requests
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": args.user_agent,
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "Accept-Language": args.apple_language,
            }
        )
        self.args = args

    def request(self, method: str, url: str, **kwargs: Any):
        last: Optional[Exception] = None
        for attempt in range(1, self.args.retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=(self.args.connect_timeout, self.args.timeout),
                    **kwargs,
                )
                if 200 <= response.status_code < 300:
                    return response
                last = RuntimeError(f"HTTP {response.status_code} for {url}")
                # 404 is useful to report immediately; transient statuses are retried.
                if response.status_code not in {408, 425, 429, 500, 502, 503, 504}:
                    break
            except Exception as exc:
                last = exc
            LOGGER.warning("Apple request failed (attempt %s/%s): %s", attempt, self.args.retries, last)
            if attempt < self.args.retries:
                backoff_sleep(self.args, attempt)
        raise last or RuntimeError(f"request failed: {url}")

    def lookup_landing_url(self, app: AppRecord) -> Optional[str]:
        for country in (self.args.apple_country, "us"):
            try:
                response = self.request(
                    "GET",
                    "https://itunes.apple.com/lookup",
                    params={"id": app.apple_id, "country": country},
                )
                data = response.json()
                results = data.get("results", []) if isinstance(data, dict) else []
                if results:
                    url = results[0].get("trackViewUrl") or results[0].get("sellerUrl")
                    if url:
                        return str(url).split("?", 1)[0]
            except Exception as exc:
                LOGGER.warning("Apple lookup failed for %s (%s): %s", app.name, country, exc)
        return None

    def extract_token(self, text: str) -> Optional[str]:
        patterns = [
            # Apple embeds the environment JSON URL-encoded in a meta tag.
            # Keep percent escapes inside the token; the upstream public feed
            # expects the token in the same encoded representation.
            r"token%22%3A%22(.+?)%22",
            r"token%22\s*%3A\s*%22(.+?)%22",
            r"\"token\"\s*:\s*\"([^\"]+)\"",
            r"\\\"token\\\"\s*:\s*\\\"([^\\\"]+)\\\"",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return html.unescape(match.group(1))
        return None

    def landing_and_token(self, app: AppRecord) -> tuple[str, str, str]:
        lookup_url = self.lookup_landing_url(app)
        candidates = []
        if lookup_url:
            candidates.append(lookup_url)
        candidates.extend(
            [
                f"https://apps.apple.com/{self.args.apple_country}/app/{apple_slug(app.name)}/id{app.apple_id}",
                f"https://apps.apple.com/us/app/{apple_slug(app.name)}/id{app.apple_id}",
            ]
        )
        errors = []
        for candidate in candidates:
            try:
                response = self.request("GET", candidate)
                token = self.extract_token(response.text)
                if token:
                    return candidate, token, parse_country_from_url(candidate, self.args.apple_country)
                errors.append(f"no token: {candidate}")
            except Exception as exc:
                errors.append(f"{candidate}: {exc}")
        raise RuntimeError("Apple landing page/token unavailable; " + " | ".join(errors))

    def parse_review(self, job: Job, item: dict[str, Any], payload: dict[str, Any], country: str) -> dict[str, Any]:
        attrs = item.get("attributes", {}) if isinstance(item, dict) else {}
        dev_reply, dev_date = recursive_developer_response(attrs, item, payload)
        review_id = item.get("id") or attrs.get("id") or ""
        return source_record(
            job=job,
            review_id=review_id,
            review_date=value_from_dict(attrs, ("date", "createdDate")),
            rating=value_from_dict(attrs, ("rating", "score")),
            review_title=value_from_dict(attrs, ("title", "headline")),
            review_text=value_from_dict(attrs, ("review", "body", "content", "text")),
            developer_reply=dev_reply,
            developer_reply_date=dev_date,
            app_version=value_from_dict(attrs, ("appVersion", "version")),
            thumbs_up_count=value_from_dict(attrs, ("helpfulCount", "thumbsUpCount")),
            is_edited=value_from_dict(attrs, ("isEdited",)),
            fetch_locale=country,
            source_url=f"https://apps.apple.com/{country}/app/id{job.app.apple_id}?see-all=reviews",
        )

    def api_reviews(self, job: Job, raw_path: Path, existing_keys: set[str], state: dict[str, Any]) -> tuple[int, int, int, list[str], list[str]]:
        landing_url, token, country = self.landing_and_token(job.app)
        state["landing_url"] = landing_url
        state["apple_country_used"] = country
        api_url = f"https://amp-api.apps.apple.com/v1/catalog/{country}/apps/{job.app.apple_id}/reviews"
        headers = {
            "Accept": "application/json",
            "Authorization": f"bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": "https://apps.apple.com",
            "Referer": landing_url,
        }
        offset = 0
        seen_offsets: set[int] = set()
        pages = 0
        fetched = 0
        new_records = 0
        errors: list[str] = []
        warnings: list[str] = []
        while True:
            if args_max_pages := getattr(self.args, "max_pages", 0):
                if pages >= args_max_pages:
                    warnings.append(f"max-pages reached ({args_max_pages})")
                    break
            if offset in seen_offsets:
                warnings.append("Apple offset repeated; stopped safely")
                break
            seen_offsets.add(offset)
            params = {
                "l": self.args.apple_language,
                "offset": offset,
                "limit": 20,
                "platform": "web",
                "additionalPlatforms": "appletv,ipad,iphone,mac",
            }
            try:
                response = self.request("GET", api_url, headers=headers, params=params)
                payload = response.json()
            except Exception as exc:
                errors.append(f"offset {offset}: {exc}")
                break
            data = payload.get("data", []) if isinstance(payload, dict) else []
            if not data:
                break
            pages += 1
            fetched += len(data)
            normalized = [self.parse_review(job, item, payload, country) for item in data]
            fresh = []
            for item in normalized:
                key = record_key(item)
                if key not in existing_keys:
                    existing_keys.add(key)
                    fresh.append(item)
            new_records += append_raw(raw_path, fresh)
            next_link = payload.get("next") if isinstance(payload, dict) else None
            next_offset = None
            if next_link:
                try:
                    parsed = parse_qs(urlparse(str(next_link)).query)
                    if parsed.get("offset"):
                        next_offset = int(parsed["offset"][0])
                except (ValueError, TypeError):
                    next_offset = None
            if next_offset is None:
                next_offset = offset + len(data)
            if next_offset <= offset or len(data) < 20:
                break
            offset = next_offset
            if self.args.throttle_ms:
                time.sleep(self.args.throttle_ms / 1000.0)
        return pages, fetched, new_records, errors, warnings

    def rss_reviews(self, job: Job, raw_path: Path, existing_keys: set[str], state: dict[str, Any]) -> tuple[int, int, int, list[str], list[str]]:
        pages = 0
        fetched = 0
        new_records = 0
        errors: list[str] = []
        warnings = ["Apple API fallback used: RSS is public but may expose fewer historical pages than the API"]
        for page in range(1, self.args.apple_rss_pages + 1):
            url = f"https://itunes.apple.com/{self.args.apple_country}/rss/customerreviews/page={page}/id={job.app.apple_id}/sortby=mostrecent/json"
            try:
                response = self.request("GET", url)
                payload = response.json()
            except Exception as exc:
                errors.append(f"RSS page {page}: {exc}")
                break
            entries = (((payload or {}).get("feed") or {}).get("entry") or []) if isinstance(payload, dict) else []
            if isinstance(entries, dict):
                entries = [entries]
            review_entries = [entry for entry in entries if isinstance(entry, dict) and "im:rating" in entry]
            if not review_entries:
                break
            pages += 1
            fetched += len(review_entries)
            normalized = []
            for entry in review_entries:
                get_label = lambda key, default="": ((entry.get(key) or {}).get("label", default) if isinstance(entry.get(key), dict) else entry.get(key, default))
                normalized.append(
                    source_record(
                        job=job,
                        review_id=get_label("id"),
                        review_date=get_label("updated") or get_label("im:version"),
                        rating=get_label("im:rating"),
                        review_title=get_label("title"),
                        review_text=get_label("content"),
                        fetch_locale=self.args.apple_country,
                        source_url=f"https://apps.apple.com/{self.args.apple_country}/app/id{job.app.apple_id}?see-all=reviews",
                    )
                )
            fresh = []
            for item in normalized:
                key = record_key(item)
                if key not in existing_keys:
                    existing_keys.add(key)
                    fresh.append(item)
            new_records += append_raw(raw_path, fresh)
        return pages, fetched, new_records, errors, warnings


def run_apple_job(job: Job, args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    raw_path, state_path = job_paths(output_dir, job)
    state = base_state(job, raw_path)
    state["started_at"] = now_iso()
    existing_keys = read_raw_keys(raw_path)
    state["existing_raw_records"] = len(existing_keys)
    errors: list[str] = []
    warnings: list[str] = []
    pages = fetched = new_records = attempts = 0
    try:
        client = AppleClient(args)
        attempts = args.retries
        try:
            pages, fetched, new_records, api_errors, api_warnings = client.api_reviews(job, raw_path, existing_keys, state)
            errors.extend(api_errors)
            warnings.extend(api_warnings)
            state["method"] = "amp_api"
        except Exception as api_exc:
            warnings.append(f"API unavailable: {api_exc}")
            if fetched:
                errors.append(str(api_exc))
            else:
                pages, fetched, new_records, rss_errors, rss_warnings = client.rss_reviews(job, raw_path, existing_keys, state)
                errors.extend(rss_errors)
                warnings.extend(rss_warnings)
                state["method"] = "rss_fallback"
        if errors and fetched:
            status = "partial"
        elif errors:
            status = "failed"
        elif fetched == 0:
            status = "success_empty"
            warnings.append(
                "No reviews returned; verify the store ID/availability and retry this job"
            )
        else:
            status = "success"
    except Exception as exc:
        errors.append(f"fatal: {type(exc).__name__}: {exc}")
        status = "failed"
        LOGGER.error("%s failed: %s", job.key, traceback.format_exc())
    state.update(
        {
            "status": status,
            "finished_at": now_iso(),
            "attempts": attempts,
            "pages": pages,
            "fetched_records": fetched,
            "new_raw_records": new_records,
            "errors": errors,
            "warnings": warnings,
        }
    )
    write_job_state(state_path, state)
    LOGGER.info("%s: %s; method=%s; fetched=%s; new raw=%s", job.key, status, state.get("method", ""), fetched, new_records)
    return state


def run_job(job: Job, args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    if job.platform == "google_play":
        return run_google_job(job, args, output_dir)
    return run_apple_job(job, args, output_dir)


def merge_rows(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = dict(old)
    for field in CLEAN_COLUMNS:
        if field == "fetch_locale":
            values = []
            for value in (old.get(field, ""), new.get(field, "")):
                values.extend([part.strip() for part in str(value or "").split(",") if part.strip()])
            merged[field] = ",".join(dict.fromkeys(values))
            continue
        previous = merged.get(field, "")
        candidate = new.get(field, "")
        if previous in (None, "") and candidate not in (None, ""):
            merged[field] = candidate
        elif field in {"review_text", "developer_reply"} and len(str(candidate or "")) > len(str(previous or "")):
            merged[field] = candidate
        elif field == "thumbs_up_count":
            try:
                if int(candidate) > int(previous):
                    merged[field] = candidate
            except (TypeError, ValueError):
                pass
    return merged


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    row = {field: record.get(field, "") for field in CLEAN_COLUMNS}
    row["review_id"] = normalize_text(row["review_id"])
    row["review_date"] = normalize_date(row["review_date"])
    row["developer_reply_date"] = normalize_date(row["developer_reply_date"])
    row["review_title"] = normalize_text(row["review_title"])
    row["review_text"] = normalize_text(row["review_text"])
    row["developer_reply"] = normalize_text(row["developer_reply"])
    row["app_version"] = normalize_text(row["app_version"])
    row["source_url"] = normalize_text(row["source_url"])
    row["fetch_locale"] = normalize_text(row["fetch_locale"])
    rating = row.get("rating", "")
    try:
        rating_number = int(float(rating))
        row["rating"] = rating_number if 1 <= rating_number <= 5 else ""
    except (TypeError, ValueError):
        row["rating"] = ""
    try:
        row["thumbs_up_count"] = int(float(row.get("thumbs_up_count", "")))
    except (TypeError, ValueError):
        row["thumbs_up_count"] = ""
    edited = row.get("is_edited", "")
    if isinstance(edited, bool):
        row["is_edited"] = str(edited).lower()
    elif edited not in (None, ""):
        row["is_edited"] = normalize_text(edited)
    else:
        row["is_edited"] = ""
    row["fetched_at"] = normalize_date(row["fetched_at"])
    return row


def clean_raw_file(raw_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_count = 0
    parse_errors = 0
    duplicate_count = 0
    empty_text_count = 0
    developer_reply_count = 0
    invalid_rating_count = 0
    deduped: dict[str, dict[str, Any]] = {}
    if raw_path.exists():
        with raw_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                raw_count += 1
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("raw line is not an object")
                except (json.JSONDecodeError, ValueError):
                    parse_errors += 1
                    continue
                rating_before = record.get("rating", "")
                try:
                    rating_number = int(float(rating_before))
                    if not 1 <= rating_number <= 5:
                        invalid_rating_count += 1
                except (TypeError, ValueError):
                    if rating_before not in (None, ""):
                        invalid_rating_count += 1
                row = clean_record(record)
                if not row["review_text"]:
                    empty_text_count += 1
                if row["developer_reply"]:
                    developer_reply_count += 1
                key = record_key(row)
                if key in deduped:
                    duplicate_count += 1
                    deduped[key] = merge_rows(deduped[key], row)
                else:
                    deduped[key] = row
    rows = list(deduped.values())
    rows.sort(key=lambda item: item.get("review_date", ""), reverse=True)
    summary = {
        "raw_records": raw_count,
        "cleaned_records": len(rows),
        "duplicate_records_merged": duplicate_count,
        "parse_errors": parse_errors,
        "empty_review_text_rows": empty_text_count,
        "developer_reply_rows": developer_reply_count,
        "invalid_rating_values": invalid_rating_count,
    }
    return rows, summary


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] = CLEAN_COLUMNS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def state_for_job(output_dir: Path, job: Job) -> dict[str, Any]:
    _, state_path = job_paths(output_dir, job)
    return read_json(state_path, base_state(job, job_paths(output_dir, job)[0]))


def clean_all(output_dir: Path, jobs: list[Job], input_path: Path, args: argparse.Namespace, input_issues: list[str]) -> dict[str, Any]:
    cleaned_dir = output_dir / "cleaned"
    reports_dir = output_dir / "reports"
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    all_rows: dict[str, dict[str, Any]] = {}
    csv_files: list[str] = []

    for job in jobs:
        raw_path, state_path = job_paths(output_dir, job)
        rows, details = clean_raw_file(raw_path)
        cleaned_path = cleaned_dir / f"{job.key}.csv"
        write_csv(cleaned_path, rows)
        csv_files.append(str(cleaned_path.relative_to(output_dir)))
        for row in rows:
            key = record_key(row)
            if key in all_rows:
                all_rows[key] = merge_rows(all_rows[key], row)
            else:
                all_rows[key] = row
        state = read_json(state_path, {})
        summary = {
            "job_key": job.key,
            "platform": job.platform,
            "app_name": job.app.name,
            "tier": job.app.tier,
            "app_id": job.app_id,
            "status": state.get("status", "no_scrape_state" if not raw_path.exists() else "unknown"),
            "method": state.get("method", ""),
            "raw_file": str(raw_path.relative_to(output_dir)) if raw_path.exists() else "",
            "cleaned_file": str(cleaned_path.relative_to(output_dir)),
            "pages": state.get("pages", 0),
            "attempts": state.get("attempts", 0),
            "fetched_records": state.get("fetched_records", 0),
            "new_raw_records": state.get("new_raw_records", 0),
            "errors": " | ".join(str(x) for x in state.get("errors", [])),
            "warnings": " | ".join(str(x) for x in state.get("warnings", [])),
            **details,
        }
        summaries.append(summary)

    all_rows_list = list(all_rows.values())
    all_rows_list.sort(key=lambda item: item.get("review_date", ""), reverse=True)
    all_path = cleaned_dir / "ALL_REVIEWS.csv"
    write_csv(all_path, all_rows_list)
    csv_files.append(str(all_path.relative_to(output_dir)))

    summary_columns = [
        "job_key", "platform", "app_name", "tier", "app_id", "status", "method", "raw_file", "cleaned_file",
        "pages", "attempts", "fetched_records", "new_raw_records", "raw_records", "cleaned_records",
        "duplicate_records_merged", "parse_errors", "empty_review_text_rows", "developer_reply_rows",
        "invalid_rating_values", "errors", "warnings",
    ]
    write_csv(reports_dir / "cleaning_summary.csv", summaries, summary_columns)

    total = {key: sum(int(item.get(key, 0) or 0) for item in summaries) for key in (
        "raw_records", "cleaned_records", "duplicate_records_merged", "parse_errors", "empty_review_text_rows", "developer_reply_rows", "invalid_rating_values"
    )}
    status_counts: dict[str, int] = {}
    for item in summaries:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    retryable = [item for item in summaries if item["status"] in {"failed", "partial", "success_empty"}]
    markdown_lines = [
        "# IMOTION review scraping and cleaning summary",
        "",
        f"Generated: `{now_iso()}`",
        f"Input workbook: `{input_path}`",
        f"Apps detected: **{len({job.app.slug for job in jobs})}**; review jobs: **{len(jobs)}**",
        "",
        "## What was retained",
        "",
        "The cleaned CSVs retain: platform, app identity/tier, stable review ID, review date, rating, title, review text, developer reply/date when exposed by the store, app version, helpfulness count, edit flag, locale, source URL, and fetch timestamp.",
        "",
        "Reviewer display names, profile/avatar URLs, and other presentation-only fields were intentionally omitted. This is column pruning, not silent row deletion.",
        "",
        "## Row-retention rules",
        "",
        "- Exact duplicate reviews are merged by platform + app ID + review ID. If an ID is missing, a deterministic hash of the review fields is used.",
        "- Rating-only reviews are retained even when review text is blank.",
        "- Empty review text is reported in `empty_review_text_rows`; it is not discarded.",
        "- Malformed raw lines are reported in `parse_errors` and remain in the raw JSONL file for inspection.",
        "- When the same review is seen in more than one locale, non-empty text/replies are merged and the locales are joined in `fetch_locale`.",
        "",
        "## Per-job results",
        "",
        "| Job | Status | Raw rows | Clean rows | Duplicates merged | Empty text | Dev replies | CSV |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in summaries:
        markdown_lines.append(
            f"| {item['job_key']} | {item['status']} | {item['raw_records']} | {item['cleaned_records']} | {item['duplicate_records_merged']} | {item['empty_review_text_rows']} | {item['developer_reply_rows']} | `{item['cleaned_file']}` |"
        )
    markdown_lines.extend(
        [
            "",
            "## Totals",
            "",
            f"- Raw normalized rows read: **{total['raw_records']}**",
            f"- Cleaned unique rows: **{total['cleaned_records']}**",
            f"- Duplicate rows merged: **{total['duplicate_records_merged']}**",
            f"- Parse errors: **{total['parse_errors']}**",
            f"- Rows with blank review text retained: **{total['empty_review_text_rows']}**",
            f"- Rows with a developer reply: **{total['developer_reply_rows']}**",
            f"- Invalid rating values blanked (row retained): **{total['invalid_rating_values']}**",
            f"- Job statuses: `{json.dumps(status_counts, ensure_ascii=False)}`",
            "",
            "## Retry queue",
            "",
        ]
    )
    if retryable:
        markdown_lines.append(
            "The following jobs were failed, partial, or empty and are eligible for `run_imotion_reviews.bat retry`:"
        )
        markdown_lines.append("")
        for item in retryable:
            markdown_lines.append(f"- `{item['job_key']}`: {item['status']}; {item['errors'] or item['warnings']}")
    else:
        markdown_lines.append("No failed, partial, or empty jobs were recorded.")
    if input_issues:
        markdown_lines.extend(["", "## Input workbook notes", ""])
        markdown_lines.extend(f"- {issue}" for issue in input_issues)
    (reports_dir / "cleaning_summary.md").write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")

    manifest = {
        "generated_at": now_iso(),
        "input_workbook": str(input_path),
        "apps_detected": [asdict(app) for app in sorted({job.app for job in jobs}, key=lambda item: item.slug)],
        "settings": {key: str(value) for key, value in vars(args).items()},
        "csv_files": csv_files,
        "summary_csv": str((reports_dir / "cleaning_summary.csv").relative_to(output_dir)),
        "summary_markdown": str((reports_dir / "cleaning_summary.md").relative_to(output_dir)),
        "totals": total,
        "status_counts": status_counts,
    }
    write_json_atomic(reports_dir / "run_manifest.json", manifest)
    LOGGER.info("Cleaning complete: %s unique rows across %s CSV files", len(all_rows_list), len(csv_files))
    return {"summaries": summaries, "csv_files": csv_files, "totals": total}


def plan(apps: list[AppRecord], args: argparse.Namespace) -> None:
    print(f"Apps detected: {len(apps)}")
    for app in apps:
        print(f"- {app.tier}: {app.name} | Google={app.google_id or '-'} | Apple={app.apple_id or '-'}")
    jobs = [Job(app, platform) for app in apps for platform, present in (("google_play", bool(app.google_id)), ("apple_app_store", bool(app.apple_id))) if present]
    print(f"Jobs: {len(jobs)} ({args.workers} workers requested)")
    for job in jobs:
        print(f"  {job.key}")


def run_scrape(apps: list[AppRecord], args: argparse.Namespace, output_dir: Path) -> list[dict[str, Any]]:
    jobs = [
        Job(app, platform)
        for app in apps
        for platform, present in (("google_play", bool(app.google_id)), ("apple_app_store", bool(app.apple_id)))
        if present
    ]
    selected: list[Job] = []
    for job in jobs:
        state = state_for_job(output_dir, job)
        status = state.get("status")
        previous_app_id = normalize_id(state.get("app_id"))
        id_changed = bool(previous_app_id and previous_app_id != job.app_id)
        if id_changed:
            LOGGER.info(
                "%s: store ID changed from %s to %s; forcing a fresh scrape",
                job.key,
                previous_app_id,
                job.app_id,
            )
        # Empty responses are retryable too: a transient store response, locale
        # mismatch, or stale app ID can otherwise be mistaken for a completed job.
        if args.retry_failed and not id_changed and status not in {"failed", "partial", "success_empty"}:
            continue
        # A retry request is explicit: do not let normal resume logic skip a
        # previously empty job selected above.
        if (
            args.resume
            and not args.refresh
            and not args.retry_failed
            and not id_changed
            and status in {"success", "success_empty"}
            and job_paths(output_dir, job)[0].exists()
        ):
            LOGGER.info("%s: resume mode skipped completed job", job.key)
            continue
        selected.append(job)
    if not selected:
        LOGGER.info("No scrape jobs selected; cleaning existing raw snapshots")
        return []
    results: list[dict[str, Any]] = []
    workers = max(1, min(args.workers, len(selected)))
    LOGGER.info("Starting %s jobs with %s workers", len(selected), workers)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scrape") as pool:
        futures = {pool.submit(run_job, job, args, output_dir): job for job in selected}
        for future in as_completed(futures):
            job = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                LOGGER.error("Unhandled job error %s: %s", job.key, exc)
                results.append({"job_key": job.key, "status": "failed", "errors": [str(exc)]})
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scrape and clean public Google Play and Apple App Store reviews for IMOTION.")
    parser.add_argument("--input", type=Path, default=Path("ID App for IMOTION.xlsx"), help="Input workbook path")
    parser.add_argument("--output", type=Path, default=Path("output"), help="Output directory")
    parser.add_argument("--workers", type=int, default=8, help="Parallel app/platform jobs (default: 8)")
    parser.add_argument("--retries", type=int, default=5, help="Attempts per page/request (default: 5)")
    parser.add_argument("--retry-wait", type=float, default=2.0, help="Initial exponential retry wait in seconds")
    parser.add_argument("--timeout", type=float, default=45.0, help="Read timeout in seconds")
    parser.add_argument("--connect-timeout", type=float, default=15.0, help="Connection timeout in seconds")
    parser.add_argument("--google-page-size", type=int, default=4500, help="Google page size, capped at 4500")
    parser.add_argument("--google-lang", default="id", help="Default Google Play language")
    parser.add_argument("--google-country", default="id", help="Default Google Play country")
    parser.add_argument("--google-locales", default="", help="Comma-separated lang:country pairs, e.g. id:id,en:us")
    parser.add_argument("--apple-country", default="id", help="Apple storefront country")
    parser.add_argument("--apple-language", default="en-GB", help="Apple API language parameter")
    parser.add_argument("--apple-rss-pages", type=int, default=50, help="RSS fallback page ceiling")
    parser.add_argument("--max-pages", type=int, default=0, help="Optional per-job page ceiling; 0 means all available")
    parser.add_argument("--throttle-ms", type=int, default=0, help="Optional delay between pages")
    parser.add_argument("--user-agent", default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36", help=argparse.SUPPRESS)
    parser.add_argument("--refresh", action="store_true", help="Re-scrape jobs marked successful instead of resuming")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Run only failed, partial, or empty jobs from the previous run",
    )
    parser.add_argument("--clean-only", action="store_true", help="Skip scraping and rebuild cleaned CSVs from raw JSONL")
    parser.add_argument("--plan", action="store_true", help="List detected apps/jobs without network access")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="Do not skip completed jobs")
    parser.set_defaults(resume=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.workers = max(1, args.workers)
    args.retries = max(1, args.retries)
    args.google_page_size = max(1, min(args.google_page_size, 4500))
    args.apple_rss_pages = max(1, args.apple_rss_pages)
    input_path = args.input.resolve()
    output_dir = args.output.resolve()
    if not input_path.exists():
        parser.error(f"Input workbook not found: {input_path}")
    apps, input_issues = load_apps(input_path)
    if not apps:
        parser.error("No app rows were detected in the workbook.")
    if args.plan:
        plan(apps, args)
        return 0
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(output_dir)
    LOGGER.info("Loaded %s apps from %s", len(apps), input_path)
    if input_issues:
        LOGGER.warning("Input notes: %s", " | ".join(input_issues))
    jobs = [
        Job(app, platform)
        for app in apps
        for platform, present in (("google_play", bool(app.google_id)), ("apple_app_store", bool(app.apple_id)))
        if present
    ]
    if not args.clean_only:
        run_scrape(apps, args, output_dir)
    clean_all(output_dir, jobs, input_path, args, input_issues)
    LOGGER.info("Finished. Read reports/cleaning_summary.md and reports/cleaning_summary.csv under %s", output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
