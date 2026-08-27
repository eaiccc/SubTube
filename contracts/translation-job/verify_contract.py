#!/usr/bin/env python3
"""Dependency-free contract and mutation readback for SubTube issue #1718."""

from __future__ import annotations

import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
CONTRACT_PATH = ROOT / "contract.json"
CONTRACT_SCHEMA_PATH = ROOT / "schemas" / "contract.schema.json"
INPUT_SCHEMA_PATH = ROOT / "schemas" / "translation-input.schema.json"
OUTPUT_SCHEMA_PATH = ROOT / "schemas" / "translation-output.schema.json"
FIXTURE_DIR = ROOT / "fixtures"
RELEASE_A_ROOT = ROOT.parent / "release-a"
OPENAPI_PATH = RELEASE_A_ROOT / "openapi.json"
RELEASE_A_VERIFIER_PATH = RELEASE_A_ROOT / "verify_contract.py"
DECISION_LEDGER_PATH = ROOT.parent / "release-a-gates" / "fixtures" / "decision-ledger.json"

PIPELINE_VERSION = "release-a-caption-v1"
LEGACY_PIPELINE_VERSION = "caption-v1+translation-v1"
EXPECTED_KINDS = {"success", "invalid_response", "provider_failure", "pipeline_identity"}
EXPECTED_CASES = {
    "valid_first_attempt_produces_ready_learning_document",
    "first_malformed_json_retries_once_then_ready",
    "second_invalid_response_fails_without_success_cache",
    "provider_timeout_uses_existing_retryable_failure_semantics",
    "pipeline_change_does_not_reuse_legacy_success_cache",
}
EFFECT_KEYS = {
    "translationCallsTotal",
    "automaticRetriesUsed",
    "successfulCacheWritten",
    "readyResultPersisted",
    "cacheHit",
    "legacyCacheReused",
    "audioDownloads",
    "sttCalls",
    "statusTrace",
}
NOT_RUN = [
    "API_SERVER_AND_QUEUE_RUNTIME",
    "OPENAI_PROVIDER_EXECUTION",
    "CAPTION_PROVIDER_EXECUTION",
    "BILLING_AND_COST_METERING",
    "LATENCY_CONCURRENCY_AND_LOAD",
    "TRANSLATION_QUALITY_AND_STAGING",
    "IOS_BUILD_AND_INTEGRATION",
    "DEPLOYMENT_AND_TESTFLIGHT",
]


class ContractFailure(AssertionError):
    """Raised when contract readback or an adversarial probe escapes."""


def fail(message: str) -> None:
    raise ContractFailure(message)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"{path}: cannot read valid JSON: {error}")
    if not isinstance(value, dict):
        fail(f"{path}: JSON root must be an object")
    return value


