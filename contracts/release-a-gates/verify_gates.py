#!/usr/bin/env python3
"""Strict, dependency-free verifier for the #1705 Release A gate package."""

from __future__ import annotations

import copy
import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
LEDGER_PATH = PACKAGE / "fixtures" / "decision-ledger.json"
CORPUS_PATH = PACKAGE / "fixtures" / "release-a-corpus.json"
SCHEMA_PATHS = {
    "decision-ledger": PACKAGE / "schemas" / "decision-ledger.schema.json",
    "release-a-corpus": PACKAGE / "schemas" / "release-a-corpus.schema.json",
}
EXPECTED_DECISIONS = {"D1", "D2", "D3", "D4", "D5", "D6"}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
EXPECTED_OPENAI_SOURCE = "https://developers.openai.com/api/docs/models/gpt-5.4-mini"
EXPECTED_YOUTUBE_QUOTA_SOURCE = "https://developers.google.com/youtube/v3/determine_quota_cost"
EXPECTED_D2_MODEL = "gpt-5.4-mini-2026-03-17"
EXPECTED_PIPELINE = "release-a-caption-v1"
EXPECTED_ALLOWED_STATUSES = ["queued", "fetching_captions", "translating", "ready", "failed"]
RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
# Intentionally empty until PO/legal approve a real caption-text provider. A
# future approved name must be added with its dated evidence, never invented by
# a corpus mutation.
KNOWN_APPROVED_CAPTION_PROVIDERS: frozenset[str] = frozenset()
EXPECTED_PROMOTION_RULES = [
    "Within 24 hours before the run, videos.list records public, non-live, embeddable, duration <= PT15M, captions=true and English default audio or an equivalent server language determination.",
    "The approved caption-text provider retrieves an English track and valid sentence timing without audio or STT.",
    "The IFrame player loads in the Release A iOS/staging environment.",
    "The evidence record includes runId, runStartedAt, checkedAt, environment, provider/pipeline fingerprint and sanitized response facts.",
]
EXPECTED_ENVIRONMENT_RUN_LANES = [
    "cold-cache end-to-end caption path",
    "ready-cache reuse with zero caption/LLM/STT provider calls",
]
EXPECTED_ENVIRONMENT_EVIDENCE = [
    "run ID and UTC timestamps",
    "deployment/version fingerprint",
    "per-video preflight facts and replacement history",
    "provider call counts and direct provider cost",
    "job_created_at and ready_at",
    "10 sampled segment IDs and two independent scores",
    "sentence synchronization offsets",
    "sanitized errors without full captions, raw audio or secrets",
]
EXPECTED_VERIFICATION_FIELDS = ["runId", "runStartedAt", "checkedAt", "videosList", "captionRetrieval", "embedCheck", "environmentFingerprint"]
EXPECTED_VIDEO_UNVERIFIED_FIELDS = ["privacyStatus", "liveBroadcastContent", "embeddable", "defaultAudioLanguage", "englishCaptionTextRetrievable"]
EXPECTED_REQUIREMENT_KEYS = {
    "videoCount", "maxDurationSeconds", "sourceLanguage", "targetLanguage", "mustBePublic",
    "mustBeNonLive", "mustBeEmbeddable", "mustHaveRetrievableEnglishCaptions",
    "allowedTranscriptSources", "audioDownloadsAllowed", "sttEnabled",
}
EXPECTED_D2_OFFICIAL_EVIDENCE = {
    "https://developers.google.com/youtube/v3/docs/videos",
    "https://developers.google.com/youtube/v3/docs/captions/list",
    "https://developers.google.com/youtube/v3/docs/captions/download",
    EXPECTED_YOUTUBE_QUOTA_SOURCE,
    EXPECTED_OPENAI_SOURCE,
}
EXPECTED_D3_PACKAGE_EVIDENCE = {
    "contracts/release-a-gates/fixtures/release-a-corpus.json",
    "contracts/release-a-gates/verify_gates.py",
}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def valid_date(value: object) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def valid_datetime(value: object) -> bool:
    return parse_datetime(value) is not None


def parse_datetime(value: object) -> datetime | None:
    """Parse only RFC3339 seconds/fraction plus Z or numeric offset."""

    if not isinstance(value, str) or RFC3339_RE.fullmatch(value) is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def valid_https_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or any(char.isspace() for char in value):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def json_equal(left: object, right: object) -> bool:
    """Compare JSON values without Python's True == 1 coercion."""

    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if is_number(left) and is_number(right):
        return float(left) == float(right)
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(json_equal(a, b) for a, b in zip(left, right))
    if isinstance(left, dict):
        return set(left) == set(right) and all(json_equal(left[key], right[key]) for key in left)
    return left == right


def strict_object(value: object, path: str, allowed: set[str], required: set[str], errors: list[str]) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path} must be an object")
        return False
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    for key in missing:
        errors.append(f"{path} missing required property {key}")
    for key in unknown:
        errors.append(f"{path} has unexpected property {key}")
    return not missing and not unknown


def nonempty_string_list(value: object, path: str, errors: list[str], minimum: int = 1) -> None:
    require(isinstance(value, list) and len(value) >= minimum, f"{path} must contain at least {minimum} item(s)", errors)
    if isinstance(value, list):
        for index, item in enumerate(value):
            require(isinstance(item, str) and bool(item.strip()), f"{path}[{index}] must be a non-empty string", errors)


