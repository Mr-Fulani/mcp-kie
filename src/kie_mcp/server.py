"""Local stdio MCP facade; all paid media runs through KieService approvals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from .catalog import CATALOG, get_catalog_entry, search_catalog
from .client import KieClient, fetch_documentation
from .config import Settings
from .errors import KieAPIError
from .ledger import GuardError
from .network import fetch_bytes
from .security import redact
from .service import KieService

try:
    settings = Settings.from_env()
except Exception:
    raise SystemExit("Invalid owner configuration; sensitive details withheld.") from None
client = KieClient(settings)
service = KieService(settings, client)
mcp = FastMCP(
    "Secure KIE media",
    instructions=(
        "Local stdio media tools. Discover live models/schema/pricing first. "
        "kie_create_task defaults to dry_run; prepare reserves budget; execute requires "
        "the approval_id and unchanged request. Unknown pricing is blocked without "
        "an owner-configured exact-input quote. Without model, friendly tools return "
        "a comparison: show options and let the user choose. auto_select=true is only "
        "for explicitly delegated cheapest selection among the first 20 candidates. "
        "With model, friendly tools prepare one task, or "
        "preview an explicit model with dry_run=true (image preview may upload); "
        "execute, wait and download separately. Never bypass these guards with shell/API skills."
    ),
    json_response=True,
)


def identity(ctx: Context) -> None:
    params = ctx.session.client_params
    if params:
        service.client_name = params.clientInfo.name[:100]
        service.client_version = params.clientInfo.version[:100]


async def safe_call(coro: Any) -> dict[str, Any]:
    try:
        value = await coro
        result = value if isinstance(value, dict) else {"data": value}
        cleaned = redact(result, settings.api_key)
        # A server-generated result path inside the configured root is intended output.
        for key in ("output_path", "output_folder"):
            output = result.get(key)
            if output and settings.allowed_download_root is not None:
                Path(output).resolve().relative_to(settings.allowed_download_root.resolve())
                cleaned[key] = output
        return cleaned
    except GuardError as exc:
        return {"error": redact(str(exc), settings.api_key), "blocked": True}
    except KieAPIError as exc:
        return redact(exc.as_dict(), settings.api_key)
    except Exception:
        return {"error": "Operation failed; sensitive details withheld."}


@mcp.resource("kie://docs/overview")
def docs_overview() -> str:
    return json.dumps(
        {
            "transport": "stdio",
            "api_base": settings.api_base,
            "upload_base": settings.upload_base,
            "paid_flow": "prepare/execute",
            "unknown_pricing": "blocked",
            "temporary_results": True,
        }
    )


@mcp.resource("kie://docs/catalog")
def docs_catalog() -> str:
    return json.dumps(CATALOG, ensure_ascii=False)


@mcp.resource("kie://docs/entry/{slug}")
def docs_entry(slug: str) -> str:
    return json.dumps(get_catalog_entry(slug) or {"error": "Unknown documentation slug"})


@mcp.tool()
async def kie_search_docs(query: str, limit: int = 10) -> dict[str, Any]:
    """Search the live official Markdown index, with an explicitly labelled offline fallback."""
    try:
        raw = await fetch_bytes(
            "https://docs.kie.ai/llms.txt", 2_000_000, allowed_hosts={"docs.kie.ai"}
        )
        import re

        lines = raw.decode("utf-8").splitlines()
        matches = []
        tokens = query.lower().split()
        for line in lines:
            match = re.search(r"\[([^]]+)\]\((https://docs\.kie\.ai/[^)]+)\)", line)
            if match and (not tokens or any(token in line.lower() for token in tokens)):
                matches.append({"title": match[1], "url": match[2]})
        return {"source": "live_docs_index", "results": matches[: max(1, min(limit, 50))]}
    except Exception:
        return {
            "source": "bundled_offline_fallback",
            "results": search_catalog(query, limit),
            "warning": "Live index unavailable; bundled entries may be stale.",
        }


@mcp.tool()
async def kie_get_documentation(slug_or_url: str, max_characters: int = 60_000) -> dict:
    """Fetch current official Markdown by bundled slug or HTTPS docs.kie.ai URL."""

    async def get():
        entry = get_catalog_entry(slug_or_url)
        url = entry["url"] if entry else slug_or_url
        text = await fetch_documentation(url)
        limit = max(1000, min(max_characters, 200_000))
        return {"url": url, "content": text[:limit], "truncated": len(text) > limit}

    return await safe_call(get())


@mcp.tool()
async def kie_list_models(query: str = "", task_type: str | None = None) -> dict:
    """Discover live KIE models; the model list is never hardcoded."""
    return await safe_call(service.search_models(query, task_type))


@mcp.tool()
async def kie_get_model_schema(model: str) -> dict:
    """Get a live unified-media contract with local references resolved."""
    return await safe_call(service.contract(model))


@mcp.tool()
async def kie_estimate_cost(model: str, input: dict[str, Any]) -> dict:
    """Validate live schema and return operation-specific price/source/confidence."""
    return await safe_call(service.estimate(model, input))


@mcp.tool()
async def kie_prepare_task(ctx: Context, model: str, input: dict[str, Any], dry_run: bool = False):
    """Reserve shared budget and return immutable approval; dry-run never reserves or submits."""
    identity(ctx)
    return await safe_call(service.prepare(model, input, dry_run=dry_run))


@mcp.tool()
async def kie_create_task(
    ctx: Context,
    model: str,
    input: dict[str, Any],
    dry_run: bool = True,
    approval_id: str | None = None,
):
    """Compatibility entry: preview by default; real submission requires a prepared approval."""
    identity(ctx)
    if dry_run:
        return await safe_call(service.prepare(model, input, dry_run=True))
    if approval_id is None:
        return {
            "error": "Prepare first; approval_id is required for paid execution",
            "blocked": True,
        }
    return await safe_call(service.execute(approval_id, model, input))


@mcp.tool()
async def kie_execute_task(ctx: Context, approval_id: str, model: str, input: dict[str, Any]):
    """Execute one immutable prepared request. Ambiguous submissions are never retried."""
    identity(ctx)
    return await safe_call(service.execute(approval_id, model, input))


@mcp.tool()
async def kie_get_task(task_id: str):
    """Get asynchronous task state/results and reconcile recorded usage when terminal."""
    return await safe_call(service.get_task(task_id))


@mcp.tool()
async def kie_wait_for_task(task_id: str, timeout_seconds: int = 900):
    """Poll with 2/3/5/8/10/15-second backoff and the owner's timeout ceiling."""
    return await safe_call(service.wait(task_id, max(1, timeout_seconds)))


