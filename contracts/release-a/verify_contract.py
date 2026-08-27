#!/usr/bin/env python3
"""Dependency-free readback checks for the SubTube Release A contract package."""

from __future__ import annotations

import json
import re
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OPENAPI_PATH = ROOT / "openapi.json"
FIXTURE_DIR = ROOT / "fixtures"
PIPELINE_VERSION = "release-a-caption-v1"
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
API_ERROR_ZERO_EFFECTS = {
    "jobCreated": False,
    "captionPipelineStarts": 0,
    "translationCalls": 0,
    "audioDownloads": 0,
    "sttCalls": 0,
}
SUCCESS_EFFECT_CONTRACTS = {
    "normal_new_job": {
        "jobCreated": True,
        "reusedJobId": None,
        "captionPipelineStarted": False,
        "translationPipelineStarted": False,
        "audioDownloads": 0,
        "sttCalls": 0,
    },
    "normal_poll_fetching_captions": {
        "jobCreated": False,
        "captionPipelineStarted": True,
        "translationPipelineStarted": False,
        "audioDownloads": 0,
        "sttCalls": 0,
    },
    "normal_poll_translating": {
        "jobCreated": False,
        "captionPipelineStarted": True,
        "translationPipelineStarted": True,
        "audioDownloads": 0,
        "sttCalls": 0,
    },
    "normal_ready": {
        "jobCreated": False,
        "captionPipelineStarted": True,
        "translationPipelineStarted": True,
        "readyResultPersisted": True,
        "audioDownloads": 0,
        "sttCalls": 0,
    },
    "learning_data_without_word_timestamps": {
        "documentAccepted": True,
        "sentenceSeekEnabled": True,
        "wordHighlightEnabled": False,
        "audioDownloads": 0,
        "sttCalls": 0,
    },
    "retry_failed_job_with_new_idempotency_key": {
        "outcome": "new_job",
        "failedJobReusedAsSuccess": False,
        "jobCreated": True,
        "reusedNewerOwner": False,
        "captionPipelineStarted": False,
        "translationPipelineStarted": False,
        "audioDownloads": 0,
        "sttCalls": 0,
    },
    "ready_dedupe_cache_hit": {
        "jobCreated": False,
        "cacheHitEventRecorded": True,
        "captionCalls": 0,
        "translationCalls": 0,
        "audioDownloads": 0,
        "sttCalls": 0,
    },
    "same_key_same_request_exact_replay": {
        "jobCreatedCount": 1,
        "sameResponse": True,
        "minimumRetentionHours": 24,
        "captionPipelineStarted": False,
        "translationPipelineStarted": False,
        "audioDownloads": 0,
        "sttCalls": 0,
    },
    "different_key_same_dedupe_inflight_convergence": {
        "ownerJobCreated": True,
        "jobCreated": False,
        "reusedInFlightOwner": True,
        "activeOwnerCount": 1,
        "captionPipelineStartsTotal": 1,
        "translationCallsTotal": 0,
        "audioDownloadsTotal": 0,
        "audioDownloads": 0,
        "sttCalls": 0,
    },
}


class ContractFailure(AssertionError):
    pass


def fail(message: str) -> None:
    raise ContractFailure(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"{path}: cannot read valid JSON: {error}")


