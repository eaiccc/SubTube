#!/usr/bin/env python3
"""Dependency-free contract and adversarial readback for SubTube issue #1727."""

from __future__ import annotations

import json
import re
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
RELEASE_A_ROOT = ROOT.parent / "release-a"
OPENAPI_PATH = RELEASE_A_ROOT / "openapi.json"
FIXTURE_DIR = ROOT / "fixtures"
LIFECYCLE_PATH = ROOT / "lifecycle.json"
LIFECYCLE_SCHEMA_PATH = ROOT / "schemas" / "lifecycle.schema.json"
FIXTURES_SCHEMA_PATH = ROOT / "schemas" / "fixtures.schema.json"
PRE_FLIGHT_FIXTURE_PATH = ROOT.parent / "url-preflight" / "fixtures" / "preflight.json"
RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
STATUSES = ["queued", "fetching_captions", "translating", "ready", "failed"]
PROCESSING_STATUSES = STATUSES[:3]
EXPECTED_KINDS = {
    "normal_flow",
    "failure_paths",
    "polling_lifecycle",
    "identity_and_retry",
    "snapshot_ordering",
    "sentence_fallback",
}
EXPECTED_CASES_BY_KIND = {
    "normal_flow": {"preflight_handoff_to_caption_ready"},
    "failure_paths": {
        "queued_can_fail_before_provider_entry",
        "fetching_captions_can_fail",
        "translating_can_fail",
        "malformed_translation_fails_after_one_automatic_retry",
    },
    "polling_lifecycle": {"foreground_poll_background_stop_and_immediate_resume"},
    "identity_and_retry": {
        "unknown_delivery_exact_replay",
        "different_keys_converge_on_inflight_owner",
        "retryable_failure_creates_one_new_owner",
        "concurrent_retry_reuses_newer_owner",
        "ready_dedupe_converges_without_provider_work",
    },
    "snapshot_ordering": {"older_and_equal_conflicting_snapshots_do_not_overwrite"},
    "sentence_fallback": {"caption_document_with_empty_words_remains_ready"},
}
REQUIRED_CASES = {
    "preflight_handoff_to_caption_ready",
    "queued_can_fail_before_provider_entry",
    "fetching_captions_can_fail",
    "translating_can_fail",
    "malformed_translation_fails_after_one_automatic_retry",
    "foreground_poll_background_stop_and_immediate_resume",
    "unknown_delivery_exact_replay",
    "different_keys_converge_on_inflight_owner",
    "retryable_failure_creates_one_new_owner",
    "concurrent_retry_reuses_newer_owner",
    "ready_dedupe_converges_without_provider_work",
    "older_and_equal_conflicting_snapshots_do_not_overwrite",
    "caption_document_with_empty_words_remains_ready",
}
ZERO_PROVIDER_EFFECTS = (
    "audioDownloads",
    "audioDownloadsDelta",
    "audioDownloadsTotal",
    "sttCalls",
    "sttCallsDelta",
    "sttCallsTotal",
)
ZERO_PROVIDER_WORK_EFFECTS = (
    "captionPipelineStartsTotal",
    "captionPipelineStartsDelta",
    "translationCallsTotal",
    "translationCallsDelta",
)
EXPECTED_OPEN_DECISIONS = {"D2-A", "D3-A", "D5-A", "SG-02", "SG-03"}
EXPECTED_NOT_RUN = {
    "API_SERVER_RUNTIME",
    "QUEUE_WORKER_AND_STORE",
    "IOS_POLLING_AND_LIFECYCLE",
    "CAPTION_AND_LLM_PROVIDERS",
    "CONCURRENCY_AND_LOAD",
    "LATENCY_SUCCESS_RATE_AND_COST",
    "CACHE_PURGE_AND_RETENTION",
    "BUILD_DEPLOYMENT_AND_TESTFLIGHT",
}
PIPELINE_VERSION = "release-a-caption-v1"


class ContractFailure(AssertionError):
    """Raised for a contract violation, including a mutation that escaped."""


def fail(message: str) -> None:
    raise ContractFailure(message)


def load_json(path: Path) -> Any:
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


def parse_rfc3339(value: str) -> datetime:
    if not isinstance(value, str) or RFC3339_PATTERN.fullmatch(value) is None:
        raise ValueError("date-time must include T, seconds, and Z or numeric UTC offset")
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
    """Small dependency-free subset of JSON Schema 2020-12 used by this repo."""
    if "$ref" in schema:
        return validate(instance, resolve_ref(document, schema["$ref"]), document, path)

    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None:
        allowed = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(is_type(instance, item) for item in allowed):
            return [f"{path}: expected type {allowed}, got {type(instance).__name__}"]

    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']!r}")

    if isinstance(instance, dict):
        for key in schema.get("required", []):
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
        if schema.get("format") == "date-time":
            try:
                parse_rfc3339(instance)
            except ValueError as error:
                errors.append(f"{path}: invalid RFC 3339 date-time ({error})")

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


def assert_schema_valid(
    instance: Any,
    schema_document: dict[str, Any],
    context: str,
) -> None:
    errors = validate(instance, schema_document, schema_document)
    if errors:
        fail(f"{context} schema validation failed:\n  " + "\n  ".join(errors))


def schema(openapi: dict[str, Any], name: str) -> dict[str, Any]:
    return openapi["components"]["schemas"][name]


def assert_valid(instance: Any, schema_name: str, openapi: dict[str, Any], context: str) -> None:
    errors = validate(instance, schema(openapi, schema_name), openapi)
    if errors:
        fail(f"{context}: schema {schema_name} failed:\n  " + "\n  ".join(errors))


def assert_invalid(instance: Any, schema_name: str, openapi: dict[str, Any], context: str) -> None:
    if not validate(instance, schema(openapi, schema_name), openapi):
        fail(f"{context}: negative mutation unexpectedly passed schema {schema_name}")


def assert_contract_failure(action: Callable[[], Any], context: str) -> None:
    try:
        action()
    except (ContractFailure, KeyError, TypeError, ValueError):
        return
    fail(f"{context}: semantic mutation unexpectedly passed")


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        fail(f"{context}: expected {expected!r}, got {actual!r}")


def check_job(body: dict[str, Any], openapi: dict[str, Any], context: str) -> None:
    assert_valid(body, "ProcessingJob", openapi, context)
    parse_rfc3339(body["updatedAt"])
    status = body["status"]
    if status in PROCESSING_STATUSES:
        require_equal(body["errorCode"], None, f"{context} processing errorCode")
        require_equal(body["errorMessageKey"], None, f"{context} processing errorMessageKey")
        require_equal(body["retryable"], False, f"{context} processing retryable")
        require_equal(body["learningDataPath"], None, f"{context} processing learningDataPath")
    elif status == "ready":
        if not body["learningDataPath"].startswith(f"/v1/videos/{body['videoId']}/learning-data?"):
            fail(f"{context}: ready LearningDocument reference must use the same videoId")
    elif status == "failed":
        if not body["errorCode"] or not body["errorMessageKey"]:
            fail(f"{context}: failed snapshot must expose errorCode and errorMessageKey")
        require_equal(body["learningDataPath"], None, f"{context} failed learningDataPath")
        contract = OPENAPI_ERROR_CONTRACT.get(body["errorCode"])
        if contract:
            if body["errorMessageKey"] != contract["messageKey"]:
                fail(f"{context}: failed errorMessageKey does not match frozen error contract")
            if body["retryable"] != contract["retryable"]:
                fail(f"{context}: failed retryable does not match frozen error contract")


