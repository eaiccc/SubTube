#!/usr/bin/env python3
"""Dependency-free readback for issue #1725 URL normalization/preflight."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parent
POLICY_PATH = ROOT / "policy.json"
POLICY_SCHEMA_PATH = ROOT / "schemas" / "policy.schema.json"
FIXTURE_SCHEMA_PATH = ROOT / "schemas" / "fixtures.schema.json"
FIXTURE_DIR = ROOT / "fixtures"
RELEASE_A_VERIFIER_PATH = ROOT.parent / "release-a" / "verify_contract.py"
PIPELINE_VERSION = "release-a-caption-v1"


class ContractFailure(AssertionError):
    pass


def fail(message: str) -> None:
    raise ContractFailure(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"{path}: cannot read valid JSON: {error}")
    if not isinstance(value, dict):
        fail(f"{path}: root must be an object")
    return value


def load_release_a_verifier() -> Any:
    spec = importlib.util.spec_from_file_location("release_a_contract", RELEASE_A_VERIFIER_PATH)
    if spec is None or spec.loader is None:
        fail(f"cannot load frozen verifier: {RELEASE_A_VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE_A = load_release_a_verifier()


def assert_schema(instance: Any, schema_document: dict[str, Any], context: str) -> None:
    errors = RELEASE_A.validate(instance, schema_document, schema_document)
    if errors:
        fail(f"{context}: schema failed:\n  " + "\n  ".join(errors))


def source_openapi(policy: dict[str, Any]) -> dict[str, Any]:
    path = (ROOT / policy["sourceContract"]).resolve()
    expected = (ROOT.parent / "release-a" / "openapi.json").resolve()
    if path != expected:
        fail(f"policy must reference the frozen Release A OpenAPI: {path}")
    return load_json(path)


EXPECTED_REQUEST_ORDER = [
    "idempotency_lookup",
    "request_schema_and_target_gate",
    "rate_quota_concurrency_gate",
    "url_normalization",
    "source_metadata_probe",
    "visibility_gate",
    "live_gate",
    "embeddability_gate",
    "duration_gate",
    "language_gate",
    "caption_availability_and_parseability_gate",
    "dedupe_lookup",
    "atomic_job_create",
]

EXPECTED_PREFLIGHT = {
    "maximumDurationSeconds": 900,
    "sourceLanguage": "en",
    "captionLanguage": "en",
    "gateOrder": ["visibility", "live", "embeddability", "duration", "language", "captions"],
    "errors": {
        "visibility": "video_private",
        "live": "video_live",
        "embeddability": "video_not_embeddable",
        "duration": "video_too_long",
        "language": "non_english",
        "captions": "captions_unavailable",
    },
}
EXPECTED_PROVIDER_ENTRY_GUARDS = {
    "quota": {
        "errorCode": "quota_exceeded",
        "wireShape": "APIError",
        "jobMayExist": False,
        "mustRunBeforeSourceProbe": True,
    },
    "cost": {
        "errorCode": "cost_limit_exceeded",
        "wireShape": "ProcessingJob(status=failed)",
        "jobMayExist": True,
        "mustRunBeforeAsyncCaptionOrTranslationProvider": True,
        "thresholdEvidence": "NOT_RUN_D2",
    },
}
EXPECTED_REJECTION_EFFECTS = {
    "jobCreated": False,
    "jobIdReturned": False,
    "captionPipelineStarts": 0,
    "translationCalls": 0,
    "audioDownloads": 0,
    "sttCalls": 0,
}
EXPECTED_OPEN_DECISIONS = [
    {
        "id": "D2-A",
        "state": "OPEN",
        "decision": "caption/LLM provider, timeout, pipeline version release value, and per-job cost cap",
    },
    {
        "id": "D3-A",
        "state": "OPEN",
        "decision": "20-video Release A preflight/latency corpus and environment",
    },
    {
        "id": "UP-01",
        "state": "OPEN",
        "decision": "Whether mobile/music/embed/shorts URLs or non-HTTPS schemes become supported beyond the two PRD URL forms",
    },
    {
        "id": "UP-02",
        "state": "OPEN",
        "decision": "Concrete source metadata/caption adapter and authoritative English/caption-parseability signals",
    },
]


def check_policy(policy: dict[str, Any], policy_schema: dict[str, Any]) -> None:
    assert_schema(policy, policy_schema, "policy.json")
    normalization = policy["normalization"]
    expected_forms = [
        {"host": "youtube.com", "path": "/watch", "videoIdLocation": "query.v"},
        {"host": "www.youtube.com", "path": "/watch", "videoIdLocation": "query.v"},
        {"host": "youtu.be", "path": "/{videoId}", "videoIdLocation": "path.segment[0]"},
    ]
    if normalization["acceptedSchemes"] != ["https"]:
        fail("Release A URL parser must accept only the explicitly contracted HTTPS form")
    if normalization["acceptedForms"] != expected_forms:
        fail("accepted URL forms changed outside MVP-01")
    if normalization["videoIdPattern"] != r"^[A-Za-z0-9_-]{11}$":
        fail("Video ID syntax must remain the #1725 11-character contract")
    if normalization["canonicalUrlTemplate"] != "https://www.youtube.com/watch?v={videoId}":
        fail("canonical URL template changed")
    for key in (
        "stripTrackingQuery",
        "stripFragment",
        "rejectAmbiguousVideoIds",
        "idempotencyFingerprintUsesRawBody",
    ):
        if normalization[key] is not True:
            fail(f"normalization invariant {key} must be true")
    if policy["requestOrder"] != EXPECTED_REQUEST_ORDER:
        fail("request gate order changed")
    if policy["preflight"] != EXPECTED_PREFLIGHT:
        fail(f"preflight fields/mapping changed: {policy['preflight']!r}")
    if policy["providerEntryGuards"] != EXPECTED_PROVIDER_ENTRY_GUARDS:
        fail(f"provider-entry guard fields changed: {policy['providerEntryGuards']!r}")
    if policy["rejectionEffects"] != EXPECTED_REJECTION_EFFECTS:
        fail(f"preflight rejection effects changed: {policy['rejectionEffects']!r}")
    if policy["handoff"]["dedupeKeyFields"] != [
        "videoId", "sourceLanguage", "targetLanguage", "pipelineVersion"
    ]:
        fail("dedupe handoff fields changed")
    if policy["handoff"]["pipelineVersionFixture"] != PIPELINE_VERSION:
        fail("preflight handoff pipeline identity drifted from #1705")
    if policy["openDecisions"] != EXPECTED_OPEN_DECISIONS:
        fail(f"open decision fields/state changed: {policy['openDecisions']!r}")


ERROR_EXPECTATIONS = {
    "invalid_url": (400, "parse.error.invalidURL", False, "preflight"),
    "unsupported_source": (422, "parse.error.unsupportedSource", False, "preflight"),
    "video_private": (422, "parse.error.privateVideo", False, "preflight"),
    "video_live": (422, "parse.error.liveVideo", False, "preflight"),
    "video_not_embeddable": (422, "parse.error.notEmbeddable", False, "preflight"),
    "video_too_long": (422, "parse.error.videoTooLong", False, "preflight"),
    "non_english": (422, "parse.error.nonEnglish", False, "preflight"),
    "captions_unavailable": (422, "parse.error.captionsUnavailable", False, "preflight"),
    "quota_exceeded": (429, "parse.error.quotaExceeded", False, "request"),
    "idempotency_conflict": (409, "parse.error.idempotencyConflict", False, "request"),
    "cost_limit_exceeded": (200, "parse.error.costLimitExceeded", False, "job"),
}


def check_release_a_compatibility(openapi: dict[str, Any]) -> None:
    if openapi.get("openapi") != "3.1.0":
        fail("frozen source contract is no longer OpenAPI 3.1.0")
    if "/v1/parse-jobs" not in openapi.get("paths", {}):
        fail("frozen source contract lacks POST /v1/parse-jobs")
    statuses = openapi["components"]["schemas"]["ProcessingStatus"]["enum"]
    if statuses != ["queued", "fetching_captions", "translating", "ready", "failed"]:
        fail("#1725 must not add or change Release A job statuses")
    if "transcribing" in json.dumps(openapi["components"]["schemas"]):
        fail("Release A source contract must exclude transcribing")
    request = openapi["components"]["schemas"]["ParseJobRequest"]
    if request["properties"]["targetLanguage"] != {"const": "zh-Hant-TW"}:
        fail("Release A target language changed")
    processing = openapi["components"]["schemas"]["ProcessingJob"]
    if processing["properties"]["duration"].get("maximum") != 900:
        fail("ProcessingJob duration maximum is not synchronized to 900 seconds")
    api_codes = set(openapi["components"]["schemas"]["APIErrorCode"]["enum"])
    job_codes = set(openapi["components"]["schemas"]["JobErrorCode"]["enum"])
    for code, expected in ERROR_EXPECTATIONS.items():
        mapping = openapi["x-error-contract"].get(code)
        if mapping is None:
            fail(f"frozen source contract lacks error mapping {code}")
        actual = (mapping["httpStatus"], mapping["messageKey"], mapping["retryable"], mapping["phase"])
        if actual != expected:
            fail(f"frozen mapping mismatch for {code}: {actual!r} != {expected!r}")
        if code == "cost_limit_exceeded":
            if code not in job_codes or code in api_codes:
                fail("cost_limit_exceeded must remain a job error, not a preflight APIError")
        elif code not in api_codes or code in job_codes:
            fail(f"{code} must remain an APIError code")


def error_result(code: str, openapi: dict[str, Any]) -> dict[str, Any]:
    mapping = openapi["x-error-contract"][code]
    return {
        "accepted": False,
        "httpStatus": mapping["httpStatus"],
        "errorCode": code,
        "errorMessageKey": mapping["messageKey"],
        "retryable": mapping["retryable"],
    }


def normalize_url(raw_url: Any, policy: dict[str, Any], openapi: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw_url, str) or not raw_url.strip():
        return error_result("invalid_url", openapi)
    candidate = raw_url.strip()
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return error_result("invalid_url", openapi)
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password or port is not None:
        return error_result("invalid_url", openapi)
    hostname = hostname.lower()
    accepted_hosts = {item["host"] for item in policy["normalization"]["acceptedForms"]}
    if hostname not in accepted_hosts:
        return error_result("unsupported_source", openapi)

    video_id: str | None = None
    if hostname in {"youtube.com", "www.youtube.com"}:
        if parsed.path != "/watch":
            return error_result("invalid_url", openapi)
        values = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
        if len(values) != 1:
            return error_result("invalid_url", openapi)
        video_id = values[0]
    elif hostname == "youtu.be":
        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) != 1:
            return error_result("invalid_url", openapi)
        video_id = segments[0]

    pattern = policy["normalization"]["videoIdPattern"]
    if video_id is None or re.fullmatch(pattern, video_id) is None:
        return error_result("invalid_url", openapi)
    canonical = policy["normalization"]["canonicalUrlTemplate"].replace("{videoId}", video_id)
    return {
        "accepted": True,
        "videoId": video_id,
        "canonicalUrl": canonical,
        "idempotencyFingerprintUrl": raw_url,
    }


ZERO_PIPELINE_EFFECTS = {
    "captionPipelineStarts": 0,
    "translationCalls": 0,
    "audioDownloads": 0,
    "sttCalls": 0,
}


def require_effects(effects: dict[str, Any], expected: dict[str, Any], context: str) -> None:
    for key, value in expected.items():
        if effects.get(key) != value:
            fail(f"{context}: expected effect {key}={value!r}, got {effects.get(key)!r}")


def check_api_error_response(response: dict[str, Any], openapi: dict[str, Any], context: str) -> None:
    if response["bodySchema"] != "APIError":
        fail(f"{context}: rejection must use APIError")
    RELEASE_A.assert_valid(response["body"], "APIError", openapi, context)
    body = response["body"]
    mapping = openapi["x-error-contract"][body["errorCode"]]
    actual = (response["status"], body["errorMessageKey"], body["retryable"])
    expected = (mapping["httpStatus"], mapping["messageKey"], mapping["retryable"])
    if actual != expected:
        fail(f"{context}: APIError mapping mismatch {actual!r} != {expected!r}")
    if "jobId" in body:
        fail(f"{context}: APIError must not contain jobId")


def check_normalization_case(case: dict[str, Any], policy: dict[str, Any], openapi: dict[str, Any]) -> None:
    context = case["case"]
    actual = normalize_url(case["input"].get("url"), policy, openapi)
    if actual != case["expected"]:
        fail(f"{context}: normalization {actual!r} != {case['expected']!r}")
    require_effects(case["expectedEffects"], ZERO_PIPELINE_EFFECTS, context)
    require_effects(
        case["expectedEffects"],
        {"jobCreated": False, "jobIdReturned": False, "sourceMetadataCalls": 0, "captionAvailabilityCalls": 0},
        context,
    )


def preflight_decision(facts: dict[str, Any]) -> str | None:
    if facts.get("visibility") != "public":
        return "video_private"
    if facts.get("isLive") is not False:
        return "video_live"
    if facts.get("embeddable") is not True:
        return "video_not_embeddable"
    duration = facts.get("durationSeconds")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0 or duration > 900:
        return "video_too_long"
    if facts.get("sourceLanguage") != "en":
        return "non_english"
    captions = facts.get("captions", {})
    if not (
        captions.get("available") is True
        and captions.get("parseable") is True
        and captions.get("language") == "en"
    ):
        return "captions_unavailable"
    return None


def captions_gate_reached(facts: dict[str, Any]) -> bool:
    without_captions = deepcopy(facts)
    without_captions["captions"] = {"available": True, "parseable": True, "language": "en"}
    return preflight_decision(without_captions) is None


def check_preflight_case(case: dict[str, Any], policy: dict[str, Any], openapi: dict[str, Any]) -> None:
    context = case["case"]
    normalized = normalize_url(case["input"].get("url"), policy, openapi)
    if normalized.get("accepted") is not True:
        fail(f"{context}: preflight fixture URL must normalize before source probes")
    facts = case["input"]["facts"]
    code = preflight_decision(facts)
    expected = case["expected"]
    effects = case["expectedEffects"]
    require_effects(effects, ZERO_PIPELINE_EFFECTS, context)
    require_effects(effects, {"sourceMetadataCalls": 1}, context)
    expected_caption_calls = 1 if captions_gate_reached(facts) else 0
    require_effects(effects, {"captionAvailabilityCalls": expected_caption_calls}, context)

    response = expected["response"]
    if code is None:
        if expected.get("accepted") is not True:
            fail(f"{context}: valid preflight facts must be accepted")
        if response["status"] != 202 or response["bodySchema"] != "ProcessingJob":
            fail(f"{context}: accepted new job must return HTTP 202 ProcessingJob")
        RELEASE_A.assert_valid(response["body"], "ProcessingJob", openapi, context)
        if response["body"]["videoId"] != normalized["videoId"]:
            fail(f"{context}: response videoId does not match normalization")
        if response["body"]["duration"] != facts["durationSeconds"]:
            fail(f"{context}: response duration does not match preflight facts")
        require_effects(effects, {"jobCreated": True, "jobIdReturned": True}, context)
    else:
        if expected.get("accepted") is not False:
            fail(f"{context}: rejected facts unexpectedly marked accepted")
        check_api_error_response(response, openapi, context)
        if response["body"]["errorCode"] != code:
            fail(f"{context}: expected precedence error {code!r}")
        require_effects(effects, {"jobCreated": False, "jobIdReturned": False}, context)


def request_fingerprint(body: dict[str, Any]) -> str:
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dedupe_key(video_id: str, policy: dict[str, Any]) -> str:
    handoff = policy["handoff"]
    return "|".join(
        [video_id, handoff["sourceLanguage"], handoff["targetLanguage"], handoff["pipelineVersionFixture"]]
    )


def assert_request(value: dict[str, Any], openapi: dict[str, Any], context: str) -> None:
    RELEASE_A.assert_valid(value["body"], "ParseJobRequest", openapi, context)
    try:
        uuid.UUID(value["idempotencyKey"])
    except (ValueError, TypeError):
        fail(f"{context}: invalid Idempotency-Key UUID")


def check_handoff_case(case: dict[str, Any], policy: dict[str, Any], openapi: dict[str, Any]) -> None:
    context = case["case"]
    first = case["input"]["first"]
    second = case["input"]["second"]
    assert_request(first, openapi, context + " first")
    assert_request(second, openapi, context + " second")
    first_normalized = normalize_url(first["body"]["url"], policy, openapi)
    second_normalized = normalize_url(second["body"]["url"], policy, openapi)
    if not first_normalized.get("accepted") or not second_normalized.get("accepted"):
        fail(f"{context}: handoff URLs must both normalize")
    same_key = first["idempotencyKey"] == second["idempotencyKey"]
    same_fingerprint = request_fingerprint(first["body"]) == request_fingerprint(second["body"])
    expected = case["expected"]
    effects = case["expectedEffects"]
    require_effects(effects, {"translationCalls": 0, "audioDownloads": 0, "sttCalls": 0}, context)

    if context == "different_keys_equivalent_urls_share_dedupe_key":
        if same_key or first_normalized["videoId"] != second_normalized["videoId"]:
            fail(f"{context}: requires different keys and equivalent normalized Video IDs")
        actual_key = dedupe_key(first_normalized["videoId"], policy)
        if expected != {
            "sameVideoId": first_normalized["videoId"],
            "sameDedupeKey": actual_key,
            "sameRequestFingerprint": same_fingerprint,
            "reuseInFlightOrReadyOwner": True,
        }:
            fail(f"{context}: dedupe handoff mismatch")
        require_effects(effects, {"activeOwnerMaximum": 1, "additionalJobCreated": False, "additionalCaptionPipelineStarts": 0}, context)
    elif context == "same_key_same_raw_body_is_exact_replay":
        if not same_key or not same_fingerprint:
            fail(f"{context}: exact replay requires the same key and canonical request body")
        if expected != {
            "outcome": "exact_replay",
            "minimumRetentionHours": 24,
            "normalizationRunsOnSecondRequest": 0,
            "preflightRunsOnSecondRequest": 0,
        }:
            fail(f"{context}: exact replay contract mismatch")
        require_effects(effects, {"jobCreatedTotal": 1, "captionPipelineStartsTotal": 0}, context)
    elif context == "same_key_equivalent_but_different_raw_url_conflicts":
        if not same_key or same_fingerprint:
            fail(f"{context}: conflict requires the same key and different canonical body")
        if first_normalized["videoId"] != second_normalized["videoId"]:
            fail(f"{context}: fixture must prove conflict happens before equivalent-URL dedupe")
        if expected["normalizedVideoIdWouldMatch"] != first_normalized["videoId"]:
            fail(f"{context}: normalized Video ID evidence mismatch")
        if expected["outcome"] != "idempotency_conflict":
            fail(f"{context}: expected idempotency_conflict")
        check_api_error_response(expected["response"], openapi, context)
        require_effects(
            effects,
            {"jobCreated": False, "jobIdReturned": False, "normalizationRunsOnSecondRequest": 0, "sourceMetadataCalls": 0, "captionPipelineStarts": 0},
            context,
        )
    else:
        fail(f"unknown handoff fixture case {context}")


def check_retry_after_header(response: dict[str, Any], openapi: dict[str, Any], context: str) -> None:
    response_contract = openapi["paths"]["/v1/parse-jobs"]["post"]["responses"]["429"]
    if "$ref" not in response_contract:
        fail(f"{context}: frozen 429 response must reference RateLimitedErrorResponse")
    resolved = RELEASE_A.resolve_ref(openapi, response_contract["$ref"])
    retry_contract = resolved.get("headers", {}).get("Retry-After")
    if retry_contract is None or retry_contract.get("required") is not True:
        fail(f"{context}: frozen 429 contract must require Retry-After")
    retry_schema = retry_contract.get("schema", {})
    if retry_schema != {"type": "integer", "minimum": 1}:
        fail(f"{context}: unsupported frozen Retry-After schema {retry_schema!r}")
    headers = response.get("headers")
    if not isinstance(headers, dict) or "Retry-After" not in headers:
        fail(f"{context}: 429 fixture must include Retry-After")
    retry_after = headers["Retry-After"]
    if not isinstance(retry_after, int) or isinstance(retry_after, bool) or retry_after < 1:
        fail(f"{context}: Retry-After must be an integer >= 1 second")


def check_provider_guard_case(case: dict[str, Any], openapi: dict[str, Any]) -> None:
    context = case["case"]
    response = case["expected"]["response"]
    effects = case["expectedEffects"]
    require_effects(effects, ZERO_PIPELINE_EFFECTS, context)
    if context == "quota_exceeded_rejects_before_source_probe":
        if case["input"].get("quotaDecision") != "deny":
            fail(f"{context}: quota_exceeded fixture requires quotaDecision=deny")
        check_api_error_response(response, openapi, context)
        check_retry_after_header(response, openapi, context)
        if response["body"]["errorCode"] != "quota_exceeded":
            fail(f"{context}: wrong quota error")
        require_effects(
            effects,
            {"jobCreated": False, "jobIdReturned": False, "sourceMetadataCalls": 0, "captionAvailabilityCalls": 0},
            context,
        )
    elif context == "cost_policy_denial_is_job_error_before_async_providers":
        if case["input"].get("costPolicyDecision") != "deny":
            fail(f"{context}: cost_limit_exceeded fixture requires costPolicyDecision=deny")
        if response["status"] != 200 or response["bodySchema"] != "ProcessingJob":
            fail(f"{context}: frozen cost error is an HTTP 200 failed ProcessingJob")
        RELEASE_A.assert_valid(response["body"], "ProcessingJob", openapi, context)
        body = response["body"]
        if body["status"] != "failed" or body["errorCode"] != "cost_limit_exceeded" or body["retryable"] is not False:
            fail(f"{context}: cost guard failed-job mapping changed")
        if case["expected"].get("preflight4xx") is not False:
            fail(f"{context}: cost_limit_exceeded must not be represented as preflight 4xx")
        if case["input"].get("thresholdEvidence") != "NOT_RUN_D2":
            fail(f"{context}: fixture must not invent a cost threshold")
        require_effects(effects, {"existingJobRequired": True, "jobCreated": False}, context)
    else:
        fail(f"unknown provider guard fixture case {context}")


REQUIRED_CASES = {
    "watch_url_strips_tracking_and_fragment",
    "short_url_strips_tracking",
    "blank_url_is_invalid",
    "non_youtube_host_is_unsupported",
    "deceptive_youtube_suffix_is_unsupported",
    "watch_url_missing_video_id_is_invalid",
    "short_url_missing_video_id_is_invalid",
    "duplicate_video_id_is_invalid",
    "public_captioned_english_900_seconds_is_accepted",
    "private_video_is_rejected",
    "live_video_is_rejected",
    "not_embeddable_video_is_rejected",
    "video_over_900_seconds_is_rejected",
    "non_english_video_is_rejected",
    "captions_unavailable_is_release_a_4xx",
    "unparseable_english_captions_are_unavailable",
    "different_keys_equivalent_urls_share_dedupe_key",
    "same_key_same_raw_body_is_exact_replay",
    "same_key_equivalent_but_different_raw_url_conflicts",
    "quota_exceeded_rejects_before_source_probe",
    "cost_policy_denial_is_job_error_before_async_providers",
}


def assert_contract_failure(action: Callable[[], None], context: str) -> None:
    try:
        action()
    except (ContractFailure, RELEASE_A.ContractFailure):
        return
    fail(f"{context}: negative mutation unexpectedly passed")


def run_mutation_probes(
    policy: dict[str, Any],
    policy_schema: dict[str, Any],
    openapi: dict[str, Any],
    by_case: dict[str, dict[str, Any]],
) -> int:
    mutation = deepcopy(by_case["watch_url_strips_tracking_and_fragment"])
    mutation["expected"]["videoId"] = "WrongVideo1"
    assert_contract_failure(lambda: check_normalization_case(mutation, policy, openapi), "normalization output mutation")

    mutation = deepcopy(by_case["public_captioned_english_900_seconds_is_accepted"])
    mutation["input"]["facts"]["durationSeconds"] = 900.001
    assert_contract_failure(lambda: check_preflight_case(mutation, policy, openapi), "inclusive duration boundary mutation")

    mutation = deepcopy(by_case["captions_unavailable_is_release_a_4xx"])
    mutation["expectedEffects"]["jobCreated"] = True
    assert_contract_failure(lambda: check_preflight_case(mutation, policy, openapi), "caption rejection side-effect mutation")

    mutation = deepcopy(by_case["cost_policy_denial_is_job_error_before_async_providers"])
    mutation["expectedEffects"]["translationCalls"] = 1
    assert_contract_failure(lambda: check_provider_guard_case(mutation, openapi), "cost guard provider mutation")

    mutation = deepcopy(policy)
    mutation["preflight"]["maximumDurationSeconds"] = 901
    assert_contract_failure(lambda: check_policy(mutation, policy_schema), "policy duration mutation")

    # Spock P1-1 required regressions: each mutation must be rejected.
    mutation = deepcopy(policy)
    mutation["rejectionEffects"]["jobCreated"] = True
    assert_contract_failure(
        lambda: check_policy(mutation, policy_schema),
        "policy rejection jobCreated=true mutation",
    )

    mutation = deepcopy(policy)
    mutation["preflight"]["errors"]["visibility"] = "captions_unavailable"
    assert_contract_failure(
        lambda: check_policy(mutation, policy_schema),
        "visibility error mapping mutation",
    )

    mutation = deepcopy(policy)
    mutation["providerEntryGuards"]["quota"]["jobMayExist"] = True
    assert_contract_failure(
        lambda: check_policy(mutation, policy_schema),
        "quota jobMayExist=true mutation",
    )

    mutation = deepcopy(policy)
    order = mutation["requestOrder"]
    order.remove("rate_quota_concurrency_gate")
    order.insert(order.index("source_metadata_probe") + 1, "rate_quota_concurrency_gate")
    assert_contract_failure(
        lambda: check_policy(mutation, policy_schema),
        "quota gate after source probe mutation",
    )

    mutation = deepcopy(policy)
    mutation["providerEntryGuards"]["cost"]["wireShape"] = "APIError"
    assert_contract_failure(
        lambda: check_policy(mutation, policy_schema),
        "cost wire shape APIError mutation",
    )

    mutation = deepcopy(policy)
    mutation["providerEntryGuards"]["cost"]["mustRunBeforeAsyncCaptionOrTranslationProvider"] = False
    assert_contract_failure(
        lambda: check_policy(mutation, policy_schema),
        "cost guard after provider start mutation",
    )

    mutation = deepcopy(policy)
    mutation["openDecisions"][0]["state"] = "CLOSED"
    assert_contract_failure(
        lambda: check_policy(mutation, policy_schema),
        "D2-A CLOSED mutation",
    )

    mutation = deepcopy(by_case["quota_exceeded_rejects_before_source_probe"])
    mutation["input"]["quotaDecision"] = "allow"
    assert_contract_failure(
        lambda: check_provider_guard_case(mutation, openapi),
        "quota allow input with denial response mutation",
    )

    # Spock P1-2: the frozen 429 response requires Retry-After.
    mutation = deepcopy(by_case["quota_exceeded_rejects_before_source_probe"])
    del mutation["expected"]["response"]["headers"]["Retry-After"]
    assert_contract_failure(
        lambda: check_provider_guard_case(mutation, openapi),
        "quota Retry-After omission mutation",
    )

    mutation = deepcopy(openapi)
    mutation["x-error-contract"]["captions_unavailable"]["httpStatus"] = 400
    assert_contract_failure(lambda: check_release_a_compatibility(mutation), "frozen error mapping mutation")

    return 15


def main() -> int:
    try:
        policy_schema = load_json(POLICY_SCHEMA_PATH)
        fixture_schema = load_json(FIXTURE_SCHEMA_PATH)
        policy = load_json(POLICY_PATH)
        check_policy(policy, policy_schema)
        openapi = source_openapi(policy)
        check_release_a_compatibility(openapi)

        fixture_paths = sorted(FIXTURE_DIR.glob("*.json"))
        if not fixture_paths:
            fail("no #1725 fixture files found")
        fixtures = [load_json(path) for path in fixture_paths]
        by_case: dict[str, dict[str, Any]] = {}
        kind_counts: dict[str, int] = {}
        for path, fixture in zip(fixture_paths, fixtures):
            assert_schema(fixture, fixture_schema, path.name)
            kind = fixture["kind"]
            kind_counts[kind] = kind_counts.get(kind, 0) + len(fixture["cases"])
            for case in fixture["cases"]:
                name = case["case"]
                if name in by_case:
                    fail(f"duplicate fixture case {name}")
                by_case[name] = case
                if kind == "normalization":
                    check_normalization_case(case, policy, openapi)
                elif kind == "preflight":
                    check_preflight_case(case, policy, openapi)
                elif kind == "handoff":
                    check_handoff_case(case, policy, openapi)
                elif kind == "provider_entry_guard":
                    check_provider_guard_case(case, openapi)
                else:
                    fail(f"unsupported fixture kind {kind}")

        if set(by_case) != REQUIRED_CASES:
            fail(
                "fixture case set mismatch: "
                f"missing={sorted(REQUIRED_CASES - set(by_case))!r}, "
                f"extra={sorted(set(by_case) - REQUIRED_CASES)!r}"
            )
        mutation_count = run_mutation_probes(policy, policy_schema, openapi, by_case)
    except (ContractFailure, RELEASE_A.ContractFailure, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("PASS: SubTube #1725 URL normalization/preflight readback")
    print(f"- Policy/schema parsed: {POLICY_PATH.relative_to(ROOT.parent.parent)}")
    print(f"- Fixture collections passed: {len(fixture_paths)} files / {len(by_case)} cases / {kind_counts}")
    print("- MVP-01 passed: watch + short URL normalization, tracking removal, blank/source/missing/ambiguous rejection")
    print("- AC-01 contract passed: public, non-live, embeddable, English, captioned, duration=900s creates one queued job")
    print("- AC-02A contract passed: unavailable/unparseable captions return 422 with no job/audio/STT/LLM")
    print("- AC-04 contract passed: invalid/private/live/not-embeddable/non-English/>900s map to frozen 4xx errors")
    print("- Idempotency/dedupe handoff passed: raw-body fingerprint, exact replay, equivalent-URL conflict, normalized Video ID dedupe")
    print("- Quota/cost provider-entry guards passed; concrete cost threshold remains NOT_RUN_D2")
    print("- Release A compatibility passed: frozen OpenAPI is read-only, caption-only, and excludes transcribing/STT")
    print(f"- Mutation regressions rejected: {mutation_count} total")
    print("- Spock P1-1 rejected: rejection job creation, visibility mapping, quota job existence/order, cost shape/order, D2-A CLOSED, quota allow-input denial")
    print("- Spock P1-2 passed: quota 429 requires positive-integer Retry-After; missing-header mutation rejected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