@mcp.tool()
async def kie_get_credits():
    """Read the media-key account balance."""
    return await safe_call(client.get_credits())


@mcp.tool()
async def kie_upload_local_file(file_path: str):
    """Validate sandbox, size and media bytes, then upload a bounded snapshot."""
    return await safe_call(client.upload_local_file(file_path, "mcp/files", None))


@mcp.tool()
async def kie_upload_base64(base64_data: str):
    """Validate decoded size and media bytes before temporary upload."""
    return await safe_call(client.upload_base64(base64_data, "mcp/base64", None))


@mcp.tool()
async def kie_upload_from_url(file_url: str):
    """Fetch with pinned-DNS/redirect/byte guards, validate media and upload the bytes."""
    return await safe_call(client.upload_from_url(file_url, "mcp/url", None))


@mcp.tool()
async def kie_get_download_url(url: str):
    """Resolve a temporary download link for an allowlisted KIE storage URL."""
    return await safe_call(client.get_download_url(url))


@mcp.tool()
async def kie_download_result(task_id: str, result_index: int = 0, result_label: str | None = None):
    """Save into a readable date/type/model/task folder; result_label is short text, not a path."""
    return await safe_call(service.download(task_id, result_index, result_label))


@mcp.tool()
async def kie_compare_models(
    operation: str,
    prompt: str = "",
    image_path: str | None = None,
    image_url: str | None = None,
    parameters: dict | None = None,
    model_input: dict | None = None,
    query: str = "",
    cursor: int = 0,
    limit: int = 5,
    include_metrics: bool = False,
):
    """Compare live models/costs/capabilities for user choice; no uploads or paid reservations.

    operation is generate_image, edit_image, generate_video, remove_background,
    upscale_image or product_image_create. parameters supplies friendly duration,
    resolution, aspect_ratio, output_format, scale or target_resolution. Show options
    to the user; paginate with next_cursor. Quality prose is a provider claim, not a score.
    """
    return await safe_call(
        service.compare_models(
            operation,
            prompt,
            image_path,
            image_url,
            parameters,
            model_input,
            query=query,
            cursor=cursor,
            limit=limit,
            include_metrics=include_metrics,
        )
    )


