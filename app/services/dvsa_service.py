from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from app.config.runtime import get_runtime_config
from app.config.workbook_schema import LOCAL_DB
from app.db.init_db import checkpoint_wal, connect_sqlite


class DVSAServiceError(ValueError):
    pass


@dataclass(frozen=True)
class DVSAResult:
    stock_id: str
    plate: str
    mot_expiry: str
    mot_status: str
    mot_last_result: str
    mot_last_checked: str
    advisories: list[str]
    raw_payload: dict[str, Any]


_TOKEN_CACHE: dict[str, object] = {
    "access_token": "",
    "expires_at": datetime(1970, 1, 1, tzinfo=UTC),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _require_dvsa_config() -> None:
    if not get_runtime_config().dvsa_enabled:
        raise DVSAServiceError(
            "DVSA integration is not configured. Add DVSA credentials to .env."
        )


def _read_json_response(response: Any) -> Any:
    charset = response.headers.get_content_charset() or "utf-8"
    payload = response.read().decode(charset)
    return json.loads(payload) if payload else {}


def _get_access_token() -> str:
    config = get_runtime_config()
    _require_dvsa_config()

    cached_token = str(_TOKEN_CACHE.get("access_token") or "")
    expires_at = _TOKEN_CACHE.get("expires_at")
    if cached_token and isinstance(expires_at, datetime):
        if expires_at > _utcnow() + timedelta(seconds=30):
            return cached_token

    body = parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": config.dvsa_client_id,
            "client_secret": config.dvsa_client_secret,
            "scope": config.dvsa_scope,
        }
    ).encode("utf-8")
    token_request = request.Request(
        config.dvsa_token_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with request.urlopen(token_request, timeout=20) as response:
            token_payload = _read_json_response(response)
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise DVSAServiceError(
            f"DVSA token request failed with HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except error.URLError as exc:
        raise DVSAServiceError(f"DVSA token request failed: {exc.reason}") from exc

    access_token = str(token_payload.get("access_token") or "")
    if not access_token:
        raise DVSAServiceError("DVSA token response did not include an access_token.")

    expires_in = int(token_payload.get("expires_in") or 3600)
    _TOKEN_CACHE["access_token"] = access_token
    _TOKEN_CACHE["expires_at"] = _utcnow() + timedelta(
        seconds=max(60, expires_in - 60)
    )
    return access_token


def _candidate_registration_urls(registration: str) -> list[str]:
    config = get_runtime_config()
    encoded_registration = parse.quote(registration)
    base_url = config.dvsa_api_base_url.rstrip("/")
    return [
        base_url + path.format(registration=encoded_registration)
        for path in config.dvsa_registration_paths
    ]


def _normalize_vehicle_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                return item
    if isinstance(payload, dict):
        if isinstance(payload.get("vehicle"), dict):
            return dict(payload["vehicle"])
        return payload
    return {}


def _parse_iso_datetime(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                continue
    return None


def _best_test_result(test_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not test_results:
        return None

    def _sort_key(item: dict[str, Any]) -> float:
        parsed = _parse_iso_datetime(
            str(
                item.get("completedDate")
                or item.get("completedDateTime")
                or item.get("testDate")
                or ""
            )
        )
        return parsed.timestamp() if parsed else 0.0

    return sorted(
        test_results,
        key=_sort_key,
        reverse=True,
    )[0]


def _extract_advisories(best_result: dict[str, Any] | None) -> list[str]:
    if not best_result:
        return []
    candidates = best_result.get("rfrAndComments") or best_result.get("defects") or []
    advisories: list[str] = []
    if isinstance(candidates, list):
        for item in candidates:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("type") or item.get("severity") or "").lower()
            text = str(item.get("text") or item.get("comment") or "").strip()
            if text and ("advis" in kind or not kind):
                advisories.append(text)
    return advisories


def _coerce_mot_result_label(best_result: dict[str, Any] | None) -> str:
    if not best_result:
        return ""
    return (
        str(best_result.get("testResult") or "")
        or str(best_result.get("result") or "")
        or str(best_result.get("testOutcome") or "")
    ).strip()


def _coerce_mot_expiry(
    vehicle_payload: dict[str, Any], best_result: dict[str, Any] | None
) -> str:
    direct_candidates = [
        vehicle_payload.get("motExpiryDate"),
        vehicle_payload.get("expiryDate"),
        vehicle_payload.get("motTestExpiryDate"),
    ]
    if best_result:
        direct_candidates.extend(
            [
                best_result.get("expiryDate"),
                best_result.get("motExpiryDate"),
                best_result.get("expiryDateTime"),
            ]
        )
    for candidate in direct_candidates:
        parsed = _parse_iso_datetime(str(candidate or ""))
        if parsed:
            return parsed.strftime("%Y-%m-%d")
    return ""


def _coerce_mot_status(
    vehicle_payload: dict[str, Any], best_result: dict[str, Any] | None
) -> str:
    direct_status = (
        str(vehicle_payload.get("motStatus") or "")
        or str(vehicle_payload.get("status") or "")
        or str(vehicle_payload.get("motTestStatus") or "")
    ).strip()
    if direct_status:
        return direct_status
    result_label = _coerce_mot_result_label(best_result)
    if result_label:
        return result_label
    if _coerce_mot_expiry(vehicle_payload, best_result):
        return "Valid"
    return "Check Needed"


def _fetch_vehicle_mot_payload(registration: str) -> dict[str, Any]:
    token = _get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-API-Key": get_runtime_config().dvsa_api_key,
        "Accept": "application/json",
    }

    last_error: str | None = None
    candidate_urls = _candidate_registration_urls(registration)
    for candidate_url in candidate_urls:
        mot_request = request.Request(candidate_url, headers=headers, method="GET")
        try:
            with request.urlopen(mot_request, timeout=20) as response:
                return _normalize_vehicle_payload(_read_json_response(response))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 403 and (
                "Incapsula" in detail
                or "incident ID" in detail
                or "_Incapsula_Resource" in detail
            ):
                raise DVSAServiceError(
                    "DVSA API access is being blocked for this IP by Imperva/Incapsula. "
                    "Use the GOV.UK MOT history fallback or run from a network the DVSA API accepts."
                ) from exc
            last_error = f"HTTP {exc.code}: {detail or exc.reason}"
            if exc.code in {400, 404}:
                continue
            raise DVSAServiceError(
                f"DVSA MOT lookup failed for {registration}: HTTP {exc.code}"
            ) from exc
        except error.URLError as exc:
            raise DVSAServiceError(
                f"DVSA MOT lookup failed for {registration}: {exc.reason}"
            ) from exc

    raise DVSAServiceError(
        f"DVSA MOT lookup failed for {registration}. Tried {len(candidate_urls)} registration endpoints. Last error: {last_error or 'no response'}"
    )


def _resolve_vehicle(
    connection: Any, *, stock_id: str | None = None, plate: str | None = None
) -> dict[str, Any]:
    if stock_id:
        row = connection.execute(
            "SELECT id, stock_id, plate FROM vehicles WHERE stock_id = ? LIMIT 1",
            (stock_id,),
        ).fetchone()
        if row:
            return dict(row)
    if plate:
        normalized_plate = "".join(ch for ch in plate.upper() if ch.isalnum())
        row = connection.execute(
            """
            SELECT id, stock_id, plate
            FROM vehicles
            WHERE plate_normalized = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (normalized_plate,),
        ).fetchone()
        if row:
            return dict(row)
    raise DVSAServiceError("Vehicle not found for MOT lookup.")


def check_vehicle_mot(
    *,
    stock_id: str | None = None,
    plate: str | None = None,
    db_path: Path = LOCAL_DB,
) -> DVSAResult:
    connection = connect_sqlite(db_path)
    try:
        vehicle = _resolve_vehicle(connection, stock_id=stock_id, plate=plate)
        registration = str(vehicle.get("plate") or "").strip()
        if not registration:
            raise DVSAServiceError("Vehicle does not have a registration to check.")

        vehicle_payload = _fetch_vehicle_mot_payload(registration)
        test_results = (
            vehicle_payload.get("motTests")
            or vehicle_payload.get("motTestHistory")
            or vehicle_payload.get("tests")
            or []
        )
        best_result = _best_test_result(test_results if isinstance(test_results, list) else [])
        advisories = _extract_advisories(best_result)
        mot_expiry = _coerce_mot_expiry(vehicle_payload, best_result)
        mot_status = _coerce_mot_status(vehicle_payload, best_result)
        mot_last_result = _coerce_mot_result_label(best_result)
        mot_last_checked = _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        connection.execute(
            """
            UPDATE vehicles
            SET mot_expiry = ?,
                mot_status = ?,
                mot_last_result = ?,
                mot_last_checked = ?,
                mot_advisories_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                mot_expiry or None,
                mot_status or None,
                mot_last_result or None,
                mot_last_checked,
                json.dumps(advisories),
                vehicle["id"],
            ),
        )
        connection.commit()
    finally:
        connection.close()

    checkpoint_wal(db_path)

    return DVSAResult(
        stock_id=str(vehicle["stock_id"]),
        plate=registration,
        mot_expiry=mot_expiry,
        mot_status=mot_status,
        mot_last_result=mot_last_result,
        mot_last_checked=mot_last_checked,
        advisories=advisories,
        raw_payload=vehicle_payload,
    )


def check_all_vehicle_mot(db_path: Path = LOCAL_DB) -> dict[str, Any]:
    connection = connect_sqlite(db_path)
    try:
        rows = connection.execute(
            """
            SELECT stock_id, plate
            FROM vehicles
            WHERE COALESCE(status, 'In Stock') != 'Sold'
              AND COALESCE(plate, '') != ''
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()
    finally:
        connection.close()

    checked: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for row in rows:
        try:
            result = check_vehicle_mot(stock_id=str(row["stock_id"]), db_path=db_path)
            checked.append(
                {
                    "stock_id": result.stock_id,
                    "plate": result.plate,
                    "mot_expiry": result.mot_expiry,
                    "mot_status": result.mot_status,
                }
            )
        except DVSAServiceError as exc:
            errors.append(
                {
                    "stock_id": str(row["stock_id"]),
                    "plate": str(row["plate"] or ""),
                    "error": str(exc),
                }
            )
    return {"checked": checked, "errors": errors, "count": len(checked)}
