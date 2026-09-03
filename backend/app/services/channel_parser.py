"""Parses the "Channel Link" field into video/channel-ID/handle, per the
rules documented in the original README (ported forward verbatim — see
PROJECT_OUTLINE.md §2 "Manual channel management").
"""

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote

_DOMAIN_RE = re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE)
_HANDLE_RE = re.compile(r"[A-Za-z0-9_.-]+")

ParsedKind = Literal["video", "channel_id", "handle"]


@dataclass(frozen=True)
class ParsedLink:
    kind: ParsedKind
    value: str


class ChannelLinkParseError(ValueError):
    pass


def _strip_youtube_domain(text: str) -> str:
    match = _DOMAIN_RE.search(text)
    if not match:
        return text
    remainder = text[match.end() :]
    return remainder.lstrip("/")


def _parse_query(query: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        if key:
            params[key] = unquote(value)
    return params


def parse_channel_link(raw: str) -> ParsedLink:
    text = raw.strip()
    if not text:
        raise ChannelLinkParseError("channel link is empty")

    text = _strip_youtube_domain(text)

    if text.startswith("watch?"):
        params = _parse_query(text[len("watch?") :])
        video_id = params.get("v")
        if video_id:
            return ParsedLink(kind="video", value=video_id)
        raise ChannelLinkParseError("missing 'v' parameter after 'watch?'")

    if text.startswith("channel/"):
        channel_id = text[len("channel/") :]
        if channel_id:
            return ParsedLink(kind="channel_id", value=channel_id)
        raise ChannelLinkParseError("empty channel ID after 'channel/'")

    if text.startswith("UC"):
        return ParsedLink(kind="channel_id", value=text)

    handle_candidate = text[1:] if text.startswith("@") else text
    if len(handle_candidate) > 3 and _HANDLE_RE.fullmatch(handle_candidate):
        return ParsedLink(kind="handle", value=f"@{handle_candidate}")

    raise ChannelLinkParseError(f"could not parse channel link: {raw!r}")