def check_zero_provider_effects(effects: dict[str, Any], context: str) -> None:
    for key in ZERO_PROVIDER_EFFECTS:
        if key in effects and effects[key] != 0:
            fail(f"{context}: {key} must remain zero in Release A, got {effects[key]!r}")


def check_zero_provider_work_effects(effects: dict[str, Any], context: str) -> None:
    for key in ZERO_PROVIDER_WORK_EFFECTS:
        if key in effects and effects[key] != 0:
            fail(f"{context}: {key} must remain zero for the deduped operation, got {effects[key]!r}")


def require_keys(mapping: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(mapping)
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        fail(f"{context}: key set mismatch; missing={sorted(missing)!r}, extra={sorted(extra)!r}")


def require_allowed_keys(mapping: dict[str, Any], allowed: set[str], context: str) -> None:
    extra = set(mapping) - allowed
    if extra:
        fail(f"{context}: unexpected keys {sorted(extra)!r}")


def check_response(response: dict[str, Any], openapi: dict[str, Any], context: str) -> None:
    require_keys(response, {"status", "body"}, f"{context} response wrapper")
    require_equal(response["status"], 202, f"{context} response status")
    assert_valid(response["body"], "ProcessingJob", openapi, f"{context} response body")


def video_id_from_url(url: str, context: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    if not video_id:
        fail(f"{context}: request URL must expose a YouTube video ID")
    return video_id


def expected_dedupe_key(video_id: str) -> str:
    return f"{video_id}|en|zh-Hant-TW|{PIPELINE_VERSION}"


def check_learning_document(
    document: dict[str, Any],
    openapi: dict[str, Any],
    context: str,
    require_empty_words: bool = False,
) -> None:
    assert_valid(document, "LearningDocument", openapi, context)
    require_equal(document["sourceLanguage"], "en", f"{context} sourceLanguage")
    require_equal(document["targetLanguage"], "zh-Hant-TW", f"{context} targetLanguage")
    require_equal(document["pipelineVersion"], PIPELINE_VERSION, f"{context} pipelineVersion")
    require_equal(document["transcriptSource"], "caption", f"{context} transcriptSource")
    for segment in document["segments"]:
        if segment["endTime"] <= segment["startTime"]:
            fail(f"{context}: subtitle segment must have positive duration")
        if require_empty_words and segment["words"]:
            fail(f"{context}: sentence fallback must keep words=[]")


def check_lifecycle(
    lifecycle: dict[str, Any],
    lifecycle_schema: dict[str, Any],
    openapi: dict[str, Any],
) -> list[str]:
    assert_schema_valid(lifecycle, lifecycle_schema, "lifecycle")
    require_equal(lifecycle["$schema"], "./schemas/lifecycle.schema.json", "lifecycle $schema")
    require_equal(lifecycle["issue"], 1727, "lifecycle issue")
    require_equal(lifecycle["release"], "A", "lifecycle release")
    require_equal(lifecycle["stateMachine"]["statuses"], STATUSES, "state status enum")
    require_equal(lifecycle["stateMachine"]["initial"], "queued", "state initial")
    require_equal(lifecycle["stateMachine"]["processing"], PROCESSING_STATUSES, "state processing")
    require_equal(lifecycle["stateMachine"]["terminal"], ["ready", "failed"], "state terminal")
    require_equal(
        lifecycle["stateMachine"]["transitions"],
        {
            "queued": ["fetching_captions", "failed"],
            "fetching_captions": ["translating", "failed"],
            "translating": ["ready", "failed"],
            "ready": [],
            "failed": [],
        },
        "state transition map",
    )
    require_equal(
        lifecycle["stateMachine"]["forbiddenStatuses"],
        ["transcribing"],
        "forbidden status set",
    )
    require_equal(lifecycle["stateMachine"]["sameJobRetryTransition"], False, "same-job retry")
    require_equal(lifecycle["stateMachine"]["cacheHitCreatesTransition"], False, "cache hit transition")

    handoff = lifecycle["preflightHandoff"]
    require_equal(handoff["requiredStatus"], "queued", "preflight handoff status")
    require_equal(handoff["jobCreated"], True, "preflight handoff jobCreated")
    require_equal(handoff["captionPipelineStartsBeforeQueue"], 0, "preflight handoff caption work")
    require_equal(handoff["translationCallsBeforeQueue"], 0, "preflight handoff translation work")
    polling = lifecycle["polling"]
    require_equal(polling["transport"], "HTTP_GET", "polling transport")
    require_equal(polling["intervalSeconds"], 3, "polling interval")
    require_equal(polling["activeOnlyWhen"], ["processing_view_active", "app_foreground", "job_nonterminal"], "polling active guard")
    require_equal(polling["backgroundAction"], "stop_periodic_polling", "background polling action")
    require_equal(polling["foregroundAction"], "immediate_get_then_3s_cadence", "foreground polling action")
    require_equal(polling["getIsReadOnly"], True, "poll GET mutability")
    require_equal(polling["transportFailureMutatesJob"], False, "transport failure mutation")
    require_equal(polling["terminalSnapshotStopsPolling"], True, "terminal polling stop")

    identity = lifecycle["identity"]
    require_equal(
        identity["dedupeKeyFields"],
        ["videoId", "sourceLanguage", "targetLanguage", "pipelineVersion"],
        "dedupe key fields",
    )
    if identity["idempotencyResultMinimumHours"] < 24:
        fail("idempotency result retention must be at least 24 hours")
    require_equal(identity["unknownDeliveryUsesSameKeyAndBody"], True, "unknown delivery replay")
    require_equal(identity["explicitRetryUsesNewKey"], True, "explicit retry key")
    require_equal(identity["activeOwnerMaximum"], 1, "active owner maximum")
    require_equal(identity["failedJobIsSuccessCache"], False, "failed success cache")
    require_equal(identity["updatedAt"]["format"], "RFC3339_TIMEZONE_REQUIRED", "updatedAt format")
    require_equal(identity["updatedAt"]["normalChain"], "strictly_increasing", "updatedAt chain")
    require_equal(identity["updatedAt"]["olderSnapshotAction"], "ignore_stale", "older snapshot action")

    completion = lifecycle["completion"]
    require_equal(completion["wireSchema"], "LearningDocument", "completion wire schema")
    require_equal(completion["referenceField"], "learningDataPath", "completion reference")
    require_equal(completion["transcriptSource"], "caption", "completion transcript source")
    require_equal(completion["sourceLanguage"], "en", "completion source language")
    require_equal(completion["targetLanguage"], "zh-Hant-TW", "completion target language")
    require_equal(completion["wordsRequired"], True, "words field requirement")
    require_equal(completion["emptyWordsAllowed"], True, "empty words allowance")
    require_equal(completion["emptyWordsBehavior"], {
        "documentAccepted": True,
        "sentenceSeekEnabled": True,
        "wordHighlightEnabled": False,
    }, "empty words behavior")

    decision_ids = [item["id"] for item in lifecycle["openDecisions"]]
    if set(decision_ids) != EXPECTED_OPEN_DECISIONS or len(decision_ids) != len(EXPECTED_OPEN_DECISIONS):
        fail(f"#1727 open-decision IDs changed: {decision_ids!r}")
    if any(item["state"] != "OPEN" for item in lifecycle["openDecisions"]):
        fail("all #1727 open decisions must remain OPEN")
    if len(lifecycle["notRun"]) != len(EXPECTED_NOT_RUN) or set(lifecycle["notRun"]) != EXPECTED_NOT_RUN:
        fail(f"#1727 NOT RUN categories changed: {lifecycle['notRun']!r}")
    require_keys(lifecycle["releaseAEffects"], {
        "audioDownloads",
        "sttCalls",
        "pollJobCreates",
        "pollCaptionPipelineStarts",
        "pollTranslationCalls",
        "backgroundJobMutations",
    }, "lifecycle Release A effects")
    if any(value != 0 for value in lifecycle["releaseAEffects"].values()):
        fail("lifecycle Release A effects must all be zero")
    if "transcribing" in json.dumps(schema(openapi, "ProcessingStatus")):
        fail("Release A OpenAPI must not expose transcribing")
    require_equal(schema(openapi, "ProcessingStatus")["enum"], STATUSES, "frozen OpenAPI statuses")
    require_equal(schema(openapi, "LearningDocument")["properties"]["transcriptSource"], {"const": "caption"}, "frozen caption source")
    return [
        "Lifecycle schema/semantic readback passed",
        "Release A status transition map passed; transcribing is forbidden",
        "Preflight queued handoff and no-before-queue side effects passed",
        "3-second read-only polling/background-resume contract passed",
        "Idempotency, dedupe owner, retry, and monotonic snapshot rules passed",
        "LearningDocument caption contract and empty words behavior passed",
    ]


def check_normal_flow(case: dict[str, Any], openapi: dict[str, Any]) -> None:
    require_allowed_keys(case, {"case", "sourcePreflightCase", "snapshots", "workerEffects", "learningDocument"}, "normal flow case")
    snapshots = case["snapshots"]
    expected_statuses = ["queued", "fetching_captions", "translating", "ready"]
    require_equal(
        [item["event"] for item in snapshots],
        ["post_accepted", "poll_fetching_captions", "poll_translating", "poll_ready"],
        "normal event vocabulary",
    )
    require_equal([item["body"]["status"] for item in snapshots], expected_statuses, "normal status chain")
    first = snapshots[0]["body"]
    previous_time = None
    for index, item in enumerate(snapshots):
        require_keys(item, {"event", "body", "expectedEffects"}, f"normal snapshot {index}")
        body = item["body"]
        check_job(body, openapi, f"normal snapshot {index}")
        require_equal(body["jobId"], first["jobId"], f"normal snapshot {index} jobId")
        require_equal(body["videoId"], first["videoId"], f"normal snapshot {index} videoId")
        current_time = parse_rfc3339(body["updatedAt"])
        if previous_time is not None and current_time <= previous_time:
            fail("normal transition updatedAt must be strictly increasing")
        previous_time = current_time
        effects = item["expectedEffects"]
        require_keys(effects, {
            "jobCreatesDelta",
            "captionPipelineStartsDelta",
            "translationCallsDelta",
            "audioDownloadsDelta",
            "sttCallsDelta",
        }, f"normal snapshot {index} effects")
        require_equal(effects["jobCreatesDelta"], 1 if index == 0 else 0, f"normal snapshot {index} jobCreatesDelta")
        for key in ("captionPipelineStartsDelta", "translationCallsDelta", "audioDownloadsDelta", "sttCallsDelta"):
            require_equal(effects[key], 0, f"normal snapshot {index} {key}")
        if index < 3:
            require_equal(body["learningDataPath"], None, f"normal processing snapshot {index} reference")
    ready_path = snapshots[-1]["body"]["learningDataPath"]
    require_equal(ready_path, f"/v1/videos/{first['videoId']}/learning-data?target=zh-Hant-TW", "ready reference")
    require_keys(case["workerEffects"], {
        "activeOwnerMaximum",
        "captionPipelineStartsTotal",
        "translationCallsTotal",
        "readyResultPersistedBeforeReady",
        "audioDownloadsTotal",
        "sttCallsTotal",
    }, "normal worker effects")
    check_zero_provider_effects(case["workerEffects"], "normal worker effects")
    require_equal(case["workerEffects"]["activeOwnerMaximum"], 1, "normal active owner")
    require_equal(case["workerEffects"]["captionPipelineStartsTotal"], 1, "normal caption pipeline total")
    require_equal(case["workerEffects"]["translationCallsTotal"], 1, "normal translation total")
    require_equal(case["workerEffects"]["readyResultPersistedBeforeReady"], True, "ready persistence ordering")
    check_learning_document(case["learningDocument"], openapi, "normal LearningDocument")
    require_equal(case["learningDocument"]["videoId"], first["videoId"], "LearningDocument videoId")


def check_failure_paths(case: dict[str, Any], openapi: dict[str, Any]) -> None:
    for item in case["cases"]:
        require_allowed_keys(item, {
            "case", "fromStatus", "snapshot", "expectedEffects",
            "automaticRetryMaximum", "automaticRetriesUsed",
        }, f"{item.get('case', 'failure')} case")
        from_status = item["fromStatus"]
        if from_status not in PROCESSING_STATUSES:
            fail(f"{item['case']}: failure source must be a processing status")
        snapshot = item["snapshot"]
        check_job(snapshot, openapi, item["case"])
        require_equal(snapshot["status"], "failed", f"{item['case']} status")
        require_equal(snapshot["learningDataPath"], None, f"{item['case']} learning reference")
        effects = item["expectedEffects"]
        require_keys(effects, {
            "successfulCacheWritten",
            "captionPipelineStartsTotal",
            "translationCallsTotal",
            "audioDownloadsTotal",
            "sttCallsTotal",
        }, f"{item['case']} effects")
        require_equal(effects["successfulCacheWritten"], False, f"{item['case']} success cache")
        check_zero_provider_effects(effects, item["case"])
        expected_pipeline = 1 if from_status in {"fetching_captions", "translating"} else 0
        expected_translation = 1 if from_status == "translating" else 0
        require_equal(effects["captionPipelineStartsTotal"], expected_pipeline, f"{item['case']} pipeline count")
        require_equal(effects["translationCallsTotal"], expected_translation if "automaticRetryMaximum" not in item else 2, f"{item['case']} translation count")
        if "automaticRetryMaximum" in item:
            require_equal(item["automaticRetryMaximum"], 1, f"{item['case']} automatic retry maximum")
            require_equal(item["automaticRetriesUsed"], 1, f"{item['case']} automatic retry usage")


def check_polling(case: dict[str, Any]) -> None:
    for item in case["cases"]:
        require_allowed_keys(item, {"case", "jobId", "events", "expected"}, f"{item.get('case', 'polling')} case")
        expected = item["expected"]
        require_keys(expected, {
            "periodicIntervalSeconds",
            "backgroundGetRequests",
            "foregroundResumeDelaySeconds",
            "transportFailureCreatesFailedSnapshot",
            "terminalSnapshotStopsPolling",
        }, f"{item['case']} expected")
        require_equal(
            [event["event"] for event in item["events"]],
            [
                "processing_view_entered",
                "poll_interval_elapsed",
                "app_backgrounded",
                "poll_interval_suppressed",
                "poll_interval_suppressed",
                "app_foregrounded",
                "poll_interval_elapsed",
            ],
            f"{item['case']} event vocabulary",
        )
        require_equal(
            [event["responseStatus"] for event in item["events"]],
            ["queued", "fetching_captions", "fetching_captions", "fetching_captions", "fetching_captions", "translating", "ready"],
            f"{item['case']} response status trace",
        )
        require_equal(
            [event["appState"] for event in item["events"]],
            ["foreground", "foreground", "background", "background", "background", "foreground", "foreground"],
            f"{item['case']} app-state trace",
        )
        require_equal(
            [event["action"] for event in item["events"]],
            [
                "get_job_immediately",
                "get_job",
                "stop_periodic_polling",
                "none",
                "none",
                "get_job_immediately",
                "get_job_and_stop_on_terminal",
            ],
            f"{item['case']} action trace",
        )
        require_equal(expected["periodicIntervalSeconds"], 3, f"{item['case']} interval")
        require_equal(expected["backgroundGetRequests"], 0, f"{item['case']} background requests")
        require_equal(expected["foregroundResumeDelaySeconds"], 0, f"{item['case']} foreground resume")
        require_equal(expected["transportFailureCreatesFailedSnapshot"], False, f"{item['case']} transport failure")
        require_equal(expected["terminalSnapshotStopsPolling"], True, f"{item['case']} terminal stop")
        previous_offset = -1
        cadence_anchor = None
        for event in item["events"]:
            if event["offsetSeconds"] <= previous_offset:
                fail(f"{item['case']}: event offsets must increase")
            previous_offset = event["offsetSeconds"]
            require_keys(event, {
                "offsetSeconds",
                "event",
                "appState",
                "action",
                "responseStatus",
                "expectedEffects",
            }, f"{item['case']} event")
            effects = event["expectedEffects"]
            require_keys(effects, {
                "getRequestsDelta",
                "jobCreatesDelta",
                "jobMutationsDelta",
                "captionPipelineStartsDelta",
                "translationCallsDelta",
                "audioDownloadsDelta",
                "sttCallsDelta",
            }, f"{item['case']} {event['event']} effects")
            for key in ("jobCreatesDelta", "jobMutationsDelta", "captionPipelineStartsDelta", "translationCallsDelta", "audioDownloadsDelta", "sttCallsDelta"):
                require_equal(effects[key], 0, f"{item['case']} {event['event']} {key}")
            if event["event"] == "processing_view_entered":
                require_equal(event["action"], "get_job_immediately", f"{item['case']} initial action")
                require_equal(effects["getRequestsDelta"], 1, f"{item['case']} initial GET")
                cadence_anchor = event["offsetSeconds"]
            elif event["event"] == "app_foregrounded":
                require_equal(event["action"], "get_job_immediately", f"{item['case']} resume action")
                require_equal(effects["getRequestsDelta"], 1, f"{item['case']} resume GET")
                cadence_anchor = event["offsetSeconds"]
            elif event["event"] == "poll_interval_elapsed":
                if cadence_anchor is None or event["offsetSeconds"] - cadence_anchor != 3:
                    fail(f"{item['case']}: periodic GET must occur exactly 3 seconds after its foreground anchor")
                if event["action"] not in {"get_job", "get_job_and_stop_on_terminal"}:
                    fail(f"{item['case']}: periodic action must be get_job or terminal-stop GET")
                require_equal(effects["getRequestsDelta"], 1, f"{item['case']} periodic GET")
                cadence_anchor = event["offsetSeconds"]
            if event["appState"] == "background":
                require_equal(effects["getRequestsDelta"], 0, f"{item['case']} background GET")
                if event["event"] == "app_backgrounded":
                    require_equal(event["action"], "stop_periodic_polling", f"{item['case']} background action")
                cadence_anchor = None
                if event["event"] == "poll_interval_suppressed":
                    require_equal(event["action"], "none", f"{item['case']} suppressed action")
        if item["events"][-1]["responseStatus"] not in {"ready", "failed"}:
            fail(f"{item['case']}: terminal polling fixture must end in ready or failed")
        require_equal(item["events"][-1]["action"], "get_job_and_stop_on_terminal", f"{item['case']} terminal action")


def check_request(request: dict[str, Any], openapi: dict[str, Any], context: str) -> None:
    require_keys(request, {"idempotencyKey", "body"}, f"{context} request wrapper")
    assert_valid(request["body"], "ParseJobRequest", openapi, f"{context} request")
    try:
        uuid.UUID(request["idempotencyKey"])
    except (KeyError, ValueError, AttributeError):
        fail(f"{context}: idempotencyKey must be a UUID")


def check_identity_and_retry(
    case: dict[str, Any],
    openapi: dict[str, Any],
    normal_case: dict[str, Any] | None = None,
) -> None:
    cases = {item["case"]: item for item in case["cases"]}
    replay = cases["unknown_delivery_exact_replay"]
    require_allowed_keys(replay, {"case", "firstRequest", "replayRequest", "firstResponse", "replayResponse", "expectedEffects"}, "exact replay case")
    check_request(replay["firstRequest"], openapi, "exact replay first")
    check_request(replay["replayRequest"], openapi, "exact replay replay")
    require_equal(replay["firstRequest"], replay["replayRequest"], "exact replay request")
    check_response(replay["firstResponse"], openapi, "exact replay first")
    check_response(replay["replayResponse"], openapi, "exact replay replay")
    require_equal(replay["firstResponse"], replay["replayResponse"], "exact replay response")
    require_keys(replay["expectedEffects"], {
        "jobCreatesTotal", "activeOwnerCount", "captionPipelineStartsTotal",
        "translationCallsTotal", "audioDownloadsTotal", "sttCallsTotal",
    }, "exact replay effects")
    require_equal(replay["expectedEffects"]["jobCreatesTotal"], 1, "exact replay job creation")
    require_equal(replay["expectedEffects"]["activeOwnerCount"], 1, "exact replay owner")
    require_equal(replay["expectedEffects"]["captionPipelineStartsTotal"], 0, "exact replay pipeline work")
    require_equal(replay["expectedEffects"]["translationCallsTotal"], 0, "exact replay translation work")
    check_zero_provider_effects(replay["expectedEffects"], "exact replay effects")

    convergence = cases["different_keys_converge_on_inflight_owner"]
    require_allowed_keys(convergence, {"case", "dedupeKey", "ownerRequest", "convergingRequest", "ownerJobId", "returnedJobIds", "expectedEffects"}, "in-flight convergence case")
    check_request(convergence["ownerRequest"], openapi, "in-flight owner")
    check_request(convergence["convergingRequest"], openapi, "in-flight converging")
    owner_video_id = video_id_from_url(convergence["ownerRequest"]["body"]["url"], "in-flight owner")
    converging_video_id = video_id_from_url(convergence["convergingRequest"]["body"]["url"], "in-flight converging")
    require_equal(converging_video_id, owner_video_id, "in-flight canonical video identity")
    require_equal(convergence["dedupeKey"], expected_dedupe_key(owner_video_id), "in-flight dedupe key")
    if convergence["ownerRequest"]["idempotencyKey"] == convergence["convergingRequest"]["idempotencyKey"]:
        fail("in-flight convergence must use different idempotency keys")
    if convergence["ownerRequest"]["body"]["url"] == convergence["convergingRequest"]["body"]["url"]:
        fail("in-flight convergence must prove equivalent but distinct URL forms")
    require_equal(convergence["returnedJobIds"], [convergence["ownerJobId"]] * 2, "in-flight owner identity")
    require_keys(convergence["expectedEffects"], {
        "jobCreatesTotal", "activeOwnerCount", "captionPipelineStartsTotal",
        "translationCallsTotal", "audioDownloadsTotal", "sttCallsTotal",
    }, "in-flight effects")
    require_equal(convergence["expectedEffects"]["jobCreatesTotal"], 1, "in-flight job creation")
    require_equal(convergence["expectedEffects"]["activeOwnerCount"], 1, "in-flight active owner")
    require_equal(convergence["expectedEffects"]["captionPipelineStartsTotal"], 1, "in-flight pipeline start")
    require_equal(convergence["expectedEffects"]["translationCallsTotal"], 0, "in-flight translation work")
    check_zero_provider_effects(convergence["expectedEffects"], "in-flight effects")

    retry = cases["retryable_failure_creates_one_new_owner"]
    require_allowed_keys(retry, {"case", "priorFailedJob", "priorRequest", "retryRequest", "outcome", "returnedJobId", "expectedEffects"}, "retry owner case")
    check_job(retry["priorFailedJob"], openapi, "retry prior failed job")
    require_equal(retry["priorFailedJob"]["status"], "failed", "retry prior status")
    check_request(retry["priorRequest"], openapi, "retry prior request")
    check_request(retry["retryRequest"], openapi, "retry request")
    require_equal(retry["priorRequest"]["body"], retry["retryRequest"]["body"], "retry canonical body")
    if retry["priorRequest"]["idempotencyKey"] == retry["retryRequest"]["idempotencyKey"]:
        fail("explicit retry must use a new idempotency key")
    require_equal(retry["outcome"], "new_job", "retry outcome")
    if retry["returnedJobId"] == retry["priorFailedJob"]["jobId"]:
        fail("explicit retry must not reuse failed job as success")
    require_equal(retry["expectedEffects"]["priorFailedJobReused"], False, "failed job reuse")
    require_equal(retry["expectedEffects"]["newerOwnerCreatesTotal"], 1, "retry owner creation")
    require_equal(retry["expectedEffects"]["newerActiveOwnerCount"], 1, "retry active owner")
    require_keys(retry["expectedEffects"], {
        "priorFailedJobReused", "newerOwnerCreatesTotal", "newerActiveOwnerCount",
        "captionPipelineStartsDelta", "translationCallsDelta", "audioDownloadsTotal", "sttCallsTotal",
    }, "retry effects")
    check_zero_provider_effects(retry["expectedEffects"], "retry effects")
    check_zero_provider_work_effects(retry["expectedEffects"], "retry effects")

    concurrent = cases["concurrent_retry_reuses_newer_owner"]
    require_allowed_keys(concurrent, {"case", "priorFailedJobId", "priorRequest", "retryRequest", "outcome", "returnedJobId", "expectedEffects"}, "concurrent retry case")
    check_request(concurrent["priorRequest"], openapi, "concurrent retry prior")
    check_request(concurrent["retryRequest"], openapi, "concurrent retry request")
    if concurrent["priorRequest"]["idempotencyKey"] == concurrent["retryRequest"]["idempotencyKey"]:
        fail("concurrent retry must use a new idempotency key")
    require_equal(concurrent["outcome"], "reused_newer_owner", "concurrent retry outcome")
    require_equal(concurrent["returnedJobId"], retry["returnedJobId"], "concurrent retry newer owner identity")
    require_equal(concurrent["returnedJobId"] != concurrent["priorFailedJobId"], True, "concurrent retry failed owner exclusion")
    require_equal(concurrent["priorFailedJobId"], retry["priorFailedJob"]["jobId"], "concurrent retry prior owner")
    require_equal(concurrent["priorRequest"]["body"], retry["priorRequest"]["body"], "concurrent retry prior canonical body")
    require_equal(concurrent["retryRequest"]["body"], retry["retryRequest"]["body"], "concurrent retry canonical body")
    require_equal(concurrent["expectedEffects"]["priorFailedJobReused"], False, "concurrent failed reuse")
    require_equal(concurrent["expectedEffects"]["newerOwnerCreatesTotal"], 0, "concurrent owner creation")
    require_equal(concurrent["expectedEffects"]["newerActiveOwnerCount"], 1, "concurrent active owner")
    require_keys(concurrent["expectedEffects"], {
        "priorFailedJobReused", "newerOwnerCreatesTotal", "newerActiveOwnerCount",
        "captionPipelineStartsDelta", "translationCallsDelta", "audioDownloadsTotal", "sttCallsTotal",
    }, "concurrent retry effects")
    check_zero_provider_effects(concurrent["expectedEffects"], "concurrent retry effects")
    check_zero_provider_work_effects(concurrent["expectedEffects"], "concurrent retry effects")

    cache = cases["ready_dedupe_converges_without_provider_work"]
    require_allowed_keys(cache, {"case", "requestKey", "request", "dedupeKey", "returnedJobId", "returnedStatus", "expectedEffects"}, "ready cache case")
    check_request(cache["request"], openapi, "ready cache request")
    require_equal(cache["request"]["idempotencyKey"], cache["requestKey"], "ready cache request key")
    if normal_case is None:
        normal_case = load_json(FIXTURE_DIR / "01-normal-flow.json")["cases"][0]
    ready_snapshot = normal_case["snapshots"][-1]["body"]
    ready_document = normal_case["learningDocument"]
    check_job(ready_snapshot, openapi, "ready cache owner")
    check_learning_document(ready_document, openapi, "ready cache LearningDocument")
    cache_video_id = video_id_from_url(cache["request"]["body"]["url"], "ready cache request")
    require_equal(cache_video_id, ready_snapshot["videoId"], "ready cache video identity")
    require_equal(cache["dedupeKey"], expected_dedupe_key(cache_video_id), "ready cache dedupe key")
    require_equal(ready_snapshot["videoId"], ready_document["videoId"], "ready cache document video identity")
    require_equal(ready_document["pipelineVersion"], PIPELINE_VERSION, "ready cache document pipeline identity")
    require_equal(ready_snapshot["learningDataPath"], f"/v1/videos/{ready_document['videoId']}/learning-data?target=zh-Hant-TW", "ready cache document reference")
    require_equal(cache["returnedStatus"], ready_snapshot["status"], "ready cache status")
    require_equal(cache["returnedJobId"], ready_snapshot["jobId"], "ready cache job")
    require_keys(cache["expectedEffects"], {
        "jobCreatesDelta", "activeOwnerCount", "captionPipelineStartsDelta",
        "translationCallsDelta", "audioDownloadsDelta", "sttCallsDelta",
    }, "ready cache effects")
    require_equal(cache["expectedEffects"]["activeOwnerCount"], 0, "ready cache active owner")
    require_equal(cache["expectedEffects"]["jobCreatesDelta"], 0, "ready cache job creation")
    check_zero_provider_effects(cache["expectedEffects"], "ready cache effects")
    check_zero_provider_work_effects(cache["expectedEffects"], "ready cache effects")


def check_snapshot_ordering(case: dict[str, Any], openapi: dict[str, Any]) -> None:
    require_allowed_keys(case["cases"][0], {"case", "acceptedSnapshot", "arrivals", "expectedEffects"}, "snapshot ordering case")
    accepted = case["cases"][0]["acceptedSnapshot"]
    check_job(accepted, openapi, "accepted snapshot")
    accepted_time = parse_rfc3339(accepted["updatedAt"])
    previous_time = None
    expected_actions = ["ignore_stale", "log_invariant_violation_and_ignore", "accept_newer"]
    expected_arrival_statuses = ["fetching_captions", "translating", "ready"]
    arrivals = case["cases"][0]["arrivals"]
    require_equal(len(arrivals), len(expected_actions), "snapshot arrival cardinality")
    for index, arrival in enumerate(arrivals):
        require_keys(arrival, {"snapshot", "expectedAction", "visibleStatusAfter"}, f"arrival {index}")
        snapshot = arrival["snapshot"]
        check_job(snapshot, openapi, f"arrival {index}")
        require_equal(snapshot["jobId"], accepted["jobId"], f"arrival {index} jobId")
        require_equal(snapshot["videoId"], accepted["videoId"], f"arrival {index} videoId")
        current_time = parse_rfc3339(snapshot["updatedAt"])
        if previous_time is not None and current_time <= previous_time:
            fail("snapshot arrival timestamps must be strictly increasing in fixture order")
        previous_time = current_time
        require_equal(arrival["expectedAction"], expected_actions[index], f"arrival {index} action")
        if index == 0 and current_time >= accepted_time:
            fail("older snapshot fixture must predate accepted snapshot")
        if index == 1 and current_time != accepted_time:
            fail("equal conflicting snapshot fixture must share accepted timestamp")
        if index == 1 and snapshot == accepted:
            fail("equal-timestamp arrival must conflict with the accepted payload")
        if index == 2 and current_time <= accepted_time:
            fail("newer snapshot fixture must be later than accepted snapshot")
        require_equal(snapshot["status"], expected_arrival_statuses[index], f"arrival {index} status")
        expected_visible_status = accepted["status"] if index < 2 else snapshot["status"]
        require_equal(arrival["visibleStatusAfter"], expected_visible_status, f"arrival {index} visible status")
    require_keys(case["cases"][0]["expectedEffects"], {
        "postRequestsDelta", "jobCreatesDelta", "captionPipelineStartsDelta",
        "translationCallsDelta", "audioDownloadsDelta", "sttCallsDelta",
    }, "snapshot ordering effects")
    effects = case["cases"][0]["expectedEffects"]
    require_equal(effects["postRequestsDelta"], 0, "snapshot ordering POST effects")
    require_equal(effects["jobCreatesDelta"], 0, "snapshot ordering job creation effects")
    check_zero_provider_work_effects(effects, "snapshot ordering effects")
    check_zero_provider_effects(effects, "snapshot ordering effects")


def check_sentence_fallback(
    case: dict[str, Any],
    openapi: dict[str, Any],
    expected_video_id: str | None = None,
) -> None:
    item = case["cases"][0]
    require_allowed_keys(item, {"case", "learningDataPath", "document", "expectedEffects"}, "sentence fallback case")
    check_learning_document(item["document"], openapi, item["case"], require_empty_words=True)
    document_video_id = item["document"]["videoId"]
    if expected_video_id is not None:
        require_equal(document_video_id, expected_video_id, "fallback owner video identity")
    require_equal(
        item["learningDataPath"],
        f"/v1/videos/{document_video_id}/learning-data?target=zh-Hant-TW",
        "fallback reference identity",
    )
    effects = item["expectedEffects"]
    require_keys(effects, {
        "documentAccepted", "sentenceSeekEnabled", "wordHighlightEnabled",
        "audioDownloadsDelta", "sttCallsDelta",
    }, "fallback effects")
    require_equal(effects["documentAccepted"], True, "fallback document acceptance")
    require_equal(effects["sentenceSeekEnabled"], True, "fallback sentence seek")
    require_equal(effects["wordHighlightEnabled"], False, "fallback word highlight")
    check_zero_provider_effects(effects, "fallback effects")


def load_package() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    lifecycle = load_json(LIFECYCLE_PATH)
    lifecycle_schema = load_json(LIFECYCLE_SCHEMA_PATH)
    fixtures_schema = load_json(FIXTURES_SCHEMA_PATH)
    openapi = load_json(OPENAPI_PATH)
    fixtures = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        fixture = load_json(path)
        assert_schema_valid(fixture, fixtures_schema, path.name)
        fixtures.append(fixture)
    if len(fixtures) != 6:
        fail(f"expected six fixture collections, got {len(fixtures)}")
    return lifecycle, lifecycle_schema, fixtures_schema, openapi, fixtures


def check_fixture_package(
    fixtures: list[dict[str, Any]],
    openapi: dict[str, Any],
) -> list[str]:
    by_kind = {fixture["kind"]: fixture for fixture in fixtures}
    if set(by_kind) != EXPECTED_KINDS:
        fail(f"fixture kind set mismatch: {sorted(set(by_kind))!r}")
    for kind, fixture in by_kind.items():
        case_names = [case["case"] for case in fixture["cases"]]
        expected_case_names = EXPECTED_CASES_BY_KIND[kind]
        if len(case_names) != len(expected_case_names) or set(case_names) != expected_case_names:
            fail(f"{kind} semantic case set mismatch: {case_names!r}")
    all_cases = [case["case"] for fixture in fixtures for case in fixture["cases"]]
    if len(all_cases) != len(set(all_cases)):
        fail("fixture case names must be unique")
    missing = REQUIRED_CASES - set(all_cases)
    if missing:
        fail(f"required #1727 cases missing: {sorted(missing)!r}")

    normal_case = by_kind["normal_flow"]["cases"][0]
    check_normal_flow(normal_case, openapi)
    check_failure_paths(by_kind["failure_paths"], openapi)
    check_polling(by_kind["polling_lifecycle"])
    check_identity_and_retry(by_kind["identity_and_retry"], openapi, normal_case)
    check_snapshot_ordering(by_kind["snapshot_ordering"], openapi)
    normal_video_id = normal_case["snapshots"][-1]["body"]["videoId"]
    check_sentence_fallback(by_kind["sentence_fallback"], openapi, normal_video_id)

    preflight = load_json(PRE_FLIGHT_FIXTURE_PATH)
    preflight_case = by_kind["normal_flow"]["cases"][0]["sourcePreflightCase"]
    matching = [item for item in preflight.get("cases", []) if item.get("case") == preflight_case]
    if len(matching) != 1:
        fail(f"#1725 accepted preflight fixture is missing source case {preflight_case!r}")
    accepted = matching[0]
    require_equal(accepted["expected"]["accepted"], True, "AC-01 source preflight acceptance")
    require_equal(accepted["expected"]["response"]["status"], 202, "AC-01 source preflight status")
    require_equal(accepted["expected"]["response"]["bodySchema"], "ProcessingJob", "AC-01 source body schema")
    require_equal(accepted["expected"]["response"]["body"]["status"], "queued", "AC-01 source queued status")
    source_body = accepted["expected"]["response"]["body"]
    normal_first = by_kind["normal_flow"]["cases"][0]["snapshots"][0]["body"]
    require_equal(normal_first["jobId"], source_body["jobId"], "AC-01 handoff job identity")
    require_equal(normal_first["videoId"], source_body["videoId"], "AC-01 handoff video identity")
    require_equal(accepted["expectedEffects"]["jobCreated"], True, "AC-01 source job creation")
    require_equal(accepted["expectedEffects"]["jobIdReturned"], True, "AC-01 source job identity returned")
    require_equal(accepted["expectedEffects"]["captionPipelineStarts"], 0, "AC-01 source caption side effect")
    require_equal(accepted["expectedEffects"]["translationCalls"], 0, "AC-01 source translation side effect")
    return [
        f"Fixture collections passed: {len(fixtures)}; semantic cases: {len(all_cases)}",
        "AC-01 queued → fetching_captions → translating → ready chain passed",
        "Processing-stage failure snapshots passed with error fields and retry semantics",
        "AC-05 polling passed: 3-second cadence, background stop, immediate foreground resume",
        "AC-05 idempotency replay, in-flight convergence, retry owner, and ready cache passed",
        "Monotonic/stale/equal snapshot ordering passed",
        "Sentence-level learning document fallback passed with words=[] and seek enabled",
    ]


def run_mutation_regressions(
    lifecycle: dict[str, Any],
    lifecycle_schema: dict[str, Any],
    openapi: dict[str, Any],
    fixtures: list[dict[str, Any]],
) -> list[str]:
    by_kind = {fixture["kind"]: fixture for fixture in fixtures}
    mutations: list[tuple[str, Callable[[], Any]]] = []

    mutated = deepcopy(lifecycle)
    mutated["stateMachine"]["transitions"]["queued"] = ["ready"]
    mutations.append(("queued-to-ready transition", lambda mutated=mutated: check_lifecycle(mutated, lifecycle_schema, openapi)))

    mutated = deepcopy(lifecycle)
    mutated["stateMachine"]["statuses"].append("transcribing")
    mutations.append(("transcribing status admission", lambda mutated=mutated: check_lifecycle(mutated, lifecycle_schema, openapi)))

    mutated = deepcopy(lifecycle)
    mutated["polling"]["intervalSeconds"] = 5
    mutations.append(("lifecycle polling interval", lambda mutated=mutated: check_lifecycle(mutated, lifecycle_schema, openapi)))

    mutated = deepcopy(by_kind["normal_flow"]["cases"][0])
    mutated["snapshots"][2]["body"]["jobId"] = "job-mutated"
    mutations.append(("normal job identity", lambda mutated=mutated: check_normal_flow(mutated, openapi)))

    mutated = deepcopy(by_kind["normal_flow"]["cases"][0])
    mutated["snapshots"][2]["body"]["updatedAt"] = mutated["snapshots"][1]["body"]["updatedAt"]
    mutations.append(("normal non-monotonic updatedAt", lambda mutated=mutated: check_normal_flow(mutated, openapi)))

    mutated = deepcopy(by_kind["failure_paths"])
    mutated["cases"][1]["snapshot"]["errorCode"] = None
    mutations.append(("failed snapshot missing errorCode", lambda mutated=mutated: check_failure_paths(mutated, openapi)))

    mutated = deepcopy(by_kind["polling_lifecycle"])
    mutated["cases"][0]["expected"]["periodicIntervalSeconds"] = 4
    mutations.append(("poll interval", lambda mutated=mutated: check_polling(mutated)))

    mutated = deepcopy(by_kind["polling_lifecycle"])
    mutated["cases"][0]["events"][2]["action"] = "get_job"
    mutations.append(("background polling action", lambda mutated=mutated: check_polling(mutated)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][1]["returnedJobIds"][1] = "job-other"
    mutations.append(("in-flight owner convergence", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][2]["retryRequest"]["idempotencyKey"] = mutated["cases"][2]["priorRequest"]["idempotencyKey"]
    mutations.append(("explicit retry key reuse", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["snapshot_ordering"])
    mutated["cases"][0]["arrivals"][0]["expectedAction"] = "accept_newer"
    mutations.append(("stale snapshot overwrite", lambda mutated=mutated: check_snapshot_ordering(mutated, openapi)))

    mutated = deepcopy(by_kind["sentence_fallback"])
    mutated["cases"][0]["expectedEffects"]["wordHighlightEnabled"] = True
    mutations.append(("word highlight fallback", lambda mutated=mutated: check_sentence_fallback(mutated, openapi)))

    mutated = deepcopy(by_kind["sentence_fallback"])
    mutated["cases"][0]["document"]["segments"][0]["words"] = [{
        "id": "word-1", "word": "Sentence", "start": 0, "end": 0.5
    }]
    mutations.append(("non-empty word fallback", lambda mutated=mutated: check_sentence_fallback(mutated, openapi)))

    mutated = deepcopy(by_kind["normal_flow"]["cases"][0])
    mutated["snapshots"][0]["expectedEffects"]["audioDownloadsDelta"] = 1
    mutations.append(("caption path audio side effect", lambda mutated=mutated: check_normal_flow(mutated, openapi)))

    mutated = deepcopy(by_kind["normal_flow"]["cases"][0])
    mutated["workerEffects"]["audioDownloadsTotal"] = 1
    mutations.append(("caption path audio total side effect", lambda mutated=mutated: check_normal_flow(mutated, openapi)))

    mutated = deepcopy(by_kind["failure_paths"])
    mutated["cases"][1]["expectedEffects"]["sttCallsTotal"] = 1
    mutations.append(("failure path STT total side effect", lambda mutated=mutated: check_failure_paths(mutated, openapi)))

    mutated = deepcopy(by_kind["polling_lifecycle"])
    mutated["cases"][0]["events"][1]["offsetSeconds"] = 2
    mutations.append(("actual two-second polling cadence", lambda mutated=mutated: check_polling(mutated)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][3]["returnedJobId"] = "job-unrelated"
    mutations.append(("concurrent retry unrelated owner", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["snapshot_ordering"])
    mutated["cases"][0]["arrivals"][0]["visibleStatusAfter"] = "fetching_captions"
    mutations.append(("stale visible state overwrite", lambda mutated=mutated: check_snapshot_ordering(mutated, openapi)))

    mutated = deepcopy(by_kind["failure_paths"])
    mutated["cases"][0]["snapshot"]["retryable"] = True
    mutations.append(("failed retryability contract drift", lambda mutated=mutated: check_failure_paths(mutated, openapi)))

    mutated = deepcopy(lifecycle)
    mutated["openDecisions"] = mutated["openDecisions"][:-1]
    mutations.append(("required open decision deletion", lambda mutated=mutated: check_lifecycle(mutated, lifecycle_schema, openapi)))

    mutated = deepcopy(lifecycle)
    mutated["notRun"] = ["UNRELATED_ONLY"]
    mutations.append(("required NOT RUN category deletion", lambda mutated=mutated: check_lifecycle(mutated, lifecycle_schema, openapi)))

    mutated = deepcopy(lifecycle)
    mutated["releaseAEffects"]["apiKeyExposedToClient"] = True
    mutations.append(("unknown security/effect field", lambda mutated=mutated: check_lifecycle(mutated, lifecycle_schema, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    normal_fixture = next(item for item in mutated_fixtures if item["kind"] == "normal_flow")
    normal_fixture["cases"][0]["unknownSecurityBoundary"] = True
    mutations.append(("unknown fixture case security field", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    normal_fixture = next(item for item in mutated_fixtures if item["kind"] == "normal_flow")
    normal_fixture["cases"][0]["snapshots"][1]["unknownEffect"] = {"audioDownloads": 7}
    mutations.append(("unknown snapshot wrapper effect field", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    polling_fixture = next(item for item in mutated_fixtures if item["kind"] == "polling_lifecycle")
    shadow_event = deepcopy(polling_fixture["cases"][0]["events"][1])
    shadow_event["event"] = "shadow_poll"
    shadow_event["offsetSeconds"] = 2
    polling_fixture["cases"][0]["events"].insert(1, shadow_event)
    mutations.append(("unknown polling event", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    polling_fixture = next(item for item in mutated_fixtures if item["kind"] == "polling_lifecycle")
    polling_fixture["cases"][0]["events"][1]["event"] = "shadow_poll"
    polling_fixture["cases"][0]["events"][1]["offsetSeconds"] = 2
    mutations.append(("renamed two-second polling event", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    polling_fixture = next(item for item in mutated_fixtures if item["kind"] == "polling_lifecycle")
    polling_fixture["cases"][0]["events"][1]["responseStatus"] = "transcribing"
    mutations.append(("polling transcribing response", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    polling_fixture = next(item for item in mutated_fixtures if item["kind"] == "polling_lifecycle")
    del polling_fixture["cases"][0]["events"][1]["responseStatus"]
    mutations.append(("polling missing response status", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    polling_fixture = next(item for item in mutated_fixtures if item["kind"] == "polling_lifecycle")
    polling_fixture["cases"][0]["events"].append(deepcopy(polling_fixture["cases"][0]["events"][-1]))
    mutations.append(("polling after terminal", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][3]["retryRequest"]["body"]["url"] = "https://youtu.be/OtherVideo01"
    mutations.append(("concurrent retry cross-video body", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    normal_fixture = next(item for item in mutated_fixtures if item["kind"] == "normal_flow")
    normal_fixture["cases"][0]["sourcePreflightCase"] = "captions_unavailable_is_release_a_4xx"
    mutations.append(("rejected preflight handoff", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated = deepcopy(lifecycle)
    mutated["polling"]["activeOnlyWhen"].remove("job_nonterminal")
    mutations.append(("missing nonterminal polling guard", lambda mutated=mutated: check_lifecycle(mutated, lifecycle_schema, openapi)))

    mutated = deepcopy(lifecycle)
    mutated["notRun"].append("API_SERVER_RUNTIME")
    mutations.append(("duplicate NOT RUN category", lambda mutated=mutated: check_lifecycle(mutated, lifecycle_schema, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    polling_fixture = next(item for item in mutated_fixtures if item["kind"] == "polling_lifecycle")
    polling_fixture["cases"][0]["events"][1]["unknownEventField"] = True
    mutations.append(("unknown legal polling event field", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][0]["expectedEffects"]["captionPipelineStartsTotal"] = 1
    mutations.append(("replay caption provider work", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][0]["expectedEffects"]["translationCallsTotal"] = 1
    mutations.append(("replay translation provider work", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][1]["expectedEffects"]["translationCallsTotal"] = 1
    mutations.append(("in-flight translation provider work", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][2]["expectedEffects"]["captionPipelineStartsDelta"] = 1
    mutations.append(("retry caption provider work", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][2]["expectedEffects"]["translationCallsDelta"] = 1
    mutations.append(("retry translation provider work", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][3]["expectedEffects"]["captionPipelineStartsDelta"] = 1
    mutations.append(("concurrent retry caption provider work", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][3]["expectedEffects"]["translationCallsDelta"] = 1
    mutations.append(("concurrent retry translation provider work", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][4]["expectedEffects"]["captionPipelineStartsDelta"] = 1
    mutations.append(("ready cache caption provider work", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][4]["expectedEffects"]["translationCallsDelta"] = 1
    mutations.append(("ready cache translation provider work", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    identity_fixture = next(item for item in mutated_fixtures if item["kind"] == "identity_and_retry")
    identity_fixture["cases"].append({"case": "unmodeled_semantic_case"})
    mutations.append(("unvalidated semantic case", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    identity_fixture = next(item for item in mutated_fixtures if item["kind"] == "identity_and_retry")
    identity_fixture["cases"][0]["firstRequest"]["unknownRequestField"] = True
    mutations.append(("unknown replay request wrapper field", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated_fixtures = deepcopy(fixtures)
    identity_fixture = next(item for item in mutated_fixtures if item["kind"] == "identity_and_retry")
    identity_fixture["cases"][0]["replayResponse"]["unknownResponseField"] = True
    mutations.append(("unknown replay response wrapper field", lambda mutated_fixtures=mutated_fixtures: check_fixture_package(mutated_fixtures, openapi)))

    mutated = deepcopy(by_kind["polling_lifecycle"])
    mutated["cases"][0]["events"][3]["appState"] = "foreground"
    mutations.append(("suppressed polling foreground state", lambda mutated=mutated: check_polling(mutated)))

    mutated = deepcopy(by_kind["snapshot_ordering"])
    mutated["cases"][0]["expectedEffects"]["captionPipelineStartsDelta"] = 1
    mutations.append(("snapshot ordering caption provider work", lambda mutated=mutated: check_snapshot_ordering(mutated, openapi)))

    mutated = deepcopy(by_kind["snapshot_ordering"])
    mutated["cases"][0]["expectedEffects"]["translationCallsDelta"] = 1
    mutations.append(("snapshot ordering translation provider work", lambda mutated=mutated: check_snapshot_ordering(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][4]["requestKey"] = "not-a-uuid"
    mutations.append(("ready cache invalid request key", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][1]["dedupeKey"] = "OtherVideo|en|zh-Hant-TW|release-a-caption-v1"
    mutations.append(("in-flight unrelated dedupe key", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["identity_and_retry"])
    mutated["cases"][4]["dedupeKey"] = "OtherVideo|en|zh-Hant-TW|release-a-caption-v1"
    mutations.append(("ready cache unrelated dedupe key", lambda mutated=mutated: check_identity_and_retry(mutated, openapi)))

    mutated = deepcopy(by_kind["normal_flow"]["cases"][0])
    mutated["learningDocument"]["pipelineVersion"] = "other-pipeline"
    mutations.append(("normal document pipeline drift", lambda mutated=mutated: check_normal_flow(mutated, openapi)))

    mutated_identity = deepcopy(by_kind["identity_and_retry"])
    mutated_normal = deepcopy(by_kind["normal_flow"]["cases"][0])
    mutated_normal["learningDocument"]["pipelineVersion"] = "other-pipeline"
    mutations.append(("ready cache document pipeline drift", lambda mutated_identity=mutated_identity, mutated_normal=mutated_normal: check_identity_and_retry(mutated_identity, openapi, mutated_normal)))

    mutated = deepcopy(by_kind["snapshot_ordering"])
    mutated["cases"][0]["arrivals"][1]["snapshot"] = deepcopy(mutated["cases"][0]["acceptedSnapshot"])
    mutations.append(("equal snapshot missing conflict", lambda mutated=mutated: check_snapshot_ordering(mutated, openapi)))

    mutated = deepcopy(by_kind["snapshot_ordering"])
    mutated["cases"][0]["arrivals"].pop()
    mutations.append(("snapshot ordering missing newer arrival", lambda mutated=mutated: check_snapshot_ordering(mutated, openapi)))

    mutated = deepcopy(by_kind["normal_flow"]["cases"][0])
    mutated["snapshots"][2]["event"] = "renamed_translation_poll"
    mutations.append(("normal event vocabulary drift", lambda mutated=mutated: check_normal_flow(mutated, openapi)))

    fallback_owner = by_kind["normal_flow"]["cases"][0]["snapshots"][-1]["body"]["videoId"]
    mutated = deepcopy(by_kind["sentence_fallback"])
    mutated["cases"][0]["document"]["videoId"] = "OtherVideo01"
    mutations.append(("sentence fallback cross-video document identity", lambda mutated=mutated, fallback_owner=fallback_owner: check_sentence_fallback(mutated, openapi, fallback_owner)))

    mutated = deepcopy(by_kind["sentence_fallback"])
    mutated["cases"][0]["learningDataPath"] = "/v1/videos/OtherVideo01/learning-data?target=zh-Hant-TW"
    mutations.append(("sentence fallback cross-video path identity", lambda mutated=mutated, fallback_owner=fallback_owner: check_sentence_fallback(mutated, openapi, fallback_owner)))

    mutated = deepcopy(lifecycle)
    mutated["stateMachine"]["forbiddenStatuses"].append("transcribing")
    mutations.append(("duplicate forbidden status", lambda mutated=mutated: check_lifecycle(mutated, lifecycle_schema, openapi)))

    for name, action in mutations:
        assert_contract_failure(action, name)
    return [f"Mutation regressions rejected: {len(mutations)} / {len(mutations)} escaped=0"]


def main() -> int:
    global OPENAPI_ERROR_CONTRACT
    try:
        lifecycle, lifecycle_schema, _fixtures_schema, openapi, fixtures = load_package()
        OPENAPI_ERROR_CONTRACT = openapi.get("x-error-contract", {})
        evidence = check_lifecycle(lifecycle, lifecycle_schema, openapi)
        evidence.extend(check_fixture_package(fixtures, openapi))
        evidence.extend(run_mutation_regressions(lifecycle, lifecycle_schema, openapi, fixtures))
        print("PASS: SubTube #1727 caption job lifecycle contract readback")
        for item in evidence:
            print(f"- {item}")
        print("- Runtime/API/queue/iOS/provider/latency/load/quality/retention/deployment evidence: NOT RUN")
        return 0
    except (ContractFailure, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


OPENAPI_ERROR_CONTRACT: dict[str, Any] = {}


if __name__ == "__main__":
    raise SystemExit(main())