@mcp.tool()
async def generate_image(
    ctx: Context,
    prompt: str,
    model: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    output_format: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
):
    """Show choices without model; with model prepare/preview one image.

    auto_select=true explicitly opts into cheapest selection.
    """
    identity(ctx)
    params = {
        k: v
        for k, v in {
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        }.items()
        if v is not None
    }
    return await safe_call(
        service.friendly(
            "generate_image",
            prompt,
            model,
            parameters=params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
        )
    )


@mcp.tool()
async def edit_image(
    ctx: Context,
    prompt: str,
    image_path: str | None = None,
    image_url: str | None = None,
    model: str | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    output_format: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
):
    """Show choices without model; with model prepare/preview an edit (may upload)."""
    identity(ctx)
    params = {
        k: v
        for k, v in {
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        }.items()
        if v is not None
    }
    return await safe_call(
        service.friendly(
            "edit_image",
            prompt,
            model,
            image_path,
            image_url,
            params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
        )
    )


@mcp.tool()
async def generate_video(
    ctx: Context,
    prompt: str,
    image_path: str | None = None,
    image_url: str | None = None,
    model: str | None = None,
    duration: int | None = None,
    aspect_ratio: str | None = None,
    resolution: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
):
    """Show choices without model; with model prepare/preview video (image preview may upload)."""
    identity(ctx)
    params = {
        k: v
        for k, v in {
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }.items()
        if v is not None
    }
    return await safe_call(
        service.friendly(
            "generate_video",
            prompt,
            model,
            image_path,
            image_url,
            params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
        )
    )


@mcp.tool()
async def remove_background(
    ctx: Context,
    image_path: str | None = None,
    image_url: str | None = None,
    model: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
):
    """Show choices without model; with model prepare/preview background removal (may upload)."""
    identity(ctx)
    return await safe_call(
        service.friendly(
            "remove_background",
            model=model,
            image_path=image_path,
            image_url=image_url,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
        )
    )


@mcp.tool()
async def upscale_image(
    ctx: Context,
    image_path: str | None = None,
    image_url: str | None = None,
    scale: int | None = None,
    target_resolution: str | None = None,
    model: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
):
    """Show choices without model; with model prepare/preview one upscale (may upload)."""
    identity(ctx)
    params = {
        k: v
        for k, v in {"scale": scale, "target_resolution": target_resolution}.items()
        if v is not None
    }
    return await safe_call(
        service.friendly(
            "upscale_image",
            model=model,
            image_path=image_path,
            image_url=image_url,
            parameters=params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
        )
    )


@mcp.tool()
async def product_image_create(
    ctx: Context,
    image_path: str,
    style: str = "ecommerce",
    background: str = "white",
    aspect_ratio: str = "3:4",
    resolution: str | None = None,
    product_name: str | None = None,
    model: str | None = None,
    output_format: str | None = None,
    dry_run: bool = False,
    model_input: dict | None = None,
    auto_select: bool = False,
):
    """Show choices without model; with model prepare/preview a product edit (may upload)."""
    identity(ctx)
    prompt = (
        f"Create a professional {style} product photo of {product_name or 'the product'}. "
        f"Use a {background} background. Preserve the product exactly."
    )
    params = {"aspect_ratio": aspect_ratio}
    if resolution:
        params["resolution"] = resolution
    if output_format:
        params["output_format"] = output_format
    return await safe_call(
        service.friendly(
            "product_image_create",
            prompt,
            model,
            image_path=image_path,
            parameters=params,
            dry_run=dry_run,
            model_input=model_input,
            auto_select=auto_select,
        )
    )


def main() -> None:
    if settings.transport != "stdio":
        raise SystemExit("Only local stdio transport is permitted.")
    try:
        settings.require_api_key()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