def strict_schema_validate(instance: object, schema: dict, path: str, root_schema: dict) -> list[str]:
    """Apply the schema keywords used by this package without jsonschema."""

    errors: list[str] = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return [f"{path}: unsupported schema reference {ref!r}"]
        target: object = root_schema
        for segment in ref[2:].split("/"):
            if not isinstance(target, dict) or segment not in target:
                return [f"{path}: unresolved schema reference {ref}"]
            target = target[segment]
        return strict_schema_validate(instance, target, path, root_schema) if isinstance(target, dict) else [f"{path}: invalid schema reference {ref}"]

    if "const" in schema and not json_equal(instance, schema["const"]):
        errors.append(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and not any(json_equal(instance, allowed) for allowed in schema["enum"]):
        errors.append(f"{path} must be one of {schema['enum']!r}")

    expected_type = schema.get("type")
    if expected_type is not None:
        type_checks = {
            "object": isinstance(instance, dict),
            "array": isinstance(instance, list),
            "string": isinstance(instance, str),
            "integer": isinstance(instance, int) and not isinstance(instance, bool),
            "number": is_number(instance),
            "boolean": isinstance(instance, bool),
            "null": instance is None,
        }
        type_ok = any(type_checks.get(item, False) for item in expected_type) if isinstance(expected_type, list) else type_checks.get(expected_type, False)
        if not type_ok:
            errors.append(f"{path} must have type {expected_type}")
            return errors

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path} is shorter than minLength {schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path} does not match pattern {schema['pattern']!r}")
        if schema.get("format") == "date" and not valid_date(instance):
            errors.append(f"{path} must be an ISO date")
        if schema.get("format") == "date-time" and not valid_datetime(instance):
            errors.append(f"{path} must be an ISO date-time with timezone")
        if schema.get("format") == "https-url" and not valid_https_url(instance):
            errors.append(f"{path} must be a valid HTTPS URL")

    if is_number(instance):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path} is below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path} is above maximum {schema['maximum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path} has fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path} has more than maxItems {schema['maxItems']}")
        prefix = schema.get("prefixItems", [])
        for index, item_schema in enumerate(prefix):
            if index < len(instance):
                errors.extend(strict_schema_validate(instance[index], item_schema, f"{path}[{index}]", root_schema))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            start = len(prefix)
            for index, item in enumerate(instance[start:], start=start):
                errors.extend(strict_schema_validate(item, item_schema, f"{path}[{index}]", root_schema))

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path} missing schema-required property {key}")
        if schema.get("additionalProperties") is False:
            for key in sorted(set(instance) - set(properties)):
                errors.append(f"{path} has schema-unexpected property {key}")
        for key, child_schema in properties.items():
            if key in instance:
                errors.extend(strict_schema_validate(instance[key], child_schema, f"{path}.{key}", root_schema))
    return errors


def validate_ledger_shape(ledger: dict, errors: list[str]) -> None:
    top_allowed = {
        "$schema", "schemaVersion", "issue", "asOf", "timezone", "releaseAOverall", "releaseBOverall",
        "decisions", "releaseAConfig", "releaseBDecisionCells", "evidenceStatus",
    }
    if not strict_object(ledger, "ledger", top_allowed, top_allowed - {"$schema"}, errors):
        return
    require(ledger.get("schemaVersion") == "1.0.0", "ledger.schemaVersion must be 1.0.0", errors)
    require(ledger.get("issue") == 1705, "ledger.issue must be 1705", errors)
    require(valid_date(ledger.get("asOf")), "ledger.asOf must be a valid ISO date", errors)
    require(ledger.get("timezone") == "Asia/Taipei", "ledger.timezone must be Asia/Taipei", errors)
    require(ledger.get("releaseAOverall") in {"blocked_no_go", "ready_for_run"}, "ledger.releaseAOverall has an invalid Release A gate state", errors)
    require(ledger.get("releaseBOverall") == "open_no_go", "ledger.releaseBOverall must be open_no_go", errors)

    decisions = ledger.get("decisions")
    require(isinstance(decisions, list), "ledger.decisions must be an array", errors)
    decision_allowed = {"id", "status", "decision", "owner", "deadline", "deadlineRule", "evidence", "releaseImpact", "unblockConditions"}
    if isinstance(decisions, list):
        for index, item in enumerate(decisions):
            path = f"ledger.decisions[{index}]"
            if not strict_object(item, path, decision_allowed, decision_allowed, errors):
                continue
            for field in ("id", "status", "decision", "deadlineRule", "releaseImpact"):
                require(isinstance(item.get(field), str) and bool(item[field].strip()), f"{path}.{field} must be a non-empty string", errors)
            require(valid_datetime(item.get("deadline")), f"{path}.deadline must have an explicit timezone", errors)
            nonempty_string_list(item.get("owner"), f"{path}.owner", errors)
            nonempty_string_list(item.get("evidence"), f"{path}.evidence", errors)
            nonempty_string_list(item.get("unblockConditions"), f"{path}.unblockConditions", errors, minimum=0)

    cells = ledger.get("releaseBDecisionCells")
    if strict_object(cells, "ledger.releaseBDecisionCells", {"D2-B", "D3-B"}, {"D2-B", "D3-B"}, errors):
        cell_allowed = {"status", "owner", "deadline", "evidence", "unblockConditions", "releaseImpact"}
        for cell_id in ("D2-B", "D3-B"):
            path = f"ledger.releaseBDecisionCells.{cell_id}"
            cell = cells[cell_id]
            if not strict_object(cell, path, cell_allowed, cell_allowed, errors):
                continue
            require(cell.get("status") == "open_no_go", f"{path}.status must remain open_no_go", errors)
            require(valid_datetime(cell.get("deadline")), f"{path}.deadline must have an explicit timezone", errors)
            nonempty_string_list(cell.get("owner"), f"{path}.owner", errors)
            nonempty_string_list(cell.get("evidence"), f"{path}.evidence", errors)
            nonempty_string_list(cell.get("unblockConditions"), f"{path}.unblockConditions", errors)
            require(isinstance(cell.get("releaseImpact"), str) and bool(cell["releaseImpact"].strip()), f"{path}.releaseImpact must be non-empty", errors)

    config = ledger.get("releaseAConfig")
    config_allowed = {"activationStatus", "pipelineVersion", "pipelineVersionActivationRule", "caption", "translation", "timeoutsMs", "providerCost", "youtubeQuota", "releaseARedLines"}
    if not strict_object(config, "ledger.releaseAConfig", config_allowed, config_allowed, errors):
        return
    require(config.get("activationStatus") in {"blocked_no_go", "ready_for_run"}, "releaseAConfig.activationStatus has an invalid gate state", errors)
    require(config.get("pipelineVersion") == EXPECTED_PIPELINE, "releaseAConfig.pipelineVersion mismatch", errors)
    require(isinstance(config.get("pipelineVersionActivationRule"), str) and "MUST NOT" in config["pipelineVersionActivationRule"], "pipelineVersionActivationRule must preserve the activation rule", errors)

    caption = config.get("caption")
    if strict_object(caption, "ledger.releaseAConfig.caption", {"source", "metadataProvider", "metadataFields", "captionTextProvider"}, {"source", "metadataProvider", "metadataFields", "captionTextProvider"}, errors):
        require(isinstance(caption.get("source"), str) and bool(caption["source"].strip()), "caption.source must be non-empty", errors)
        require(caption.get("metadataProvider") == "YouTube Data API v3 videos.list", "caption.metadataProvider must be frozen", errors)
        nonempty_string_list(caption.get("metadataFields"), "caption.metadataFields", errors)
        caption_provider = caption.get("captionTextProvider")
        if strict_object(caption_provider, "ledger.releaseAConfig.caption.captionTextProvider", {"status", "provider", "reason", "evidence"}, {"status", "provider", "reason"}, errors):
            require(caption_provider.get("status") in {"blocked", "approved"}, "caption text provider status is invalid", errors)
            if caption_provider.get("status") == "blocked":
                require(caption_provider.get("provider") is None, "blocked caption text provider must be null", errors)
            else:
                require(isinstance(caption_provider.get("provider"), str) and bool(caption_provider["provider"].strip()), "approved caption provider must be named", errors)
                require(caption_provider.get("provider") in KNOWN_APPROVED_CAPTION_PROVIDERS, "caption provider is not in the externally approved provider allowlist", errors)
                nonempty_string_list(caption_provider.get("evidence"), "captionTextProvider.evidence", errors)
            require(isinstance(caption_provider.get("reason"), str) and bool(caption_provider["reason"].strip()), "caption provider reason must be non-empty", errors)

    translation = config.get("translation")
    translation_allowed = {"provider", "endpoint", "modelAlias", "modelSnapshot", "reasoningEffort", "structuredOutputs", "targetLanguage", "maxAutomaticRetries", "aggregateTokenBudgetPerAttempt", "priceUsdPerMillionTokens"}
    if strict_object(translation, "ledger.releaseAConfig.translation", translation_allowed, translation_allowed, errors):
        expected = {"provider": "OpenAI API", "endpoint": "Responses API", "modelAlias": "gpt-5.4-mini", "modelSnapshot": EXPECTED_D2_MODEL, "reasoningEffort": "none", "structuredOutputs": True, "targetLanguage": "zh-Hant-TW", "maxAutomaticRetries": 1}
        for field, expected_value in expected.items():
            require(translation.get(field) == expected_value, f"translation.{field} is not the frozen D2-A value", errors)
        budget = translation.get("aggregateTokenBudgetPerAttempt")
        if strict_object(budget, "translation.aggregateTokenBudgetPerAttempt", {"input", "output"}, {"input", "output"}, errors):
            require(budget.get("input") == 12000 and budget.get("output") == 12000, "translation token budgets must remain 12000/12000", errors)
        prices = translation.get("priceUsdPerMillionTokens")
        price_allowed = {"input", "output", "regionalProcessingUpliftMaximum", "accessedAt", "source"}
        if strict_object(prices, "translation.priceUsdPerMillionTokens", price_allowed, price_allowed, errors):
            require(is_number(prices.get("input")) and math.isclose(prices["input"], 0.75, abs_tol=1e-12), "input price must be USD 0.75/M", errors)
            require(is_number(prices.get("output")) and math.isclose(prices["output"], 4.5, abs_tol=1e-12), "output price must be USD 4.50/M", errors)
            require(is_number(prices.get("regionalProcessingUpliftMaximum")) and math.isclose(prices["regionalProcessingUpliftMaximum"], 0.1, abs_tol=1e-12), "regional uplift maximum must be 10%", errors)
            require(prices.get("accessedAt") == "2026-08-27" and valid_date(prices.get("accessedAt")), "price accessedAt must be the verified 2026-08-27 date", errors)
            require(prices.get("source") == EXPECTED_OPENAI_SOURCE and valid_https_url(prices.get("source")), "price source must be the official OpenAI model URL", errors)

    timeouts = config.get("timeoutsMs")
    timeout_allowed = {"preflightHard", "captionFetchStep", "llmAttempt", "jobHardFromCreatedToTerminal"}
    if strict_object(timeouts, "ledger.releaseAConfig.timeoutsMs", timeout_allowed, timeout_allowed, errors):
        expected_timeouts = {"preflightHard": 2000, "captionFetchStep": 15000, "llmAttempt": 20000, "jobHardFromCreatedToTerminal": 60000}
        for field, expected_value in expected_timeouts.items():
            require(isinstance(timeouts.get(field), int) and not isinstance(timeouts[field], bool) and timeouts[field] == expected_value and timeouts[field] > 0, f"timeout {field} must be the positive frozen value", errors)

    cost = config.get("providerCost")
    cost_allowed = {"scope", "llmWorstCaseFormula", "llmBaseWorstCaseUsd", "llmWorstCaseUsd", "hardCapUsd", "remainingCaptionProviderAllowanceUsd", "enforcement"}
    if strict_object(cost, "ledger.releaseAConfig.providerCost", cost_allowed, cost_allowed, errors):
        require(isinstance(cost.get("scope"), str) and bool(cost["scope"].strip()), "providerCost.scope must be non-empty", errors)
        require(cost.get("llmWorstCaseFormula") == "2 attempts * ((12000 input / 1000000 * USD 0.75) + (12000 output / 1000000 * USD 4.50)) * 1.10 maximum documented regional uplift", "provider cost formula must preserve all D2-A inputs", errors)
        for field, expected_value in (("llmBaseWorstCaseUsd", 0.126), ("llmWorstCaseUsd", 0.1386), ("hardCapUsd", 0.15), ("remainingCaptionProviderAllowanceUsd", 0.0114)):
            require(is_number(cost.get(field)) and math.isclose(cost[field], expected_value, abs_tol=1e-9), f"providerCost.{field} mismatch", errors)
        require(isinstance(cost.get("enforcement"), str) and "cost_limit_exceeded" in cost["enforcement"], "provider cost enforcement rule is missing", errors)

    quota = config.get("youtubeQuota")
    quota_allowed = {"videosListUnitsPerCall", "captionsListUnitsPerCall", "captionsDownloadUnitsPerCall", "source", "limitation"}
    if strict_object(quota, "ledger.releaseAConfig.youtubeQuota", quota_allowed, quota_allowed, errors):
        require(quota.get("videosListUnitsPerCall") == 1, "videos.list quota units must remain 1", errors)
        require(quota.get("captionsListUnitsPerCall") == 50, "captions.list quota units must remain 50", errors)
        require(quota.get("captionsDownloadUnitsPerCall") == 200, "captions.download quota units must remain 200", errors)
        require(quota.get("source") == EXPECTED_YOUTUBE_QUOTA_SOURCE and valid_https_url(quota.get("source")), "YouTube quota source must be official", errors)
        require(isinstance(quota.get("limitation"), str) and bool(quota["limitation"].strip()), "YouTube quota limitation must be explicit", errors)

    red_lines = config.get("releaseARedLines")
    red_allowed = {"audioDownloadsAllowed", "sttEnabled", "allowedPublicStatuses", "allowedTranscriptSources", "captionUnavailableBehavior"}
    if strict_object(red_lines, "ledger.releaseAConfig.releaseARedLines", red_allowed, red_allowed, errors):
        require(red_lines.get("audioDownloadsAllowed") is False, "Release A audio must be disabled", errors)
        require(red_lines.get("sttEnabled") is False, "Release A STT must be disabled", errors)
        require(red_lines.get("allowedPublicStatuses") == EXPECTED_ALLOWED_STATUSES, "Release A statuses must exclude transcribing", errors)
        require(red_lines.get("allowedTranscriptSources") == ["caption"], "Release A transcript source must be caption-only", errors)
        require(isinstance(red_lines.get("captionUnavailableBehavior"), str) and "no job" in red_lines["captionUnavailableBehavior"], "caption-unavailable behavior must stop before providers", errors)

    evidence_status = ledger.get("evidenceStatus")
    evidence_allowed = {"officialPolicyAndPriceReadback", "captionProviderExecution", "llmProviderExecution", "runtimeCostMetering", "sttProvider"}
    if strict_object(evidence_status, "ledger.evidenceStatus", evidence_allowed, evidence_allowed, errors):
        expected_status = {"officialPolicyAndPriceReadback": "DOCUMENTED", "llmProviderExecution": "NOT RUN", "runtimeCostMetering": "NOT RUN", "sttProvider": "NOT SELECTED / NO-GO"}
        for field, expected_value in expected_status.items():
            require(evidence_status.get(field) == expected_value, f"evidenceStatus.{field} must remain explicit", errors)
        require(evidence_status.get("captionProviderExecution") in {"NOT RUN", "PASS"}, "caption provider execution evidence status is invalid", errors)


def validate_evidence_freshness(evidence: dict, path: str, errors: list[str]) -> None:
    run_started_at = parse_datetime(evidence.get("runStartedAt"))
    checked_at = parse_datetime(evidence.get("checkedAt"))
    now = datetime.now(timezone.utc)
    require(run_started_at is not None, f"{path}.runStartedAt must be strict RFC3339", errors)
    require(checked_at is not None, f"{path}.checkedAt must be strict RFC3339", errors)
    if run_started_at is not None:
        require(run_started_at <= now, f"{path}.runStartedAt cannot be in the future", errors)
    if checked_at is not None:
        require(checked_at <= now, f"{path}.checkedAt cannot be in the future", errors)
    if run_started_at is not None and checked_at is not None:
        delta = checked_at - run_started_at
        require(delta >= timedelta(0), f"{path}.checkedAt cannot precede runStartedAt", errors)
        require(delta <= timedelta(hours=24), f"{path}.checkedAt must be within 24 hours of runStartedAt", errors)


def validate_verified_evidence(video: dict, path: str, ledger: dict, corpus: dict, errors: list[str]) -> None:
    video_id = video.get("videoId", "")
    evidence = video.get("verificationEvidence")
    if not strict_object(evidence, f"{path}.verificationEvidence", set(EXPECTED_VERIFICATION_FIELDS), set(EXPECTED_VERIFICATION_FIELDS), errors):
        return
    run_id = evidence.get("runId")
    require(
        isinstance(run_id, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}", run_id)),
        f"verified video {video_id} needs a structured non-placeholder runId",
        errors,
    )
    validate_evidence_freshness(evidence, f"{path}.verificationEvidence", errors)
    videos_list = evidence.get("videosList")
    video_facts_allowed = {"privacyStatus", "liveBroadcastContent", "embeddable", "durationSeconds", "captionAvailable", "defaultAudioLanguage"}
    if strict_object(videos_list, f"{path}.verificationEvidence.videosList", video_facts_allowed, video_facts_allowed, errors):
        require(videos_list.get("privacyStatus") == "public", f"verified video {video_id} must prove public status", errors)
        require(videos_list.get("liveBroadcastContent") == "none", f"verified video {video_id} must prove non-live status", errors)
        require(videos_list.get("embeddable") is True, f"verified video {video_id} must prove embeddability", errors)
        require(isinstance(videos_list.get("durationSeconds"), int) and not isinstance(videos_list["durationSeconds"], bool) and 0 < videos_list["durationSeconds"] <= 900, f"verified video {video_id} duration evidence is invalid", errors)
        require(videos_list.get("captionAvailable") is True, f"verified video {video_id} must prove captions", errors)
        require(videos_list.get("defaultAudioLanguage") == "en", f"verified video {video_id} must prove English metadata", errors)

    caption_retrieval = evidence.get("captionRetrieval")
    caption_allowed = {"status", "provider", "language", "sentenceTiming", "audioDownloads", "sttCalls"}
    if strict_object(caption_retrieval, f"{path}.verificationEvidence.captionRetrieval", caption_allowed, caption_allowed, errors):
        require(caption_retrieval.get("status") == "approved_provider", f"verified video {video_id} needs approved caption-provider evidence", errors)
        evidence_provider = caption_retrieval.get("provider")
        ledger_provider = ledger.get("releaseAConfig", {}).get("caption", {}).get("captionTextProvider", {})
        require(isinstance(evidence_provider, str) and bool(evidence_provider.strip()), f"verified video {video_id} provider evidence must be named", errors)
        require(evidence_provider in KNOWN_APPROVED_CAPTION_PROVIDERS, f"verified video {video_id} provider is not externally approved", errors)
        require(evidence_provider == ledger_provider.get("provider"), f"verified video {video_id} provider identity must match the ledger", errors)
        require(caption_retrieval.get("language") == "en", f"verified video {video_id} caption language must be English", errors)
        require(caption_retrieval.get("sentenceTiming") is True, f"verified video {video_id} needs sentence timing", errors)
        require(caption_retrieval.get("audioDownloads") == 0 and caption_retrieval.get("sttCalls") == 0, f"verified video {video_id} evidence must prove zero audio/STT", errors)

    embed_check = evidence.get("embedCheck")
    if strict_object(embed_check, f"{path}.verificationEvidence.embedCheck", {"status", "player"}, {"status", "player"}, errors):
        require(embed_check.get("status") == "pass", f"verified video {video_id} needs a passing embed check", errors)
        require(embed_check.get("player") == "youtube_iframe", f"verified video {video_id} embed player evidence mismatch", errors)

    environment_fingerprint = evidence.get("environmentFingerprint")
    environment_allowed = {"environment", "pipelineVersion", "translationProvider", "modelSnapshot", "targetLanguage", "sttEnabled", "audioDownloadsAllowed"}
    if strict_object(environment_fingerprint, f"{path}.verificationEvidence.environmentFingerprint", environment_allowed, environment_allowed, errors):
        required = corpus.get("testEnvironment", {}).get("requiredFingerprint", {})
        for field in environment_allowed - {"environment"}:
            require(environment_fingerprint.get(field) == required.get(field), f"verified video {video_id} environment fingerprint mismatch at {field}", errors)
        require(environment_fingerprint.get("environment") == "release-a-staging", f"verified video {video_id} must name staging", errors)


def validate_run_evidence(run_evidence: object, path: str, errors: list[str]) -> None:
    allowed = {"runId", "runStartedAt", "runCompletedAt", "status", "verifiedVideoCount", "evidenceArtifact"}
    required = allowed
    if not strict_object(run_evidence, path, allowed, required, errors):
        return
    run_id = run_evidence.get("runId")
    require(isinstance(run_id, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,127}", run_id)), f"{path}.runId must be structured", errors)
    started = parse_datetime(run_evidence.get("runStartedAt"))
    completed = parse_datetime(run_evidence.get("runCompletedAt"))
    now = datetime.now(timezone.utc)
    require(started is not None, f"{path}.runStartedAt must be strict RFC3339", errors)
    require(completed is not None, f"{path}.runCompletedAt must be strict RFC3339", errors)
    if started is not None:
        require(started <= now, f"{path}.runStartedAt cannot be in the future", errors)
    if completed is not None:
        require(completed <= now, f"{path}.runCompletedAt cannot be in the future", errors)
    if started is not None and completed is not None:
        require(completed >= started, f"{path}.runCompletedAt cannot precede runStartedAt", errors)
    require(run_evidence.get("status") == "pass", f"{path}.status must be pass", errors)
    require(run_evidence.get("verifiedVideoCount") == 20, f"{path}.verifiedVideoCount must be 20", errors)
    artifact = run_evidence.get("evidenceArtifact")
    require(isinstance(artifact, str) and bool(artifact.strip()), f"{path}.evidenceArtifact must be non-empty", errors)


def validate_corpus_shape(corpus: dict, ledger: dict, errors: list[str]) -> None:
    top_allowed = {"$schema", "schemaVersion", "issue", "scope", "capturedAt", "requirements", "observationMethod", "summary", "videos", "promotionGate", "qualityPlan", "testEnvironment", "fixtureSeparation", "replacementPolicy"}
    if not strict_object(corpus, "corpus", top_allowed, top_allowed - {"$schema"}, errors):
        return
    require(corpus.get("schemaVersion") == "1.0.0", "corpus.schemaVersion must be 1.0.0", errors)
    require(corpus.get("issue") == 1705, "corpus.issue must be 1705", errors)
    require(corpus.get("scope") == "release_a_caption_only", "corpus must be Release A caption-only", errors)
    require(valid_datetime(corpus.get("capturedAt")), "corpus.capturedAt must have an explicit timezone", errors)

    requirements = corpus.get("requirements")
    if strict_object(requirements, "corpus.requirements", EXPECTED_REQUIREMENT_KEYS, EXPECTED_REQUIREMENT_KEYS, errors):
        expected = {"videoCount": 20, "maxDurationSeconds": 900, "sourceLanguage": "en", "targetLanguage": "zh-Hant-TW", "mustBePublic": True, "mustBeNonLive": True, "mustBeEmbeddable": True, "mustHaveRetrievableEnglishCaptions": True, "allowedTranscriptSources": ["caption"], "audioDownloadsAllowed": False, "sttEnabled": False}
        for field, expected_value in expected.items():
            require(requirements.get(field) == expected_value, f"corpus.requirements.{field} must preserve Release A eligibility", errors)

    observation = corpus.get("observationMethod")
    observation_allowed = {"surface", "officialHost", "queries", "observedSignals", "limitations"}
    if strict_object(observation, "corpus.observationMethod", observation_allowed, observation_allowed, errors):
        require(observation.get("officialHost") == "https://www.youtube.com" and valid_https_url(observation.get("officialHost")), "observation host must be official YouTube", errors)
        nonempty_string_list(observation.get("queries"), "observationMethod.queries", errors)
        nonempty_string_list(observation.get("observedSignals"), "observationMethod.observedSignals", errors)
        nonempty_string_list(observation.get("limitations"), "observationMethod.limitations", errors)
        require(any("not the server preflight contract" in item for item in observation.get("limitations", [])), "observation must distinguish candidates from verified evidence", errors)

    summary = corpus.get("summary")
    summary_allowed = {"candidateCount", "verifiedCount", "rejectedCount", "maxObservedDurationSeconds", "gateStatus"}
    if not strict_object(summary, "corpus.summary", summary_allowed, summary_allowed, errors):
        summary = {}
    videos = corpus.get("videos")
    require(isinstance(videos, list) and len(videos) == 20, "manifest must contain exactly 20 videos", errors)

    promotion = corpus.get("promotionGate")
    promotion_allowed = {"requiredEligibilityFlags", "candidateToVerified", "evidenceSchema", "currentBlocker"}
    if strict_object(promotion, "corpus.promotionGate", promotion_allowed, promotion_allowed, errors):
        flags = promotion.get("requiredEligibilityFlags")
        flag_allowed = {"public", "nonLive", "embeddable", "retrievableEnglishCaptions", "maxDurationSeconds"}
        if strict_object(flags, "promotionGate.requiredEligibilityFlags", flag_allowed, flag_allowed, errors):
            require(flags == {"public": True, "nonLive": True, "embeddable": True, "retrievableEnglishCaptions": True, "maxDurationSeconds": 900}, "promotion eligibility flags must remain strict Release A values", errors)
        require(promotion.get("candidateToVerified") == EXPECTED_PROMOTION_RULES, "promotion rules/evidence requirements must not be removed or weakened", errors)
        evidence_schema = promotion.get("evidenceSchema")
        evidence_allowed = {"requiredFields", "videosListRequiredFacts", "captionRetrievalRequired", "embedCheckRequired", "environmentFingerprintRequired"}
        if strict_object(evidence_schema, "promotionGate.evidenceSchema", evidence_allowed, evidence_allowed, errors):
            require(evidence_schema.get("requiredFields") == EXPECTED_VERIFICATION_FIELDS, "promotion evidence required fields mismatch", errors)
            video_facts = evidence_schema.get("videosListRequiredFacts")
            video_facts_allowed = {"privacyStatus", "liveBroadcastContent", "embeddable", "durationSecondsMax", "captionAvailable", "defaultAudioLanguage"}
            if strict_object(video_facts, "promotionGate.evidenceSchema.videosListRequiredFacts", video_facts_allowed, video_facts_allowed, errors):
                require(video_facts == {"privacyStatus": "public", "liveBroadcastContent": "none", "embeddable": True, "durationSecondsMax": 900, "captionAvailable": True, "defaultAudioLanguage": "en"}, "videos.list promotion facts must remain strict", errors)
            caption_facts = evidence_schema.get("captionRetrievalRequired")
            caption_facts_allowed = {"status", "language", "sentenceTiming", "audioDownloads", "sttCalls"}
            if strict_object(caption_facts, "promotionGate.evidenceSchema.captionRetrievalRequired", caption_facts_allowed, caption_facts_allowed, errors):
                require(caption_facts == {"status": "approved_provider", "language": "en", "sentenceTiming": True, "audioDownloads": 0, "sttCalls": 0}, "caption retrieval promotion facts must remain strict", errors)
            embed_facts = evidence_schema.get("embedCheckRequired")
            if strict_object(embed_facts, "promotionGate.evidenceSchema.embedCheckRequired", {"status"}, {"status"}, errors):
                require(embed_facts.get("status") == "pass", "embed promotion evidence must require pass", errors)
            require(evidence_schema.get("environmentFingerprintRequired") == ["pipelineVersion", "translationProvider", "modelSnapshot", "targetLanguage", "sttEnabled", "audioDownloadsAllowed"], "environment fingerprint requirements must not be removed", errors)
        require(isinstance(promotion.get("currentBlocker"), str) and "No approved caption-text provider" in promotion["currentBlocker"], "promotion blocker must remain explicit", errors)

    video_ids: list[str] = []
    durations: list[int] = []
    candidates = verified = invalid = 0
    video_allowed = {"ordinal", "videoId", "url", "title", "channel", "observedDurationSeconds", "observationQuery", "status", "observedSignals", "unverifiedFields", "verificationEvidence"}
    video_required = video_allowed - {"verificationEvidence"}
    if isinstance(videos, list):
        for index, video in enumerate(videos, start=1):
            path = f"corpus.videos[{index - 1}]"
            if not strict_object(video, path, video_allowed, video_required, errors):
                continue
            video_id = video.get("videoId")
            duration = video.get("observedDurationSeconds")
            status = video.get("status")
            video_ids.append(video_id if isinstance(video_id, str) else "")
            durations.append(duration if isinstance(duration, int) and not isinstance(duration, bool) else 0)
            require(video.get("ordinal") == index, f"{path}.ordinal mismatch", errors)
            require(isinstance(video_id, str) and bool(VIDEO_ID_RE.fullmatch(video_id)), f"{path}.videoId is invalid", errors)
            require(video.get("url") == f"https://www.youtube.com/watch?v={video_id}", f"{path}.url is not canonical", errors)
            require(isinstance(video.get("title"), str) and bool(video["title"].strip()), f"{path}.title must be non-empty", errors)
            require(isinstance(video.get("channel"), str) and bool(video["channel"].strip()), f"{path}.channel must be non-empty", errors)
            require(isinstance(duration, int) and not isinstance(duration, bool) and 0 < duration <= 900, f"{path}.observedDurationSeconds must be within D6", errors)
            require(video.get("observationQuery") in {1, 2}, f"{path}.observationQuery must identify the source query", errors)
            signals = video.get("observedSignals")
            signal_allowed = {"searchVisible", "fixedDuration", "englishMetadata", "captionsBadge", "verifiedChannel"}
            if strict_object(signals, f"{path}.observedSignals", signal_allowed, signal_allowed, errors):
                for signal in signal_allowed:
                    require(signals.get(signal) is True, f"{path}.observedSignals.{signal} must be true for a candidate", errors)
            require(status in {"candidate", "verified", "invalid"}, f"{path}.status is invalid", errors)
            nonempty_string_list(video.get("unverifiedFields"), f"{path}.unverifiedFields", errors, minimum=0)
            if status == "candidate":
                candidates += 1
                require(video.get("unverifiedFields") == EXPECTED_VIDEO_UNVERIFIED_FIELDS, f"candidate {video_id} must preserve unverified eligibility fields", errors)
                require("verificationEvidence" not in video, f"candidate {video_id} cannot carry promotion evidence", errors)
            elif status == "verified":
                verified += 1
                require(video.get("unverifiedFields") == [], f"verified video {video_id} cannot retain unverified eligibility fields", errors)
                validate_verified_evidence(video, path, ledger, corpus, errors)
            else:
                invalid += 1

    require(len(video_ids) == len(set(video_ids)), "video IDs must be unique", errors)
    if isinstance(summary, dict):
        require(summary.get("candidateCount") == candidates, "candidate summary count mismatch", errors)
        require(summary.get("verifiedCount") == verified, "verified summary count mismatch", errors)
        require(summary.get("rejectedCount") == invalid, "invalid/rejected summary count mismatch", errors)
        require(summary.get("maxObservedDurationSeconds") == max(durations, default=0), "max observed duration summary mismatch", errors)
        require(isinstance(summary.get("maxObservedDurationSeconds"), int) and 0 < summary.get("maxObservedDurationSeconds", 0) <= 900, "summary max duration must be within D6", errors)
        if verified < 20:
            require(summary.get("gateStatus") == "blocked_candidates_only", "candidate-only corpus must remain blocked", errors)
        else:
            require(summary.get("gateStatus") == "verified_ready_for_run", "fully verified corpus must use verified_ready_for_run", errors)

    quality = corpus.get("qualityPlan")
    quality_allowed = {"segmentsPerVideo", "selectionRule", "reviewers", "reviewRule", "rubric", "acceptableScoreMinimum", "aggregateAcceptanceMinimum", "expectedRatingCount", "gateFormula", "disagreementRule", "executionStatus"}
    if strict_object(quality, "corpus.qualityPlan", quality_allowed, quality_allowed, errors):
        require(quality.get("segmentsPerVideo") == 10, "quality sample must use 10 segments per video", errors)
        require(isinstance(quality.get("selectionRule"), str) and "do not hand-pick" in quality["selectionRule"], "quality selection rule must be deterministic", errors)
        reviewers = quality.get("reviewers")
        require(isinstance(reviewers, list) and len(reviewers) == 2, "exactly two reviewers must be assigned", errors)
        reviewer_ids: list[str] = []
        if isinstance(reviewers, list):
            reviewer_allowed = {"id", "locale", "role"}
            for index, reviewer in enumerate(reviewers):
                if strict_object(reviewer, f"quality.reviewers[{index}]", reviewer_allowed, reviewer_allowed, errors):
                    reviewer_ids.append(reviewer.get("id"))
                    require(reviewer.get("locale") == "zh-Hant-TW", f"quality.reviewers[{index}] must use zh-Hant-TW", errors)
                    require(isinstance(reviewer.get("role"), str) and bool(reviewer["role"].strip()), f"quality.reviewers[{index}].role must be non-empty", errors)
        require(len(reviewer_ids) == len(set(reviewer_ids)) == 2, "reviewers must be distinct", errors)
        rubric = quality.get("rubric")
        require(isinstance(rubric, list) and [row.get("score") for row in rubric if isinstance(row, dict)] == [1, 2, 3, 4, 5], "rubric must define scores 1 through 5", errors)
        if isinstance(rubric, list):
            rubric_allowed = {"score", "label", "definition"}
            for index, row in enumerate(rubric):
                if strict_object(row, f"quality.rubric[{index}]", rubric_allowed, rubric_allowed, errors):
                    require(isinstance(row.get("label"), str) and bool(row["label"].strip()), f"quality.rubric[{index}].label must be non-empty", errors)
                    require(isinstance(row.get("definition"), str) and bool(row["definition"].strip()), f"quality.rubric[{index}].definition must be non-empty", errors)
        require(quality.get("acceptableScoreMinimum") == 4, "acceptable threshold must be 4/5", errors)
        require(is_number(quality.get("aggregateAcceptanceMinimum")) and math.isclose(quality["aggregateAcceptanceMinimum"], 0.9, abs_tol=1e-12), "quality gate must be 90%", errors)
        require(quality.get("expectedRatingCount") == 400, "20*10*2 must yield 400 ratings", errors)
        require(quality.get("gateFormula") == "count(score >= 4) / 400 >= 0.90", "quality gate formula mismatch", errors)
        require(isinstance(quality.get("reviewRule"), str) and "independently" in quality["reviewRule"], "review independence rule is missing", errors)
        require(isinstance(quality.get("disagreementRule"), str) and bool(quality["disagreementRule"].strip()), "review disagreement rule is missing", errors)
        require(quality.get("executionStatus") == "NOT RUN", "quality execution must remain NOT RUN", errors)

    environment = corpus.get("testEnvironment")
    environment_allowed = {"name", "status", "requiredFingerprint", "requiredRunLanes", "requiredEvidence", "runEvidence"}
    environment_required = environment_allowed - {"runEvidence"}
    if strict_object(environment, "corpus.testEnvironment", environment_allowed, environment_required, errors):
        require(environment.get("name") == "release-a-staging", "staging name must be release-a-staging", errors)
        require(environment.get("status") in {"blocked_not_provisioned", "provisioned"}, "staging status is invalid", errors)
        fingerprint = environment.get("requiredFingerprint")
        fingerprint_allowed = {"pipelineVersion", "translationProvider", "modelSnapshot", "targetLanguage", "sttEnabled", "audioDownloadsAllowed"}
        if strict_object(fingerprint, "testEnvironment.requiredFingerprint", fingerprint_allowed, fingerprint_allowed, errors):
            translation = ledger.get("releaseAConfig", {}).get("translation", {})
            require(fingerprint.get("pipelineVersion") == EXPECTED_PIPELINE, "environment pipeline version mismatch", errors)
            require(fingerprint.get("translationProvider") == "OpenAI API", "environment provider mismatch", errors)
            require(fingerprint.get("modelSnapshot") == translation.get("modelSnapshot") == EXPECTED_D2_MODEL, "environment model snapshot mismatch", errors)
            require(fingerprint.get("targetLanguage") == "zh-Hant-TW", "environment target mismatch", errors)
            require(fingerprint.get("sttEnabled") is False and fingerprint.get("audioDownloadsAllowed") is False, "environment must preserve Release A red lines", errors)
        require(environment.get("requiredRunLanes") == EXPECTED_ENVIRONMENT_RUN_LANES, "staging run lanes must remain explicit", errors)
        require(environment.get("requiredEvidence") == EXPECTED_ENVIRONMENT_EVIDENCE, "staging evidence checklist must remain explicit", errors)
        if environment.get("status") == "blocked_not_provisioned":
            require("runEvidence" not in environment, "blocked staging cannot carry actual run evidence", errors)
        else:
            validate_run_evidence(environment.get("runEvidence"), "corpus.testEnvironment.runEvidence", errors)

    separation = corpus.get("fixtureSeparation")
    separation_allowed = {"releaseACorpusPurpose", "preflightRejectionFixtures", "serviceFailureFixtures", "rule"}
    if strict_object(separation, "corpus.fixtureSeparation", separation_allowed, separation_allowed, errors):
        preflight_fixtures = separation.get("preflightRejectionFixtures")
        service_fixtures = separation.get("serviceFailureFixtures")
        nonempty_string_list(preflight_fixtures, "fixtureSeparation.preflightRejectionFixtures", errors, minimum=7)
        nonempty_string_list(service_fixtures, "fixtureSeparation.serviceFailureFixtures", errors)
        if isinstance(preflight_fixtures, list) and isinstance(service_fixtures, list):
            require(set(preflight_fixtures).isdisjoint(service_fixtures), "preflight and service-failure fixtures must be separate", errors)
            for relative_path in preflight_fixtures + service_fixtures:
                require((ROOT / relative_path).is_file(), f"referenced fixture does not exist: {relative_path}", errors)
        require(isinstance(separation.get("releaseACorpusPurpose"), str) and "Only preflight-pass caption success" in separation["releaseACorpusPurpose"], "corpus purpose must exclude rejection/failure fixtures", errors)
        require(isinstance(separation.get("rule"), str) and "never enter" in separation["rule"], "fixture denominator rule is missing", errors)

    replacement = corpus.get("replacementPolicy")
    replacement_allowed = {"trigger", "action", "comparability", "freshness"}
    if strict_object(replacement, "corpus.replacementPolicy", replacement_allowed, replacement_allowed, errors):
        for field in replacement_allowed:
            require(isinstance(replacement.get(field), str) and bool(replacement[field].strip()), f"replacementPolicy.{field} must be non-empty", errors)
        require("Never relax" in replacement["action"] and "900 seconds" in replacement["action"], "replacement must not widen the 15-minute limit", errors)
        require("24 hours" in replacement["freshness"], "replacement policy needs a 24-hour freshness gate", errors)
        require("rerun all 20" in replacement["comparability"], "replacement must force a full-corpus rerun", errors)


def validate(ledger: dict, corpus: dict, schemas: dict[str, dict] | None = None) -> list[str]:
    errors: list[str] = []
    if schemas is not None:
        errors.extend(strict_schema_validate(ledger, schemas["decision-ledger"], "ledger", schemas["decision-ledger"]))
        errors.extend(strict_schema_validate(corpus, schemas["release-a-corpus"], "corpus", schemas["release-a-corpus"]))
    validate_ledger_shape(ledger, errors)
    validate_corpus_shape(corpus, ledger, errors)

    decisions = ledger.get("decisions", [])
    decision_ids = [item.get("id") for item in decisions if isinstance(item, dict)]
    require(len(decisions) == 6, "ledger must contain exactly six D1-D6 rows", errors)
    require(set(decision_ids) == EXPECTED_DECISIONS, "ledger IDs must be exactly D1-D6", errors)
    require(len(decision_ids) == len(set(decision_ids)), "ledger decision IDs must be unique", errors)
    by_id = {item.get("id"): item for item in decisions if isinstance(item, dict)}
    require(by_id.get("D1", {}).get("status") == "open_no_go", "D1 must remain OPEN/NO-GO", errors)
    require(by_id.get("D6", {}).get("status") == "decided", "D6 product limit must be decided", errors)
    d2_evidence = set(by_id.get("D2", {}).get("evidence", []))
    d3_evidence = set(by_id.get("D3", {}).get("evidence", []))
    require(EXPECTED_D2_OFFICIAL_EVIDENCE <= d2_evidence, "D2 evidence must include every frozen official provider/price source", errors)
    require(EXPECTED_D3_PACKAGE_EVIDENCE <= d3_evidence, "D3 evidence must point to the canonical corpus and verifier", errors)
    require(ledger.get("releaseBOverall") == "open_no_go", "Release B must remain OPEN/NO-GO", errors)

    release_b_cells = ledger.get("releaseBDecisionCells", {})
    if isinstance(release_b_cells, dict):
        d2_b = release_b_cells.get("D2-B", {})
        d3_b = release_b_cells.get("D3-B", {})
        require("decision-ledger.json:D1-D2" in d2_b.get("evidence", []), "D2-B evidence must trace to D1-D2", errors)
        require("release-a-corpus.json:scope=release_a_caption_only" in d3_b.get("evidence", []), "D3-B evidence must prove corpus separation", errors)
        require("Release B remains OPEN/NO-GO" in d2_b.get("releaseImpact", ""), "D2-B release impact must keep Release B OPEN/NO-GO", errors)
        require("Release B quality and launch remain OPEN/NO-GO" in d3_b.get("releaseImpact", ""), "D3-B release impact must keep Release B OPEN/NO-GO", errors)

    videos = corpus.get("videos", []) if isinstance(corpus, dict) else []
    verified_videos = [video for video in videos if isinstance(video, dict) and video.get("status") == "verified"]
    verified_count = len(verified_videos)
    summary = corpus.get("summary", {}) if isinstance(corpus, dict) else {}
    config = ledger.get("releaseAConfig", {})
    caption_provider = config.get("caption", {}).get("captionTextProvider", {}) if isinstance(config, dict) else {}
    evidence_status = ledger.get("evidenceStatus", {})
    environment = corpus.get("testEnvironment", {}) if isinstance(corpus, dict) else {}
    if verified_count == 0:
        require(by_id.get("D2", {}).get("status") == "blocked_no_go", "D2 must remain blocked while caption provider is absent", errors)
        require(by_id.get("D3", {}).get("status") == "blocked_no_go", "D3 must remain blocked while corpus is candidate-only", errors)
        require(ledger.get("releaseAOverall") == "blocked_no_go", "Release A must be NO-GO with zero verified videos", errors)
        require(config.get("activationStatus") == "blocked_no_go", "Release A activation must remain blocked with zero verified videos", errors)
        require(caption_provider.get("status") == "blocked" and caption_provider.get("provider") is None, "zero-verified baseline must retain blocked/null caption provider", errors)
        require(environment.get("status") == "blocked_not_provisioned", "zero-verified baseline must retain blocked staging", errors)
        require("runEvidence" not in environment, "zero-verified baseline must not carry fabricated run evidence", errors)
        require(summary.get("gateStatus") == "blocked_candidates_only", "zero-verified corpus must remain blocked_candidates_only", errors)
        require(evidence_status.get("captionProviderExecution") == "NOT RUN", "zero-verified baseline caption execution must remain NOT RUN", errors)
    elif verified_count != len(videos) or verified_count != 20:
        require(False, "partial verified promotion is forbidden; promotion must be all 20 videos", errors)
    else:
        require(by_id.get("D2", {}).get("status") == "decided", "verified promotion requires a decided D2 provider gate", errors)
        require(by_id.get("D3", {}).get("status") == "decided", "verified promotion requires a decided D3 corpus gate", errors)
        require(ledger.get("releaseAOverall") == "ready_for_run", "verified promotion requires a ready_for_run Release A gate", errors)
        require(config.get("activationStatus") == "ready_for_run", "verified promotion requires ready_for_run activation", errors)
        require(caption_provider.get("status") == "approved", "verified promotion requires an approved caption provider", errors)
        provider_name = caption_provider.get("provider")
        require(provider_name in KNOWN_APPROVED_CAPTION_PROVIDERS, "verified promotion provider must be externally approved, not fabricated", errors)
        nonempty_string_list(caption_provider.get("evidence"), "captionTextProvider.evidence", errors)
        require(evidence_status.get("captionProviderExecution") == "PASS", "verified promotion requires caption provider PASS evidence", errors)
        require(environment.get("status") == "provisioned", "verified promotion requires provisioned staging", errors)
        run_evidence = environment.get("runEvidence")
        validate_run_evidence(run_evidence, "corpus.testEnvironment.runEvidence", errors)
        require(summary.get("gateStatus") == "verified_ready_for_run", "verified promotion requires verified_ready_for_run corpus gate", errors)
        run_id = run_evidence.get("runId") if isinstance(run_evidence, dict) else None
        run_started_at = run_evidence.get("runStartedAt") if isinstance(run_evidence, dict) else None
        for video in verified_videos:
            evidence = video.get("verificationEvidence", {})
            require(evidence.get("runId") == run_id, f"verified video {video.get('videoId')} runId must match staging run evidence", errors)
            require(evidence.get("runStartedAt") == run_started_at, f"verified video {video.get('videoId')} runStartedAt must match staging run evidence", errors)

    translation = config.get("translation", {}) if isinstance(config, dict) else {}
    budget = translation.get("aggregateTokenBudgetPerAttempt", {}) if isinstance(translation, dict) else {}
    prices = translation.get("priceUsdPerMillionTokens", {}) if isinstance(translation, dict) else {}
    cost = config.get("providerCost", {}) if isinstance(config, dict) else {}
    try:
        attempts = 1 + int(translation.get("maxAutomaticRetries", -1))
        calculated_base_cost = attempts * (float(budget.get("input", 0)) / 1_000_000 * float(prices.get("input", 0)) + float(budget.get("output", 0)) / 1_000_000 * float(prices.get("output", 0)))
        calculated_cost = calculated_base_cost * (1 + float(prices.get("regionalProcessingUpliftMaximum", 0)))
    except (TypeError, ValueError):
        calculated_base_cost = calculated_cost = float("nan")
    require(math.isclose(calculated_base_cost, 0.126, abs_tol=1e-9), "LLM base worst-case formula must equal USD 0.126", errors)
    require(is_number(cost.get("llmBaseWorstCaseUsd")) and math.isclose(cost.get("llmBaseWorstCaseUsd", -1), calculated_base_cost, abs_tol=1e-9), "stored base LLM cost must match formula", errors)
    require(math.isclose(calculated_cost, 0.1386, abs_tol=1e-9), "LLM uplifted worst-case formula must equal USD 0.1386", errors)
    require(is_number(cost.get("llmWorstCaseUsd")) and math.isclose(cost.get("llmWorstCaseUsd", -1), calculated_cost, abs_tol=1e-9), "stored LLM cost must match formula", errors)
    if is_number(cost.get("hardCapUsd")) and is_number(cost.get("llmWorstCaseUsd")):
        require(cost["hardCapUsd"] >= cost["llmWorstCaseUsd"], "hard cost cap is below worst-case LLM spend", errors)
        expected_remaining = cost["hardCapUsd"] - cost["llmWorstCaseUsd"]
        require(
            is_number(cost.get("remainingCaptionProviderAllowanceUsd"))
            and math.isclose(cost["remainingCaptionProviderAllowanceUsd"], expected_remaining, abs_tol=1e-9),
            "remaining caption-provider allowance must equal hard cap minus LLM worst case",
            errors,
        )
    return errors


def run_mutation_probes(ledger: dict, corpus: dict, schemas: dict[str, dict]) -> tuple[list[str], int]:
    """Run malformed copies through the same schema-plus-semantic entrypoint."""

    accepted: list[str] = []
    probe_count = 0

    def probe(name: str, mutated_ledger: dict, mutated_corpus: dict) -> None:
        nonlocal probe_count
        probe_count += 1
        if not validate(mutated_ledger, mutated_corpus, schemas):
            accepted.append(name)

    mutated = copy.deepcopy(ledger)
    mutated["decisions"][0].pop("deadlineRule")
    probe("missing_D1_deadlineRule", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["decisions"][0]["deadline"] = "2026-09-30T17:00:00"
    probe("deadline_without_timezone", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    for timeout_name in mutated["releaseAConfig"]["timeoutsMs"]:
        mutated["releaseAConfig"]["timeoutsMs"][timeout_name] = 0
    probe("zero_D2_timeouts", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["releaseAConfig"]["translation"]["priceUsdPerMillionTokens"]["source"] = "not-a-url"
    probe("invalid_price_source_url", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["releaseAConfig"]["translation"]["priceUsdPerMillionTokens"]["accessedAt"] = "2026-02-30"
    probe("invalid_price_access_date", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["decisions"][1]["evidence"] = []
    probe("empty_D2_evidence", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["releaseAConfig"]["translation"]["endpoint"] = "Chat Completions API"
    probe("wrong_responses_endpoint", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["releaseAConfig"]["translation"]["reasoningEffort"] = "minimal"
    probe("wrong_reasoning_effort", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["releaseAConfig"]["providerCost"]["llmWorstCaseFormula"] = "price * tokens"
    probe("invalid_cost_formula", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["releaseAConfig"]["providerCost"]["hardCapUsd"] = 0.1
    probe("cost_ceiling_below_worst_case", mutated, corpus)

    mutated_corpus = copy.deepcopy(corpus)
    mutated_corpus["testEnvironment"]["requiredFingerprint"]["modelSnapshot"] = "gpt-5.4-mini-floating"
    probe("inconsistent_model_fingerprint", ledger, mutated_corpus)

    mutated_corpus = copy.deepcopy(corpus)
    mutated_corpus["promotionGate"]["requiredEligibilityFlags"]["embeddable"] = False
    probe("false_D3_eligibility", ledger, mutated_corpus)

    mutated_corpus = copy.deepcopy(corpus)
    mutated_corpus["promotionGate"].pop("candidateToVerified")
    probe("removed_D3_promotion_rules", ledger, mutated_corpus)

    mutated_corpus = copy.deepcopy(corpus)
    mutated_corpus["promotionGate"].pop("evidenceSchema")
    probe("removed_D3_promotion_evidence", ledger, mutated_corpus)

    mutated_corpus = copy.deepcopy(corpus)
    mutated_corpus["videos"][0]["status"] = "verified"
    mutated_corpus["videos"][0]["unverifiedFields"] = []
    mutated_corpus["videos"][0]["verificationEvidence"] = {field: "junk" for field in EXPECTED_VERIFICATION_FIELDS}
    mutated_corpus["summary"].update({"candidateCount": 19, "verifiedCount": 1, "gateStatus": "blocked_candidates_only"})
    probe("junk_verified_evidence", ledger, mutated_corpus)

    mutated_corpus = copy.deepcopy(corpus)
    mutated_corpus["testEnvironment"]["requiredRunLanes"].pop()
    probe("missing_staging_run_lane", ledger, mutated_corpus)

    mutated_corpus = copy.deepcopy(corpus)
    mutated_corpus["testEnvironment"]["requiredEvidence"] = []
    probe("empty_staging_evidence", ledger, mutated_corpus)

    mutated_corpus = copy.deepcopy(corpus)
    mutated_corpus["qualityPlan"]["acceptableScoreMinimum"] = 3
    probe("invalid_quality_threshold", ledger, mutated_corpus)

    mutated = copy.deepcopy(ledger)
    mutated["releaseBDecisionCells"]["D2-B"]["evidence"] = []
    probe("empty_D2_B_evidence", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["releaseBDecisionCells"]["D3-B"]["deadline"] = "2026-09-30T17:00:00"
    probe("D3_B_deadline_without_timezone", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["unexpectedTopLevelProperty"] = True
    probe("unexpected_top_level_property", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["decisions"][0]["unknownDecisionField"] = "not allowed"
    probe("unexpected_decision_property", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["decisions"][0]["deadlineRule"] = 7
    probe("wrong_type_required_property", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["releaseAConfig"]["translation"]["modelSnapshot"] = ""
    probe("empty_required_property", mutated, corpus)

    mutated = copy.deepcopy(ledger)
    mutated["$schema"] = 1705
    probe("schema_only_reference_type", mutated, corpus)

    probe_now = datetime.now(timezone.utc).replace(microsecond=0)

    def timestamp(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    def fabricated_evidence(video: dict, run_started_at: datetime, checked_at: datetime, provider: str = "fabricated-caption-provider") -> dict:
        return {
            "runId": "fabricated-run-1705",
            "runStartedAt": timestamp(run_started_at),
            "checkedAt": timestamp(checked_at),
            "videosList": {
                "privacyStatus": "public",
                "liveBroadcastContent": "none",
                "embeddable": True,
                "durationSeconds": video["observedDurationSeconds"],
                "captionAvailable": True,
                "defaultAudioLanguage": "en",
            },
            "captionRetrieval": {
                "status": "approved_provider",
                "provider": provider,
                "language": "en",
                "sentenceTiming": True,
                "audioDownloads": 0,
                "sttCalls": 0,
            },
            "embedCheck": {"status": "pass", "player": "youtube_iframe"},
            "environmentFingerprint": {
                "environment": "release-a-staging",
                "pipelineVersion": EXPECTED_PIPELINE,
                "translationProvider": "OpenAI API",
                "modelSnapshot": EXPECTED_D2_MODEL,
                "targetLanguage": "zh-Hant-TW",
                "sttEnabled": False,
                "audioDownloadsAllowed": False,
            },
        }

    def one_fabricated_verified(base: dict, run_started_at: datetime, checked_at: datetime) -> dict:
        result = copy.deepcopy(base)
        result["videos"][0]["status"] = "verified"
        result["videos"][0]["unverifiedFields"] = []
        result["videos"][0]["verificationEvidence"] = fabricated_evidence(result["videos"][0], run_started_at, checked_at)
        result["summary"].update({"candidateCount": 19, "verifiedCount": 1, "gateStatus": "blocked_candidates_only"})
        return result

    valid_run_start = probe_now - timedelta(hours=1)
    valid_checked = probe_now
    probe(
        "single_verified_with_blocked_provider_staging",
        ledger,
        one_fabricated_verified(corpus, valid_run_start, valid_checked),
    )

    all_verified = copy.deepcopy(corpus)
    for video in all_verified["videos"]:
        video["status"] = "verified"
        video["unverifiedFields"] = []
        video["verificationEvidence"] = fabricated_evidence(video, valid_run_start, valid_checked)
    all_verified["summary"].update({"candidateCount": 0, "verifiedCount": 20, "gateStatus": "verified_ready_for_run"})
    probe("all_20_verified_with_blocked_provider_staging", ledger, all_verified)

    fabricated_provider = copy.deepcopy(ledger)
    fabricated_provider["releaseAConfig"]["caption"]["captionTextProvider"]["provider"] = "fabricated-caption-provider"
    probe("fabricated_caption_provider_name", fabricated_provider, corpus)

    stale_verified = one_fabricated_verified(corpus, probe_now - timedelta(hours=25), probe_now)
    probe("stale_verified_run_timestamp", ledger, stale_verified)

    future_checked_verified = one_fabricated_verified(corpus, valid_run_start, probe_now + timedelta(hours=1))
    probe("future_verified_checked_timestamp", ledger, future_checked_verified)

    future_run_verified = one_fabricated_verified(corpus, probe_now + timedelta(hours=1), probe_now + timedelta(hours=2))
    probe("future_verified_run_timestamp", ledger, future_run_verified)

    missing_run_timestamp = one_fabricated_verified(corpus, valid_run_start, valid_checked)
    missing_run_timestamp["videos"][0]["verificationEvidence"].pop("runStartedAt")
    probe("missing_verified_run_timestamp", ledger, missing_run_timestamp)

    space_datetime = copy.deepcopy(ledger)
    space_datetime["decisions"][0]["deadline"] = "2026-09-30 17:00:00+08:00"
    probe("space_separated_datetime", space_datetime, corpus)

    reversed_timestamps = one_fabricated_verified(corpus, valid_checked, valid_run_start)
    probe("verified_checked_before_run_timestamp", ledger, reversed_timestamps)
    return accepted, probe_count


def main() -> int:
    try:
        schemas = {name: load_json(path) for name, path in SCHEMA_PATHS.items()}
        ledger = load_json(LEDGER_PATH)
        corpus = load_json(CORPUS_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: JSON readback: {exc}")
        return 1

    errors = validate(ledger, corpus, schemas)
    mutation_false_negatives, probe_count = run_mutation_probes(ledger, corpus, schemas)
    if mutation_false_negatives:
        errors.append("mutation probes unexpectedly passed: " + ", ".join(mutation_false_negatives))
    if errors:
        print(f"FAIL: {len(errors)} gate error(s)")
        for error in errors:
            print(f"- {error}")
        return 1

    summary = corpus["summary"]
    print("PASS: #1705 Release A gate package")
    print("- schemas: 2 JSON schemas applied with dependency-free strict validator")
    print("- nested contract: exact keys/types/non-empty values enforced for D1-D6, D2-A/B and D3-A/B")
    print("- decisions: D1-D6 complete; Release A=BLOCKED/NO-GO; Release B=OPEN/NO-GO")
    print(f"- corpus: {len(corpus['videos'])} candidates; verified={summary['verifiedCount']}; maxObservedDuration={summary['maxObservedDurationSeconds']}s")
    print("- red lines: audio=false; STT=false; transcribing excluded; transcriptSource=caption only")
    print("- D2-A cost: regional-uplifted worst-case LLM USD 0.1386 <= direct-provider cap USD 0.15")
    print("- quality: 2 zh-Hant-TW reviewers; 1-5 rubric; acceptable>=4; aggregate>=90%; NOT RUN")
    print(f"- mutation probes: {probe_count - len(mutation_false_negatives)}/{probe_count} rejected")
    return 0


if __name__ == "__main__":
    sys.exit(main())
