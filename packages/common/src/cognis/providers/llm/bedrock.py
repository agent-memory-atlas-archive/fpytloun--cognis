"""Bedrock catalog access using the same AWS SDK credential chain as S3."""

from __future__ import annotations

import asyncio
from typing import Any


async def discover_bedrock_models(
    *, region: str | None = None, profile: str | None = None, include_profiles: bool = True
) -> list[dict[str, Any]]:
    """List invocable foundation models and active inference profiles."""
    return await asyncio.to_thread(_discover, region, profile, include_profiles)


def _discover(
    region: str | None, profile: str | None, include_profiles: bool
) -> list[dict[str, Any]]:
    import boto3
    from botocore.config import Config

    session = boto3.Session(profile_name=profile, region_name=region)
    client = session.client(
        "bedrock",
        config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1}),
    )
    records: list[dict[str, Any]] = []
    try:
        data = client.list_foundation_models()
        for model in data.get("modelSummaries", []):
            if model.get("modelLifecycle", {}).get("status") == "LEGACY":
                continue
            if "ON_DEMAND" not in model.get("inferenceTypesSupported", []):
                continue
            embedding = "EMBEDDING" in model.get("outputModalities", [])
            if not embedding and "TEXT" not in model.get("outputModalities", []):
                continue
            records.append(
                {
                    "model_id": model["modelId"],
                    "name": model["modelId"],
                    "display_name": model.get("modelName"),
                    "model_mode": "embedding" if embedding else "chat",
                    "supports_embedding": embedding,
                    "supports_streaming": bool(model.get("responseStreamingSupported")),
                }
            )
        if not include_profiles:
            return records
        token: str | None = None
        while True:
            params: dict[str, Any] = {"maxResults": 100}
            if token:
                params["nextToken"] = token
            data = client.list_inference_profiles(**params)
            for entry in data.get("inferenceProfileSummaries", []):
                if entry.get("status") != "ACTIVE":
                    continue
                records.append(
                    {
                        "model_id": entry["inferenceProfileId"],
                        "name": entry["inferenceProfileId"],
                        "display_name": entry.get("inferenceProfileName"),
                        "model_mode": "chat",
                        "supports_embedding": False,
                    }
                )
            token = data.get("nextToken")
            if not token:
                break
        return records
    finally:
        client.close()