def load_release_a_verifier() -> Any:
    spec = importlib.util.spec_from_file_location("release_a_contract_for_translation", RELEASE_A_VERIFIER_PATH)
    if spec is None or spec.loader is None:
        fail(f"cannot load Release A verifier: {RELEASE_A_VERIFIER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RELEASE_A = load_release_a_verifier()


def require_equal(actual: Any, expected: Any, context: str) -> None:
    if not RELEASE_A.json_const_equal(actual, expected):
        fail(f"{context}: expected {expected!r}, got {actual!r}")


def require_keys(mapping: dict[str, Any], expected: set[str], context: str) -> None:
    if not isinstance(mapping, dict):
        fail(f"{context}: expected object")
    actual = set(mapping)
    if actual != expected:
        fail(
            f"{context}: key set mismatch; "
            f"missing={sorted(expected - actual)!r}, extra={sorted(actual - expected)!r}"
        )


def schema_errors(instance: Any, schema_document: dict[str, Any]) -> list[str]:
    return RELEASE_A.validate(instance, schema_document, schema_document)


def assert_schema(instance: Any, schema_document: dict[str, Any], context: str) -> None:
    errors = schema_errors(instance, schema_document)
    if errors:
        fail(f"{context}: schema failed:\n  " + "\n  ".join(errors))


def dedupe_key(video_id: str) -> str:
    return f"{video_id}|en|zh-Hant-TW|{PIPELINE_VERSION}"


def check_timeline(segments: list[dict[str, Any]], context: str) -> None:
    ids: set[str] = set()
    previous_start: float | None = None
    previous_end: float | None = None
    for index, segment in enumerate(segments):
        segment_id = segment["segmentId"]
        if segment_id in ids:
            fail(f"{context}: duplicate segmentId {segment_id!r}")
        ids.add(segment_id)
        start = segment["startTime"]
        end = segment["endTime"]
        if start < 0 or end <= start:
            fail(f"{context}[{index}]: segment requires 0 <= startTime < endTime")
        if previous_start is not None and start <= previous_start:
            fail(f"{context}[{index}]: startTime must be strictly increasing")
        if previous_end is not None and start < previous_end:
            fail(f"{context}[{index}]: segments must not overlap")
        previous_start = start
        previous_end = end


def check_input(value: dict[str, Any], input_schema: dict[str, Any], context: str) -> None:
    assert_schema(value, input_schema, context)
    check_timeline(value["segments"], f"{context}.segments")


def output_validation_errors(
    value: Any,
    source: dict[str, Any],
    output_schema: dict[str, Any],
) -> list[str]:
    errors = schema_errors(value, output_schema)
    if errors or not isinstance(value, dict):
        return errors or ["output must be an object"]
    try:
        check_timeline(value["segments"], "translation output segments")
    except (ContractFailure, KeyError, TypeError) as error:
        errors.append(str(error))
        return errors
    if len(value["segments"]) != len(source["segments"]):
        errors.append("segment count drift")
        return errors
    for index, (source_segment, translated_segment) in enumerate(zip(source["segments"], value["segments"])):
        if translated_segment["segmentId"] != source_segment["segmentId"]:
            errors.append(f"segment {index} ID/order drift")
        if translated_segment["startTime"] != source_segment["startTime"]:
            errors.append(f"segment {index} startTime drift")
        if translated_segment["endTime"] != source_segment["endTime"]:
            errors.append(f"segment {index} endTime drift")
    return errors


def build_learning_document(
    video_id: str,
    source: dict[str, Any],
    translated: dict[str, Any],
) -> dict[str, Any]:
    return {
        "videoId": video_id,
        "sourceLanguage": "en",
        "targetLanguage": "zh-Hant-TW",
        "pipelineVersion": PIPELINE_VERSION,
        "transcriptSource": "caption",
        "segments": [
            {
                "id": source_segment["segmentId"],
                "startTime": source_segment["startTime"],
                "endTime": source_segment["endTime"],
                "originalText": source_segment["originalText"],
                "translatedText": translated_segment["translation"],
                "words": [],
            }
            for source_segment, translated_segment in zip(source["segments"], translated["segments"])
        ],
    }


def check_frozen_oracle(
    contract: dict[str, Any],
    contract_schema: dict[str, Any],
    ledger: dict[str, Any],
    openapi: dict[str, Any],
) -> None:
    if not schema_errors(1, {"const": True}):
        fail("dependency-free const validation must reject integer 1 for boolean true")
    if not schema_errors(0, {"const": False}):
        fail("dependency-free const validation must reject integer 0 for boolean false")
    assert_schema(contract, contract_schema, "translation contract")
    config = ledger["releaseAConfig"]
    translation = config["translation"]
    adapter = contract["adapter"]
    oracle_pairs = [
        (config["pipelineVersion"], PIPELINE_VERSION, "ledger pipelineVersion"),
        (contract["pipelineIdentity"]["pipelineVersion"], PIPELINE_VERSION, "contract pipelineVersion"),
        (adapter["provider"], translation["provider"], "provider"),
        (adapter["endpoint"], translation["endpoint"], "endpoint"),
        (adapter["modelSnapshot"], translation["modelSnapshot"], "model snapshot"),
        (adapter["reasoningEffort"], translation["reasoningEffort"], "reasoning effort"),
        (adapter["structuredOutputs"], translation["structuredOutputs"], "Structured Outputs"),
        (adapter["inputTokenBudgetPerAttempt"], translation["aggregateTokenBudgetPerAttempt"]["input"], "input token budget"),
        (adapter["outputTokenBudgetPerAttempt"], translation["aggregateTokenBudgetPerAttempt"]["output"], "output token budget"),
        (adapter["timeoutMs"], config["timeoutsMs"]["llmAttempt"], "LLM timeout"),
        (contract["retryPolicy"]["maxAutomaticRetries"], translation["maxAutomaticRetries"], "automatic retry maximum"),
        (contract["costOracle"]["baseWorstCaseUsd"], config["providerCost"]["llmBaseWorstCaseUsd"], "base worst-case cost"),
        (contract["costOracle"]["regionalWorstCaseUsd"], config["providerCost"]["llmWorstCaseUsd"], "regional worst-case cost"),
        (contract["costOracle"]["hardCapUsd"], config["providerCost"]["hardCapUsd"], "hard cost cap"),
    ]
    for actual, expected, context in oracle_pairs:
        require_equal(actual, expected, context)
    require_equal(adapter["modelFallbacks"], [], "model fallback set")
    require_equal(contract["retryPolicy"]["maxAttempts"], 2, "maximum provider attempts")
    require_equal(contract["retryPolicy"]["providerFailureAutomaticRetries"], 0, "provider failure automatic retries")
    require_equal(contract["notRun"], NOT_RUN, "NOT RUN boundary")

    pipeline_contract = openapi.get("x-pipeline-identity")
    require_equal(
        pipeline_contract,
        {
            "canonicalVersion": PIPELINE_VERSION,
            "dedupeKeyFields": ["videoId", "sourceLanguage", "targetLanguage", "pipelineVersion"],
            "identityChangeReusesOldCacheOrOwner": False,
        },
        "OpenAPI pipeline identity",
    )
    learning_pipeline = openapi["components"]["schemas"]["LearningDocument"]["properties"]["pipelineVersion"]
    require_equal(learning_pipeline, {"const": PIPELINE_VERSION}, "OpenAPI LearningDocument pipelineVersion")
    require_equal(openapi["components"]["schemas"]["LearningDocument"]["properties"]["transcriptSource"], {"const": "caption"}, "OpenAPI transcriptSource")
    statuses = openapi["components"]["schemas"]["ProcessingStatus"]["enum"]
    if "transcribing" in statuses:
        fail("Release A OpenAPI must not admit transcribing")
    for name, mapping in contract["failureMappings"].items():
        frozen = openapi["x-error-contract"][mapping["errorCode"]]
        require_equal(frozen["messageKey"], mapping["errorMessageKey"], f"{name} message key")
        require_equal(frozen["retryable"], mapping["retryable"], f"{name} retryability")


def evaluate_attempts(
    attempts: list[dict[str, Any]],
    source: dict[str, Any],
    output_schema: dict[str, Any],
) -> tuple[str, int, int, dict[str, Any] | None]:
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
        fail("attempt list must contain one attempt plus at most one automatic retry")
    invalid_count = 0
    for index, attempt in enumerate(attempts):
        outcome = attempt.get("outcome")
        if outcome == "malformed_json":
            require_keys(attempt, {"outcome", "bodyText"}, f"attempt {index}")
            try:
                json.loads(attempt["bodyText"])
            except (json.JSONDecodeError, TypeError):
                invalid_count += 1
            else:
                fail(f"attempt {index}: malformed_json fixture unexpectedly parses")
        elif outcome == "response":
            require_keys(attempt, {"outcome", "body"}, f"attempt {index}")
            errors = output_validation_errors(attempt["body"], source, output_schema)
            if not errors:
                if index != len(attempts) - 1:
                    fail("attempts after a valid translation response are forbidden")
                return "ready", index + 1, invalid_count, attempt["body"]
            invalid_count += 1
        elif outcome == "provider_failure":
            require_keys(attempt, {"outcome", "failure"}, f"attempt {index}")
            if attempt["failure"] not in {"timeout", "service_error"}:
                fail(f"attempt {index}: unsupported provider failure class")
            if index != 0 or len(attempts) != 1:
                fail("provider failure is not automatically retried by #1718")
            return "provider_failure", 1, 0, None
        else:
            fail(f"attempt {index}: unknown outcome {outcome!r}")

        if index == 0 and len(attempts) != 2:
            fail("the first invalid response must consume the one automatic retry")
    return "invalid_response", len(attempts), 1, None


def check_cache_probe(case: dict[str, Any], effects: dict[str, Any]) -> None:
    probe = case["cacheProbe"]
    if probe is None:
        require_equal(effects["cacheHit"], False, f"{case['case']} cache hit")
        require_equal(effects["legacyCacheReused"], False, f"{case['case']} legacy cache reuse")
        return
    require_keys(probe, {"lookupDedupeKey", "existingEntries"}, f"{case['case']} cache probe")
    current_key = dedupe_key(case["videoId"])
    require_equal(probe["lookupDedupeKey"], current_key, f"{case['case']} current dedupe lookup")
    if not probe["existingEntries"]:
        fail(f"{case['case']}: pipeline identity probe requires a legacy entry")
    for entry in probe["existingEntries"]:
        require_keys(entry, {"dedupeKey", "pipelineVersion", "status"}, f"{case['case']} legacy entry")
        require_equal(entry["pipelineVersion"], LEGACY_PIPELINE_VERSION, f"{case['case']} legacy pipeline marker")
        require_equal(entry["status"], "ready", f"{case['case']} legacy cache status")
        if entry["dedupeKey"] == current_key or entry["pipelineVersion"] == PIPELINE_VERSION:
            fail(f"{case['case']}: legacy identity must not equal the current identity")
    require_equal(effects["cacheHit"], False, f"{case['case']} changed-identity cache hit")
    require_equal(effects["legacyCacheReused"], False, f"{case['case']} legacy cache reuse")


def check_case(
    case: dict[str, Any],
    contract: dict[str, Any],
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    openapi: dict[str, Any],
) -> None:
    require_keys(case, {"case", "videoId", "input", "attempts", "cacheProbe", "expected"}, case.get("case", "fixture case"))
    check_input(case["input"], input_schema, f"{case['case']} input")
    result, calls, invalid_retries, translated = evaluate_attempts(case["attempts"], case["input"], output_schema)
    expected = case["expected"]
    require_keys(expected, {"job", "learningDocument", "effects"}, f"{case['case']} expected")
    effects = expected["effects"]
    require_keys(effects, EFFECT_KEYS, f"{case['case']} effects")
    require_equal(effects["translationCallsTotal"], calls, f"{case['case']} translation call count")
    require_equal(effects["automaticRetriesUsed"], invalid_retries, f"{case['case']} automatic retry count")
    require_equal(effects["audioDownloads"], 0, f"{case['case']} audio downloads")
    require_equal(effects["sttCalls"], 0, f"{case['case']} STT calls")
    if "transcribing" in effects["statusTrace"]:
        fail(f"{case['case']}: Release A status trace must not contain transcribing")
    check_cache_probe(case, effects)

    RELEASE_A.assert_valid(expected["job"], "ProcessingJob", openapi, f"{case['case']} job")
    require_equal(expected["job"]["videoId"], case["videoId"], f"{case['case']} job video identity")
    if result == "ready":
        require_equal(expected["job"]["status"], "ready", f"{case['case']} ready status")
        require_equal(effects["statusTrace"], ["translating", "ready"], f"{case['case']} status trace")
        require_equal(effects["successfulCacheWritten"], True, f"{case['case']} success cache")
        require_equal(effects["readyResultPersisted"], True, f"{case['case']} ready persistence")
        if translated is None:
            fail(f"{case['case']}: ready result has no translated output")
        document = build_learning_document(case["videoId"], case["input"], translated)
        require_equal(expected["learningDocument"], document, f"{case['case']} LearningDocument assembly")
        RELEASE_A.assert_valid(document, "LearningDocument", openapi, f"{case['case']} LearningDocument")
        require_equal(expected["job"]["learningDataPath"], f"/v1/videos/{case['videoId']}/learning-data?target=zh-Hant-TW", f"{case['case']} learningDataPath")
    else:
        failure_name = "invalidResponse" if result == "invalid_response" else "providerFailure"
        mapping = contract["failureMappings"][failure_name]
        job = expected["job"]
        require_equal(job["status"], "failed", f"{case['case']} failed status")
        require_equal(job["errorCode"], mapping["errorCode"], f"{case['case']} errorCode")
        require_equal(job["errorMessageKey"], mapping["errorMessageKey"], f"{case['case']} errorMessageKey")
        require_equal(job["retryable"], mapping["retryable"], f"{case['case']} retryable")
        require_equal(expected["learningDocument"], None, f"{case['case']} failed LearningDocument")
        require_equal(effects["successfulCacheWritten"], False, f"{case['case']} failed success cache")
        require_equal(effects["readyResultPersisted"], False, f"{case['case']} failed ready persistence")
        require_equal(effects["statusTrace"], ["translating", "failed"], f"{case['case']} failed status trace")


def check_fixture_package(
    fixtures: list[dict[str, Any]],
    contract: dict[str, Any],
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    openapi: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if len(fixtures) != 4:
        fail(f"expected four fixture collections, got {len(fixtures)}")
    by_kind: dict[str, dict[str, Any]] = {}
    by_case: dict[str, dict[str, Any]] = {}
    for fixture in fixtures:
        require_keys(fixture, {"contractVersion", "kind", "cases"}, "fixture collection")
        require_equal(fixture["contractVersion"], "1.0.0", f"{fixture.get('kind')} contractVersion")
        kind = fixture["kind"]
        if kind in by_kind:
            fail(f"duplicate fixture kind {kind!r}")
        by_kind[kind] = fixture
        for case in fixture["cases"]:
            name = case.get("case")
            if name in by_case:
                fail(f"duplicate fixture case {name!r}")
            by_case[name] = case
            check_case(case, contract, input_schema, output_schema, openapi)
    require_equal(set(by_kind), EXPECTED_KINDS, "fixture kinds")
    require_equal(set(by_case), EXPECTED_CASES, "fixture case set")
    return by_case


def assert_contract_failure(action: Callable[[], Any], context: str) -> None:
    try:
        action()
    except (ContractFailure, RELEASE_A.ContractFailure, KeyError, TypeError, ValueError):
        return
    fail(f"mutation escaped: {context}")


def run_mutation_regressions(
    contract: dict[str, Any],
    contract_schema: dict[str, Any],
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    fixtures: list[dict[str, Any]],
    ledger: dict[str, Any],
    openapi: dict[str, Any],
) -> dict[str, int]:
    by_case = {case["case"]: case for fixture in fixtures for case in fixture["cases"]}
    success = by_case["valid_first_attempt_produces_ready_learning_document"]
    invalid = by_case["second_invalid_response_fails_without_success_cache"]
    provider = by_case["provider_timeout_uses_existing_retryable_failure_semantics"]
    identity = by_case["pipeline_change_does_not_reuse_legacy_success_cache"]
    probes: dict[str, list[tuple[str, Callable[[], Any]]]] = {
        "schema_strictness": [],
        "segment_integrity": [],
        "retry_failure": [],
        "frozen_oracle": [],
        "cache_identity": [],
        "effects_type_fidelity": [],
        "release_a_red_lines": [],
        "security_scope": [],
    }

    def case_probe(category: str, name: str, base: dict[str, Any], mutate: Callable[[dict[str, Any]], None]) -> None:
        changed = deepcopy(base)
        mutate(changed)
        probes[category].append((name, lambda changed=changed: check_case(changed, contract, input_schema, output_schema, openapi)))

    def contract_probe(category: str, name: str, mutate: Callable[[dict[str, Any]], None]) -> None:
        changed = deepcopy(contract)
        mutate(changed)
        probes[category].append((name, lambda changed=changed: check_frozen_oracle(changed, contract_schema, ledger, openapi)))

    case_probe("schema_strictness", "unknown input field", success, lambda c: c["input"].__setitem__("unknown", True))
    case_probe("schema_strictness", "missing input language", success, lambda c: c["input"].pop("sourceLanguage"))
    case_probe("schema_strictness", "unknown output field", success, lambda c: c["attempts"][0]["body"].__setitem__("unknown", True))
    case_probe("schema_strictness", "missing output translation", success, lambda c: c["attempts"][0]["body"]["segments"][0].pop("translation"))

    case_probe("segment_integrity", "segment count drift", success, lambda c: c["attempts"][0]["body"]["segments"].pop())
    case_probe("segment_integrity", "segment order drift", success, lambda c: c["attempts"][0]["body"]["segments"].reverse())
    case_probe("segment_integrity", "segment ID drift", success, lambda c: c["attempts"][0]["body"]["segments"][0].__setitem__("segmentId", "other"))
    case_probe("segment_integrity", "startTime drift", success, lambda c: c["attempts"][0]["body"]["segments"][0].__setitem__("startTime", 0.1))
    case_probe("segment_integrity", "endTime drift", success, lambda c: c["attempts"][0]["body"]["segments"][0].__setitem__("endTime", 2.4))
    case_probe("segment_integrity", "blank translation", success, lambda c: c["attempts"][0]["body"]["segments"][0].__setitem__("translation", " \t "))
    case_probe("segment_integrity", "negative input time", success, lambda c: c["input"]["segments"][0].__setitem__("startTime", -0.1))
    case_probe("segment_integrity", "overlapping input timeline", success, lambda c: c["input"]["segments"][1].__setitem__("startTime", 2.4))
    case_probe("segment_integrity", "non-increasing input timeline", success, lambda c: c["input"]["segments"][1].__setitem__("startTime", 0))
    case_probe("segment_integrity", "duplicate segment ID", success, lambda c: c["input"]["segments"][1].__setitem__("segmentId", "seg-001"))

    contract_probe("retry_failure", "automatic retry maximum two", lambda c: c["retryPolicy"].__setitem__("maxAutomaticRetries", 2))
    contract_probe("retry_failure", "maximum attempts three", lambda c: c["retryPolicy"].__setitem__("maxAttempts", 3))
    case_probe("retry_failure", "third translation attempt", invalid, lambda c: c["attempts"].append(deepcopy(c["attempts"][-1])))
    case_probe("retry_failure", "invalid response writes success cache", invalid, lambda c: c["expected"]["effects"].__setitem__("successfulCacheWritten", True))
    case_probe("retry_failure", "invalid response call count drift", invalid, lambda c: c["expected"]["effects"].__setitem__("translationCallsTotal", 3))
    case_probe("retry_failure", "provider failure automatic retry", provider, lambda c: c["attempts"].append(deepcopy(c["attempts"][0])))
    case_probe("retry_failure", "provider failure retryability drift", provider, lambda c: c["expected"]["job"].__setitem__("retryable", False))

    contract_probe("frozen_oracle", "provider drift", lambda c: c["adapter"].__setitem__("provider", "other"))
    contract_probe("frozen_oracle", "endpoint drift", lambda c: c["adapter"].__setitem__("endpoint", "Chat Completions API"))
    contract_probe("frozen_oracle", "model drift", lambda c: c["adapter"].__setitem__("modelSnapshot", "gpt-5.4-mini"))
    contract_probe("frozen_oracle", "reasoning drift", lambda c: c["adapter"].__setitem__("reasoningEffort", "low"))
    contract_probe("frozen_oracle", "Structured Outputs disabled", lambda c: c["adapter"].__setitem__("structuredOutputs", False))
    contract_probe("frozen_oracle", "Structured Outputs integer", lambda c: c["adapter"].__setitem__("structuredOutputs", 1))
    contract_probe("frozen_oracle", "input token budget drift", lambda c: c["adapter"].__setitem__("inputTokenBudgetPerAttempt", 12001))
    contract_probe("frozen_oracle", "output token budget drift", lambda c: c["adapter"].__setitem__("outputTokenBudgetPerAttempt", 12001))
    contract_probe("frozen_oracle", "timeout drift", lambda c: c["adapter"].__setitem__("timeoutMs", 20001))
    contract_probe("frozen_oracle", "model fallback added", lambda c: c["adapter"]["modelFallbacks"].append("other-model"))
    contract_probe("frozen_oracle", "pipeline drift", lambda c: c["pipelineIdentity"].__setitem__("pipelineVersion", LEGACY_PIPELINE_VERSION))
    contract_probe("frozen_oracle", "old success-cache reuse flag integer", lambda c: c["pipelineIdentity"].__setitem__("identityChangeReusesOldSuccessCache", 0))
    contract_probe("frozen_oracle", "old in-flight-owner reuse flag integer", lambda c: c["pipelineIdentity"].__setitem__("identityChangeReusesOldInFlightOwner", 0))
    contract_probe("frozen_oracle", "invalid-response retryable integer", lambda c: c["failureMappings"]["invalidResponse"].__setitem__("retryable", 1))
    contract_probe("frozen_oracle", "invalid-response cache flag integer", lambda c: c["failureMappings"]["invalidResponse"].__setitem__("successfulCacheWritten", 0))
    contract_probe("frozen_oracle", "provider-failure retryable integer", lambda c: c["failureMappings"]["providerFailure"].__setitem__("retryable", 1))
    contract_probe("frozen_oracle", "provider-failure cache flag integer", lambda c: c["failureMappings"]["providerFailure"].__setitem__("successfulCacheWritten", 0))

    case_probe("cache_identity", "legacy cache reused", identity, lambda c: c["expected"]["effects"].__setitem__("legacyCacheReused", True))
    case_probe("cache_identity", "legacy cache marked hit", identity, lambda c: c["expected"]["effects"].__setitem__("cacheHit", True))
    case_probe("cache_identity", "lookup uses legacy dedupe key", identity, lambda c: c["cacheProbe"].__setitem__("lookupDedupeKey", c["cacheProbe"]["existingEntries"][0]["dedupeKey"]))
    case_probe("cache_identity", "LearningDocument pipeline drift", success, lambda c: c["expected"]["learningDocument"].__setitem__("pipelineVersion", LEGACY_PIPELINE_VERSION))

    case_probe("effects_type_fidelity", "successfulCacheWritten true to 1", success, lambda c: c["expected"]["effects"].__setitem__("successfulCacheWritten", 1))
    case_probe("effects_type_fidelity", "readyResultPersisted true to 1", success, lambda c: c["expected"]["effects"].__setitem__("readyResultPersisted", 1))
    case_probe("effects_type_fidelity", "cacheHit false to 0", identity, lambda c: c["expected"]["effects"].__setitem__("cacheHit", 0))
    case_probe("effects_type_fidelity", "legacyCacheReused false to 0", identity, lambda c: c["expected"]["effects"].__setitem__("legacyCacheReused", 0))
    case_probe("effects_type_fidelity", "translationCallsTotal 1 to true", success, lambda c: c["expected"]["effects"].__setitem__("translationCallsTotal", True))
    case_probe("effects_type_fidelity", "automaticRetriesUsed 0 to false", success, lambda c: c["expected"]["effects"].__setitem__("automaticRetriesUsed", False))
    case_probe("effects_type_fidelity", "audioDownloads 0 to false", success, lambda c: c["expected"]["effects"].__setitem__("audioDownloads", False))
    case_probe("effects_type_fidelity", "sttCalls 0 to false", success, lambda c: c["expected"]["effects"].__setitem__("sttCalls", False))

    case_probe("release_a_red_lines", "audio side effect", success, lambda c: c["expected"]["effects"].__setitem__("audioDownloads", 1))
    case_probe("release_a_red_lines", "STT side effect", success, lambda c: c["expected"]["effects"].__setitem__("sttCalls", 1))
    case_probe("release_a_red_lines", "transcribing status", success, lambda c: c["expected"]["effects"]["statusTrace"].insert(1, "transcribing"))
    case_probe("release_a_red_lines", "input transcriptSource stt", success, lambda c: c["input"].__setitem__("transcriptSource", "stt"))
    case_probe("release_a_red_lines", "output transcriptSource stt", success, lambda c: c["attempts"][0]["body"].__setitem__("transcriptSource", "stt"))
    case_probe("release_a_red_lines", "source language drift", success, lambda c: c["input"].__setitem__("sourceLanguage", "ja"))
    case_probe("release_a_red_lines", "target language drift", success, lambda c: c["input"].__setitem__("targetLanguage", "zh-Hans"))

    contract_probe("security_scope", "client-side adapter", lambda c: c["adapter"].__setitem__("executionBoundary", "client"))
    contract_probe("security_scope", "credential forwarded", lambda c: c["security"].__setitem__("credentialForwardedToClient", True))
    contract_probe("security_scope", "credential forwarded integer", lambda c: c["security"].__setitem__("credentialForwardedToClient", 0))
    contract_probe("security_scope", "credential logging", lambda c: c["security"].__setitem__("credentialLogged", True))
    contract_probe("security_scope", "credential persisted integer", lambda c: c["security"].__setitem__("credentialPersistedInFixtures", 0))
    contract_probe("security_scope", "credential logging integer", lambda c: c["security"].__setitem__("credentialLogged", 0))
    contract_probe("security_scope", "raw provider payload logging integer", lambda c: c["security"].__setitem__("rawProviderPayloadLogged", 0))
    contract_probe("security_scope", "unknown secret material field", lambda c: c["security"].__setitem__("credentialValue", "forbidden"))

    stats: dict[str, int] = {}
    for category, category_probes in probes.items():
        for name, action in category_probes:
            assert_contract_failure(action, f"{category}/{name}")
        stats[category] = len(category_probes)
    return stats


def load_package() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
    dict[str, Any],
]:
    contract = load_json(CONTRACT_PATH)
    contract_schema = load_json(CONTRACT_SCHEMA_PATH)
    input_schema = load_json(INPUT_SCHEMA_PATH)
    output_schema = load_json(OUTPUT_SCHEMA_PATH)
    fixture_paths = sorted(FIXTURE_DIR.glob("*.json"))
    fixtures = [load_json(path) for path in fixture_paths]
    ledger = load_json(DECISION_LEDGER_PATH)
    openapi = load_json(OPENAPI_PATH)
    return contract, contract_schema, input_schema, output_schema, fixtures, ledger, openapi


def main() -> int:
    try:
        contract, contract_schema, input_schema, output_schema, fixtures, ledger, openapi = load_package()
        check_frozen_oracle(contract, contract_schema, ledger, openapi)
        cases = check_fixture_package(fixtures, contract, input_schema, output_schema, openapi)
        mutation_stats = run_mutation_regressions(
            contract,
            contract_schema,
            input_schema,
            output_schema,
            fixtures,
            ledger,
            openapi,
        )
    except (ContractFailure, RELEASE_A.ContractFailure, KeyError, TypeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1

    total_mutations = sum(mutation_stats.values())
    print("PASS: SubTube #1718 translation job contract readback")
    print(f"- Strict schemas passed: contract + input + Structured Output; fixture collections=4 cases={len(cases)}")
    print("- #1705 D2-A oracle passed: OpenAI Responses API / gpt-5.4-mini-2026-03-17 / reasoning none / Structured Outputs / 12000+12000 tokens / one retry / no fallback")
    print("- Segment integrity passed: same count, stable ID/order/times, nonblank translation, nonnegative strictly increasing nonoverlapping timeline")
    print("- Retry/failure passed: valid calls=1; invalid→valid calls=2; invalid twice fails translation_invalid_response; provider timeout uses translation_provider_failed")
    print("- Pipeline identity passed: release-a-caption-v1 across adapter/OpenAPI/LearningDocument/dedupe; legacy cache/owner reuse=false")
    print("- Release A red lines passed: transcriptSource=caption, audioDownloads=0, sttCalls=0, no transcribing")
    print(f"- Mutation regressions rejected: {total_mutations}/{total_mutations} escaped=0 categories={mutation_stats}")
    print("- Runtime/provider/billing/latency/load/quality/staging/iOS/deployment/TestFlight: NOT RUN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
