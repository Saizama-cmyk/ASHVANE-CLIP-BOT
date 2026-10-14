"""Read-only, bounded YouTube Analytics reports for the current authorized channel."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import re

import httpx

ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
ANALYTICS_MONETARY_SCOPE = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
VIDEO_FILTER_LIMIT = 500  # YouTube Analytics filters API ceiling
TOP_VIDEO_LIMIT = 200  # channel top-video report maxResults ceiling
FIELDS = {"views": "report_views", "engagedViews": "engaged_views",
          "averageViewDuration": "average_view_duration_s", "averageViewPercentage": "average_view_percentage",
          "subscribersGained": "subscribers_gained"}


async def collect_outcomes(publisher, remote_ids):
    cfg = publisher.settings.analytics
    if not cfg.youtube_outcomes_enabled:
        return {"status": "disabled", "by_id": {}}
    token_record = publisher.tokens.get("youtube")
    scopes = set(str(token_record.get("scope", "")).split())
    if scopes and not scopes.intersection({ANALYTICS_SCOPE, ANALYTICS_MONETARY_SCOPE}):
        return {"status": "permission_required", "by_id": {}}
    ids = list(dict.fromkeys(remote_ids))[:cfg.youtube_library_limit]
    if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in ids):
        raise ValueError("Invalid YouTube outcome identifier")
    if not ids:
        return {"status": "no_posts", "by_id": {}}
    today = datetime.now(timezone.utc).date()
    end = today - timedelta(days=cfg.youtube_reporting_lag_days)
    start = end - timedelta(days=cfg.lookback_days - 1)
    window = {"requested_start_date": start.isoformat(), "requested_end_date": end.isoformat()}
    token = await publisher.oauth.access_token("youtube")
    output = {}
    batch_size = min(cfg.youtube_library_limit, VIDEO_FILTER_LIMIT, TOP_VIDEO_LIMIT)
    for offset in range(0, len(ids), batch_size):
        batch = ids[offset:offset + batch_size]
        params = {"ids": "channel==MINE", "startDate": window["requested_start_date"],
                  "endDate": window["requested_end_date"], "dimensions": "video",
                  "metrics": ",".join(FIELDS), "filters": "video==" + ",".join(batch),
                  "sort": "-views", "maxResults": len(batch)}
        async with publisher.http.stream("GET", ANALYTICS_URL, params=params,
                headers={"Authorization": "Bearer " + token}, follow_redirects=False,
                timeout=publisher.settings.discovery.http_timeout_s) as response:
            if response.status_code in (401, 403):
                return {"status": "permission_or_api_access_required", "by_id": {}, **window}
            if response.status_code != 200:
                return {"status": "report_error", "by_id": {}, **window}
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > cfg.youtube_response_max_bytes:
                    raise ValueError("YouTube outcome response exceeds its configured limit")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid YouTube Analytics report")
        headers, rows = data.get("columnHeaders"), data.get("rows", [])
        expected = ["video", *FIELDS]
        if not isinstance(headers, list) or [row.get("name") if isinstance(row, dict) else None for row in headers] != expected:
            raise ValueError("Unexpected YouTube outcome columns")
        if not isinstance(rows, list) or len(rows) > len(batch):
            raise ValueError("Excessive YouTube outcome rows")
        for row in rows:
            if not isinstance(row, list) or len(row) != len(expected) or row[0] not in batch or row[0] in output:
                raise ValueError("Unrequested or duplicate YouTube outcome row")
            values = row[1:]
            if any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in values):
                raise ValueError("Invalid YouTube outcome metric")
            # Percentages above 100 are valid for rewatched Shorts.
            output[row[0]] = {**dict(zip(FIELDS.values(), values)), **window}
    return {"status": "ready" if output else "no_data", "by_id": output, **window,
            "truncated": len(remote_ids) > len(ids)}
