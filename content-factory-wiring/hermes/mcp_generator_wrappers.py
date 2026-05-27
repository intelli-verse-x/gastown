"""
mcp_generator_wrappers.py — expose content-factory's generators as MCP tools.

Without MCP, each generator (Veo, ElevenLabs, Hyperframes, Replicate, etc.)
is wrapped in a bespoke Python client. Hermes/Claude can't see them as tools.

With MCP, every generator becomes a tool the orchestrator can call:
  tool: contentx.veo_generate(prompt, duration, aspect)
  tool: contentx.elevenlabs_tts(text, voice_id, lufs)
  tool: contentx.hyperframes_render(scene_id, characters, prompt)

This file is the contract + skeleton server. Implement provider auth + actual
calls by filling in each `_call_*` function. Provider clients live in
content-factory and just need to be imported.

Run as:  python mcp_generator_wrappers.py --serve

For consumers (Hermes, Claude desktop, gt agents) add to mcp.json:
  {
    "mcpServers": {
      "contentx": {
        "command": "python",
        "args": ["/opt/contentx-wiring/hermes/mcp_generator_wrappers.py", "--serve"]
      }
    }
  }
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

try:
    from mcp.server import Server  # type: ignore
    from mcp.server.stdio import stdio_server  # type: ignore
    from mcp.types import Tool, TextContent  # type: ignore
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


TOOLS_SCHEMA = [
    {
        "name": "contentx.veo_generate",
        "description": "Generate a video clip via Veo. Returns URL to .mp4.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "duration_s": {"type": "number", "default": 4.0},
                "aspect_ratio": {"type": "string", "enum": ["9:16", "1:1", "16:9"]},
                "negative_prompt": {"type": "string"},
                "seed": {"type": "integer"},
            },
            "required": ["prompt", "aspect_ratio"],
        },
    },
    {
        "name": "contentx.elevenlabs_tts",
        "description": "TTS via ElevenLabs with target LUFS. Returns URL to .wav.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "voice_id": {"type": "string"},
                "stability": {"type": "number", "default": 0.5},
                "lufs_target": {"type": "number", "default": -14.0},
            },
            "required": ["text", "voice_id"],
        },
    },
    {
        "name": "contentx.hyperframes_render",
        "description": "Render a character scene via Hyperframes. Returns scene URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene_id": {"type": "string"},
                "characters": {"type": "array", "items": {"type": "string"}},
                "prompt": {"type": "string"},
                "style_ref_image_url": {"type": "string"},
                "previous_shot_url": {"type": "string"},
            },
            "required": ["scene_id", "prompt"],
        },
    },
    {
        "name": "contentx.replicate_image",
        "description": "Generate an image via Replicate (flux/sdxl/etc).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "model": {"type": "string", "default": "flux-1.1-pro"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "seed": {"type": "integer"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "contentx.audio_master",
        "description": "Master audio to platform LUFS / true-peak spec.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "audio_url": {"type": "string"},
                "platform": {"type": "string", "enum": ["youtube_shorts", "tiktok", "instagram_reels", "youtube_main"]},
            },
            "required": ["audio_url", "platform"],
        },
    },
    {
        "name": "contentx.suno_song",
        "description": "Compose a song via Suno given lyrics + style tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lyrics": {"type": "string"},
                "style_tags": {"type": "array", "items": {"type": "string"}},
                "duration_s": {"type": "number"},
            },
            "required": ["lyrics", "style_tags"],
        },
    },
]


# ---------------------------------------------------------------------------
# Provider stubs — fill in with real client imports from content-factory
# ---------------------------------------------------------------------------

async def _call_veo(p: dict[str, Any]) -> dict[str, Any]:
    # from content_factory.generators.veo import VeoClient
    # client = VeoClient(api_key=os.environ["GOOGLE_VEO_KEY"])
    # return await client.generate(**p)
    return {"status": "stub", "video_url": "s3://stub/veo_output.mp4", "params": p}


async def _call_elevenlabs(p: dict[str, Any]) -> dict[str, Any]:
    # from content_factory.generators.elevenlabs import ElevenLabsClient
    # client = ElevenLabsClient(api_key=os.environ["ELEVENLABS_API_KEY"])
    # return await client.tts(**p)
    return {"status": "stub", "audio_url": "s3://stub/eleven_output.wav", "params": p}


async def _call_hyperframes(p: dict[str, Any]) -> dict[str, Any]:
    return {"status": "stub", "scene_url": "s3://stub/hyperframes.mp4", "params": p}


async def _call_replicate(p: dict[str, Any]) -> dict[str, Any]:
    # import replicate
    # output = replicate.run(p.get("model","flux-1.1-pro"), input=p)
    return {"status": "stub", "image_url": "s3://stub/replicate.png", "params": p}


async def _call_audio_master(p: dict[str, Any]) -> dict[str, Any]:
    return {"status": "stub", "mastered_url": "s3://stub/mastered.wav", "params": p}


async def _call_suno(p: dict[str, Any]) -> dict[str, Any]:
    return {"status": "stub", "song_url": "s3://stub/song.mp3", "params": p}


HANDLERS = {
    "contentx.veo_generate": _call_veo,
    "contentx.elevenlabs_tts": _call_elevenlabs,
    "contentx.hyperframes_render": _call_hyperframes,
    "contentx.replicate_image": _call_replicate,
    "contentx.audio_master": _call_audio_master,
    "contentx.suno_song": _call_suno,
}


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

async def run_mcp() -> None:
    if not HAS_MCP:
        print("error: `mcp` package not installed. `pip install mcp`", file=sys.stderr)
        sys.exit(2)
    server = Server("contentx-generators")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(**t) for t in TOOLS_SCHEMA]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        handler = HANDLERS.get(name)
        if not handler:
            return [TextContent(type="text", text=json.dumps({"error": f"unknown tool {name}"}))]
        result = await handler(arguments)
        return [TextContent(type="text", text=json.dumps(result))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def emit_schema() -> None:
    """Print the tool schema as JSON so consumers can register without running the server."""
    print(json.dumps(TOOLS_SCHEMA, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true", help="Run MCP stdio server")
    ap.add_argument("--schema", action="store_true", help="Print tool schema and exit")
    args = ap.parse_args()
    if args.schema:
        emit_schema()
        return
    if args.serve:
        asyncio.run(run_mcp())
        return
    ap.print_help()


if __name__ == "__main__":
    main()