def resolve_ref(document: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        fail(f"external refs are not allowed: {ref}")
    value: Any = document
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[token]
    if not isinstance(value, dict):
        fail(f"schema ref does not resolve to an object: {ref}")
    return value


def is_type(instance: Any, expected: str) -> bool:
    return {
        "null": instance is None,
        "object": isinstance(instance, dict),
        "array": isinstance(instance, list),
        "string": isinstance(instance, str),
        "boolean": isinstance(instance, bool),
        "integer": isinstance(instance, int) and not isinstance(instance, bool),
        "number": isinstance(instance, (int, float)) and not isinstance(instance, bool),
    }.get(expected, False)


def json_const_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON values without Python's bool-as-int coercion."""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual == expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            json_const_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    if isinstance(actual, dict):
        return (
            actual.keys() == expected.keys()
            and all(json_const_equal(actual[key], expected[key]) for key in actual)
        )
    return actual == expected


def parse_rfc3339(value: str) -> datetime:
    if RFC3339_PATTERN.fullmatch(value) is None:
        raise ValueError("date-time must include T, seconds, and Z or a numeric UTC offset")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("date-time must include a timezone")
    return parsed


def validate(
    instance: Any,
    schema: dict[str, Any],
    document: dict[str, Any],
    path: str = "$",
) -> list[str]:
    if "$ref" in schema:
        return validate(instance, resolve_ref(document, schema["$ref"]), document, path)

    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None:
        allowed = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(is_type(instance, item) for item in allowed):
            return [f"{path}: expected type {allowed}, got {type(instance).__name__}"]

    if "const" in schema and not json_const_equal(instance, schema["const"]):
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']!r}")

    if isinstance(instance, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate(value, properties[key], document, f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {key!r}")

    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errors.append(f"{path}: expected at least {schema['minItems']} items")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(instance):
                errors.extend(validate(item, item_schema, document, f"{path}[{index}]"))

    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than minLength")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path}: does not match {schema['pattern']!r}")
        if schema.get("format") == "uuid":
            try:
                uuid.UUID(instance)
            except ValueError:
                errors.append(f"{path}: invalid UUID")
        if schema.get("format") == "date-time":
            try:
                parse_rfc3339(instance)
            except ValueError:
                errors.append(f"{path}: invalid RFC 3339 date-time")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: not above exclusiveMinimum {schema['exclusiveMinimum']}")

    if "oneOf" in schema:
        branch_errors = [validate(instance, branch, document, path) for branch in schema["oneOf"]]
        matches = sum(not branch for branch in branch_errors)
        if matches != 1:
            errors.append(f"{path}: expected exactly one oneOf match, got {matches}")

    return errors


def schema(openapi: dict[str, Any], name: str) -> dict[str, Any]:
    return openapi["components"]["schemas"][name]


def check_refs(value: Any, document: dict[str, Any], path: str = "$") -> None:
    if isinstance(value, dict):
        if "$ref" in value:
            resolve_ref(document, value["$ref"])
        for key, child in value.items():
            check_refs(child, document, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            check_refs(child, document, f"{path}[{index}]")


def operation_for(request: dict[str, Any], openapi: dict[str, Any]) -> dict[str, Any]:
    path = request["path"].split("?", 1)[0]
    if path == "/v1/parse-jobs":
        template = path
    elif re.fullmatch(r"/v1/parse-jobs/[^/]+", path):
        template = "/v1/parse-jobs/{jobId}"
    elif re.fullmatch(r"/v1/videos/[^/]+/learning-data", path):
        template = "/v1/videos/{videoId}/learning-data"
    else:
        fail(f"fixture request path is outside the OpenAPI contract: {request['path']}")
    method = request["method"].lower()
    try:
        return openapi["paths"][template][method]
    except KeyError:
        fail(f"fixture method is outside the OpenAPI contract: {request['method']} {request['path']}")


def assert_valid(instance: Any, schema_name: str, openapi: dict[str, Any], context: str) -> None:
    errors = validate(instance, schema(openapi, schema_name), openapi)
    if errors:
        fail(f"{context}: schema {schema_name} failed:\n  " + "\n  ".join(errors))


def assert_invalid(instance: Any, schema_name: str, openapi: dict[str, Any], context: str) -> None:
    if not validate(instance, schema(openapi, schema_name), openapi):
        fail(f"{context}: negative mutation unexpectedly passed schema {schema_name}")


def assert_contract_failure(action: Any, context: str) -> None:
    try:
        action()
    except ContractFailure:
        return
    fail(f"{context}: semantic mutation unexpectedly passed")


def check_exchange(
    request: dict[str, Any],
    response: dict[str, Any],
    openapi: dict[str, Any],
    context: str,
) -> None:
    operation = operation_for(request, openapi)
    if str(response["status"]) not in operation["responses"]:
        fail(f"{context}: HTTP {response['status']} is not declared for this operation")
    assert_valid(response["body"], response["bodySchema"], openapi, context)
    if request["method"] == "POST":
        assert_valid(request["body"], "ParseJobRequest", openapi, context)
        key = request["headers"].get("Idempotency-Key")
        if not key:
            fail(f"{context}: POST fixture lacks Idempotency-Key")
        try:
            uuid.UUID(key)
        except ValueError:
            fail(f"{context}: invalid Idempotency-Key UUID")


def check_api_error_effects(fixture: dict[str, Any], context: str) -> None:
    effects = fixture.get("expectedEffects", {})
    for key, expected in API_ERROR_ZERO_EFFECTS.items():
        if key not in effects:
            fail(f"{context}: APIError fixture must assert {key}={expected!r}")
        if effects[key] != expected:
            fail(f"{context}: APIError fixture {key}={effects[key]!r}, expected {expected!r}")


def check_release_a_fixture_effects(fixture: dict[str, Any], context: str) -> None:
    effects = fixture.get("expectedEffects", {})
    for key in ("audioDownloads", "sttCalls"):
        if key not in effects:
            fail(f"{context}: every Release A fixture must explicitly assert {key}=0")
        if effects[key] != 0:
            fail(f"{context}: Release A requires {key}=0, got {effects[key]!r}")

    response = fixture["response"]
    body = response["body"]
    is_success = response["bodySchema"] == "LearningDocument" or (
        response["bodySchema"] == "ProcessingJob" and body["status"] != "failed"
    )
    if not is_success:
        return

    case = fixture["case"]
    expected_effects = SUCCESS_EFFECT_CONTRACTS.get(case)
    if expected_effects is None:
        fail(f"{context}: successful fixture has no explicit effect oracle")
    for key, expected in expected_effects.items():
        if key not in effects:
            fail(f"{context}: successful fixture must assert {key}={expected!r}")
        if effects[key] != expected:
            fail(f"{context}: successful fixture {key}={effects[key]!r}, expected {expected!r}")


def check_fixture(fixture: dict[str, Any], path: Path, openapi: dict[str, Any]) -> None:
    response = fixture["response"]
    check_exchange(fixture["request"], response, openapi, path.name)
    check_release_a_fixture_effects(fixture, path.name)

    body = response["body"]
    if response["bodySchema"] == "APIError":
        error_contract = openapi["x-error-contract"].get(body["errorCode"])
        if error_contract is None:
            fail(f"{path.name}: errorCode is absent from x-error-contract")
        actual = (response["status"], body["errorMessageKey"], body["retryable"])
        expected = (
            error_contract["httpStatus"],
            error_contract["messageKey"],
            error_contract["retryable"],
        )
        if actual != expected:
            fail(f"{path.name}: APIError mapping {actual!r} != {expected!r}")
        if "jobId" in body:
            fail(f"{path.name}: preflight/request error must not contain jobId")
        check_api_error_effects(fixture, path.name)

    if response["bodySchema"] == "ProcessingJob" and body["status"] == "failed":
        error_contract = openapi["x-error-contract"][body["errorCode"]]
        actual = (response["status"], body["errorMessageKey"], body["retryable"])
        expected = (
            error_contract["httpStatus"],
            error_contract["messageKey"],
            error_contract["retryable"],
        )
        if actual != expected:
            fail(f"{path.name}: failed-job mapping {actual!r} != {expected!r}")

    if response["bodySchema"] == "LearningDocument":
        segment_ids: set[str] = set()
        previous_start = -1.0
        for segment in body["segments"]:
            if segment["id"] in segment_ids:
                fail(f"{path.name}: duplicate segment id {segment['id']!r}")
            segment_ids.add(segment["id"])
            if segment["endTime"] <= segment["startTime"]:
                fail(f"{path.name}: segment endTime must exceed startTime")
            if segment["startTime"] < previous_start:
                fail(f"{path.name}: segment order must follow startTime")
            previous_start = segment["startTime"]
            word_ids: set[str] = set()
            for word in segment["words"]:
                if word["id"] in word_ids:
                    fail(f"{path.name}: duplicate word id {word['id']!r}")
                word_ids.add(word["id"])
                if word["end"] <= word["start"]:
                    fail(f"{path.name}: word end must exceed start")
                if word["start"] < segment["startTime"] or word["end"] > segment["endTime"]:
                    fail(f"{path.name}: word timestamp must stay within its sentence")

def check_normal_transition_chain(by_case: dict[str, dict[str, Any]]) -> None:
    cases = (
        "normal_new_job",
        "normal_poll_fetching_captions",
        "normal_poll_translating",
        "normal_ready",
    )
    bodies = [by_case[case]["response"]["body"] for case in cases]
    states = [body["status"] for body in bodies]
    if states != ["queued", "fetching_captions", "translating", "ready"]:
        fail(f"normal transition fixture path is invalid: {states!r}")

    job_ids = {body["jobId"] for body in bodies}
    video_ids = {body["videoId"] for body in bodies}
    if len(job_ids) != 1:
        fail(f"normal transition jobId must remain stable: {sorted(job_ids)!r}")
    if len(video_ids) != 1:
        fail(f"normal transition videoId must remain stable: {sorted(video_ids)!r}")

    job_id = bodies[0]["jobId"]
    for case in cases[1:]:
        request_path = by_case[case]["request"]["path"]
        if request_path != f"/v1/parse-jobs/{job_id}":
            fail(f"{case}: poll path does not match transition jobId {job_id!r}")

    updated_at = [parse_rfc3339(body["updatedAt"]) for body in bodies]
    if any(later <= earlier for earlier, later in zip(updated_at, updated_at[1:])):
        fail("normal transition updatedAt values must be strictly monotonic")


def check_retry_outcome(retry: dict[str, Any]) -> None:
    old_key = retry["priorRequest"]["headers"]["Idempotency-Key"]
    new_key = retry["request"]["headers"]["Idempotency-Key"]
    if old_key == new_key:
        fail("a user-initiated retry must use a new Idempotency-Key")
    if retry["priorRequest"]["body"] != retry["request"]["body"]:
        fail("retry fixture must preserve the parse request body/dedupe input")

    effects = retry["expectedEffects"]
    if effects["failedJobReusedAsSuccess"] is not False:
        fail("a failed job may not be reused as a successful cache result")
    job_created = effects.get("jobCreated") is True
    reused_newer_owner = effects.get("reusedNewerOwner") is True
    if job_created == reused_newer_owner:
        fail("retry must assert exactly one outcome: new job or existing newer owner")

    prior_failed_job_id = effects.get("priorFailedJobId")
    returned_job_id = retry["response"]["body"]["jobId"]
    if not prior_failed_job_id or returned_job_id == prior_failed_job_id:
        fail("retry must not return the prior failed job as its processing owner")
    expected_outcome = "new_job" if job_created else "reused_newer_owner"
    if effects.get("outcome") != expected_outcome:
        fail(f"retry outcome must be {expected_outcome!r}")
    if reused_newer_owner and effects.get("reusedJobId") != returned_job_id:
        fail("retry newer-owner reuse must identify the returned owner jobId")


def check_package(openapi: dict[str, Any], fixtures: list[tuple[Path, dict[str, Any]]]) -> list[str]:
    if openapi.get("openapi") != "3.1.0":
        fail("OpenAPI version must remain 3.1.0")
    check_refs(openapi, openapi)
    expected_paths = {
        "/v1/parse-jobs",
        "/v1/parse-jobs/{jobId}",
        "/v1/videos/{videoId}/learning-data",
    }
    if set(openapi["paths"]) != expected_paths:
        fail(f"Release A path set changed unexpectedly: {sorted(openapi['paths'])!r}")

    statuses = schema(openapi, "ProcessingStatus")["enum"]
    if statuses != ["queued", "fetching_captions", "translating", "ready", "failed"]:
        fail(f"Release A status enum changed unexpectedly: {statuses!r}")
    if "transcribing" in json.dumps(openapi["components"]["schemas"]):
        fail("Release A schemas must not contain transcribing")
    if schema(openapi, "LearningDocument")["properties"]["transcriptSource"] != {"const": "caption"}:
        fail("Release A transcriptSource must be caption-only")
    if schema(openapi, "LearningDocument")["properties"]["pipelineVersion"] != {"const": PIPELINE_VERSION}:
        fail("Release A LearningDocument pipelineVersion must match the frozen #1705 identity")
    if openapi.get("x-pipeline-identity") != {
        "canonicalVersion": PIPELINE_VERSION,
        "dedupeKeyFields": ["videoId", "sourceLanguage", "targetLanguage", "pipelineVersion"],
        "identityChangeReusesOldCacheOrOwner": False,
    }:
        fail("Release A pipeline/cache identity contract drifted")

    names = {fixture["case"] for _, fixture in fixtures}
    required_cases = {
        "normal_new_job",
        "normal_poll_fetching_captions",
        "normal_poll_translating",
        "normal_ready",
        "learning_data_without_word_timestamps",
        "release_a_captions_unavailable",
        "unsupported_private_video",
        "translation_provider_failed",
        "retry_failed_job_with_new_idempotency_key",
        "ready_dedupe_cache_hit",
        "same_key_same_request_exact_replay",
        "invalid_url",
        "unsupported_live_video",
        "unsupported_not_embeddable_video",
        "unsupported_non_english_video",
        "unsupported_video_too_long",
        "different_key_same_dedupe_inflight_convergence",
        "same_key_different_canonical_body_conflict",
    }
    missing = required_cases - names
    if missing:
        fail(f"required fixture cases missing: {sorted(missing)!r}")

    by_case = {fixture["case"]: fixture for _, fixture in fixtures}
    successful_cases = {
        fixture["case"]
        for _, fixture in fixtures
        if fixture["response"]["bodySchema"] == "LearningDocument"
        or (
            fixture["response"]["bodySchema"] == "ProcessingJob"
            and fixture["response"]["body"]["status"] != "failed"
        )
    }
    if successful_cases != set(SUCCESS_EFFECT_CONTRACTS):
        fail(
            "successful fixture/effect-oracle coverage mismatch: "
            f"missing={sorted(successful_cases - set(SUCCESS_EFFECT_CONTRACTS))!r}, "
            f"stale={sorted(set(SUCCESS_EFFECT_CONTRACTS) - successful_cases)!r}"
        )
    check_normal_transition_chain(by_case)
    normal_video_id = by_case["normal_new_job"]["response"]["body"]["videoId"]
    learning_video_id = by_case["learning_data_without_word_timestamps"]["response"]["body"]["videoId"]
    if learning_video_id != normal_video_id:
        fail("normal LearningDocument videoId must match the ready transition videoId")
    if by_case["learning_data_without_word_timestamps"]["response"]["body"]["pipelineVersion"] != PIPELINE_VERSION:
        fail("normal LearningDocument pipelineVersion must use the canonical Release A identity")

    ac04_cases = {
        "invalid_url": "invalid_url",
        "unsupported_private_video": "video_private",
        "unsupported_live_video": "video_live",
        "unsupported_not_embeddable_video": "video_not_embeddable",
        "unsupported_non_english_video": "non_english",
        "unsupported_video_too_long": "video_too_long",
    }
    for case, expected_code in ac04_cases.items():
        fixture = by_case[case]
        if fixture["response"]["body"]["errorCode"] != expected_code:
            fail(f"{case}: expected AC-04 errorCode {expected_code!r}")
        check_api_error_effects(fixture, case)

    retry = by_case["retry_failed_job_with_new_idempotency_key"]
    assert_valid(retry["priorRequest"]["body"], "ParseJobRequest", openapi, "retry prior request")
    check_retry_outcome(retry)

    inflight = by_case["different_key_same_dedupe_inflight_convergence"]
    check_exchange(inflight["ownerRequest"], inflight["ownerResponse"], openapi, "in-flight owner exchange")
    owner_key = inflight["ownerRequest"]["headers"]["Idempotency-Key"]
    reuse_key = inflight["request"]["headers"]["Idempotency-Key"]
    if owner_key == reuse_key:
        fail("in-flight dedupe reuse must use a different Idempotency-Key")
    owner_body = inflight["ownerResponse"]["body"]
    reuse_body = inflight["response"]["body"]
    if owner_body["jobId"] != reuse_body["jobId"] or owner_body["videoId"] != reuse_body["videoId"]:
        fail("in-flight requests with the same dedupe key must converge on one job/video identity")
    inflight_effects = inflight["expectedEffects"]
    if inflight_effects["ownerDedupeKey"] != inflight_effects["requestDedupeKey"]:
        fail("in-flight fixture must assert the same server dedupe key")
    expected_inflight_key = f"{owner_body['videoId']}|en|zh-Hant-TW|{PIPELINE_VERSION}"
    if inflight_effects["ownerDedupeKey"] != expected_inflight_key:
        fail("in-flight fixture dedupe key must use the canonical Release A identity")
    if inflight_effects["ownerJobCreated"] is not True or inflight_effects["jobCreated"] is not False:
        fail("in-flight convergence must create only the owner job")
    if inflight_effects["reusedInFlightOwner"] is not True:
        fail("the second in-flight request must explicitly reuse the owner")
    if inflight_effects["reusedJobId"] != owner_body["jobId"] or inflight_effects["activeOwnerCount"] != 1:
        fail("in-flight convergence must identify exactly one active owner")
    if inflight_effects["captionPipelineStartsTotal"] != 1:
        fail("in-flight convergence must start the caption pipeline exactly once")
    for key in ("translationCallsTotal", "audioDownloadsTotal", "sttCalls"):
        if inflight_effects[key] != 0:
            fail(f"in-flight convergence fixture must assert {key}=0 at the sampled stage")
    if parse_rfc3339(reuse_body["updatedAt"]) <= parse_rfc3339(owner_body["updatedAt"]):
        fail("in-flight reused snapshot must not predate its owner snapshot")

    conflict = by_case["same_key_different_canonical_body_conflict"]
    check_exchange(conflict["priorRequest"], conflict["priorResponse"], openapi, "idempotency conflict prior exchange")
    prior_key = conflict["priorRequest"]["headers"]["Idempotency-Key"]
    conflict_key = conflict["request"]["headers"]["Idempotency-Key"]
    if prior_key != conflict_key:
        fail("idempotency conflict must reuse the same Idempotency-Key")
    if conflict["priorRequest"]["body"] == conflict["request"]["body"]:
        fail("idempotency conflict requires a different canonical request body")
    if conflict["response"]["status"] != 409 or conflict["response"]["body"]["errorCode"] != "idempotency_conflict":
        fail("same key with a different canonical body must return 409 idempotency_conflict")
    check_api_error_effects(conflict, "idempotency conflict")

    cache = by_case["ready_dedupe_cache_hit"]
    if cache["response"]["status"] != 200 or cache["response"]["body"]["status"] != "ready":
        fail("ready cache hit must return HTTP 200 and status=ready")
    for key in ("captionCalls", "translationCalls", "sttCalls"):
        if cache["expectedEffects"][key] != 0:
            fail(f"ready cache hit must assert {key}=0")

    replay = by_case["same_key_same_request_exact_replay"]
    assert_valid(replay["replayResponse"]["body"], replay["replayResponse"]["bodySchema"], openapi, "idempotency replay")
    if replay["request"] != replay["replayRequest"]:
        fail("idempotency replay request must be byte-equivalent at fixture level")
    if replay["response"] != replay["replayResponse"]:
        fail("idempotency replay must preserve status, headers, and body")
    if replay["expectedEffects"]["jobCreatedCount"] != 1:
        fail("idempotency replay must create exactly one job")
    if replay["expectedEffects"]["minimumRetentionHours"] < 24:
        fail("idempotency retention must be at least 24 hours")

    retention = openapi.get("x-result-cache-retention")
    if retention != {"successDays": 7, "purgeEvidence": "NOT_RUN_D5"}:
        fail("7-day success cache contract must remain explicit with purgeEvidence=NOT_RUN_D5")

    queued = by_case["normal_new_job"]["response"]["body"]
    mutation = deepcopy(queued)
    mutation["status"] = "transcribing"
    assert_invalid(mutation, "ProcessingJob", openapi, "Release B status exclusion")
    mutation = deepcopy(queued)
    mutation["learningDataPath"] = "/v1/videos/abcdefghijk/learning-data?target=zh-Hant-TW"
    assert_invalid(mutation, "ProcessingJob", openapi, "processing nullability")
    ready = by_case["normal_ready"]["response"]["body"]
    mutation = deepcopy(ready)
    mutation["learningDataPath"] = None
    assert_invalid(mutation, "ProcessingJob", openapi, "ready nullability")
    failed_job = by_case["translation_provider_failed"]["response"]["body"]
    mutation = deepcopy(failed_job)
    mutation["errorCode"] = None
    assert_invalid(mutation, "ProcessingJob", openapi, "failed error requirement")
    learning = by_case["learning_data_without_word_timestamps"]["response"]["body"]
    mutation = deepcopy(learning)
    mutation["transcriptSource"] = "stt"
    assert_invalid(mutation, "LearningDocument", openapi, "Release B transcript exclusion")
    mutation = deepcopy(learning)
    del mutation["segments"][0]["words"]
    assert_invalid(mutation, "LearningDocument", openapi, "words presence requirement")
    mutation = deepcopy(queued)
    mutation["updatedAt"] = "2026-08-25T06:00:00"
    assert_invalid(mutation, "ProcessingJob", openapi, "RFC 3339 timezone requirement")

    mutated_chain = deepcopy(by_case)
    mutated_chain["normal_poll_translating"]["response"]["body"]["jobId"] = "job-mismatched"
    assert_contract_failure(
        lambda: check_normal_transition_chain(mutated_chain),
        "mismatched transition jobId mutation",
    )
    mutated_chain = deepcopy(by_case)
    mutated_chain["normal_poll_translating"]["response"]["body"]["updatedAt"] = "2026-08-25T06:00:03Z"
    assert_contract_failure(
        lambda: check_normal_transition_chain(mutated_chain),
        "non-monotonic transition updatedAt mutation",
    )
    mutated_ac04 = deepcopy(by_case["unsupported_private_video"])
    mutated_ac04["expectedEffects"]["audioDownloads"] = 1
    assert_contract_failure(
        lambda: check_api_error_effects(mutated_ac04, "mutated AC-04 fixture"),
        "AC-04 downstream side-effect mutation",
    )
    mutated_retry = deepcopy(retry)
    mutated_retry["expectedEffects"]["jobCreated"] = False
    assert_contract_failure(
        lambda: check_retry_outcome(mutated_retry),
        "retry jobCreated=false mutation",
    )
    mutated_success = deepcopy(by_case["normal_new_job"])
    mutated_success["expectedEffects"]["audioDownloads"] = 1
    assert_contract_failure(
        lambda: check_release_a_fixture_effects(mutated_success, "mutated normal submit fixture"),
        "successful caption path audio download mutation",
    )
    mutated_success = deepcopy(by_case["normal_poll_fetching_captions"])
    mutated_success["expectedEffects"]["captionPipelineStarted"] = False
    assert_contract_failure(
        lambda: check_release_a_fixture_effects(mutated_success, "mutated caption-stage fixture"),
        "caption-stage pipeline flag mutation",
    )
    mutated_fallback = deepcopy(by_case["learning_data_without_word_timestamps"])
    mutated_fallback["expectedEffects"]["sentenceSeekEnabled"] = False
    assert_contract_failure(
        lambda: check_release_a_fixture_effects(mutated_fallback, "mutated sentence fallback fixture"),
        "sentence fallback seek-disabled mutation",
    )
    mutated_fallback = deepcopy(by_case["learning_data_without_word_timestamps"])
    mutated_fallback["expectedEffects"]["wordHighlightEnabled"] = True
    assert_contract_failure(
        lambda: check_release_a_fixture_effects(mutated_fallback, "mutated sentence fallback fixture"),
        "sentence fallback word-highlight mutation",
    )

    error_codes = set(schema(openapi, "APIErrorCode")["enum"]) | set(schema(openapi, "JobErrorCode")["enum"])
    if set(schema(openapi, "APIErrorCode")["enum"]) & set(schema(openapi, "JobErrorCode")["enum"]):
        fail("request-level and job-level error enums must not overlap")
    mapped_codes = set(openapi["x-error-contract"])
    if error_codes != mapped_codes:
        fail(
            "error taxonomy/schema mismatch: "
            f"missing mappings={sorted(error_codes - mapped_codes)!r}, "
            f"extra mappings={sorted(mapped_codes - error_codes)!r}"
        )

    return [
        f"OpenAPI JSON parsed: {OPENAPI_PATH.relative_to(ROOT.parent.parent)}",
        f"Schema/semantic fixtures passed: {len(fixtures)}",
        "Release A transition identity passed: stable jobId/videoId and strictly monotonic timezone-aware updatedAt",
        "Release B exclusions passed: no transcribing schema; transcriptSource=caption; every fixture sttCalls=0",
        f"OpenAPI paths/refs passed: {len(expected_paths)} paths",
        f"Error mappings synchronized: {len(mapped_codes)}",
        f"AC-04 APIError/downstream-zero cases passed: {len(ac04_cases)}",
        "AC-05 passed: in-flight convergence, exact replay, canonical-body conflict, and valid retry owner outcome",
        f"Successful fixture effect oracles passed: {len(successful_cases)}; every fixture audioDownloads=0 and sttCalls=0",
        "7-day success-cache contract read back; purge/runtime evidence NOT RUN (D5)",
        "Frozen pipeline identity passed: release-a-caption-v1; identity changes cannot reuse old cache/owners",
        "Sentence-level fallback passed with empty words arrays",
        "Mutation regressions rejected: success audio download, false caption-stage flag, disabled sentence seek, enabled word highlight, mismatched jobId, non-monotonic updatedAt, AC-04 side effect, retry without owner, timezone-less RFC 3339, transcribing/stt/null/error/words",
    ]


def main() -> int:
    try:
        openapi = load_json(OPENAPI_PATH)
        paths = sorted(FIXTURE_DIR.glob("*.json"))
        if not paths:
            fail("no fixtures found")
        fixtures = [(path, load_json(path)) for path in paths]
        for path, fixture in fixtures:
            check_fixture(fixture, path, openapi)
        evidence = check_package(openapi, fixtures)
    except (ContractFailure, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    print("PASS: SubTube Release A contract readback")
    for item in evidence:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
