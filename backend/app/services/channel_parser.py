"""Parses the "Channel Link" field into video/channel-ID/handle. Originally
ported forward from the v2 README's rules (see PROJECT_OUTLINE.md §2
"Manual channel management"), since generalized to tolerate the actual
variety of links YouTube produces: extra path segments after a handle or
channel ID (e.g. a share link to a channel's Shorts tab), the video-id-only
`youtu.be` short-link form, `/shorts/`, `/embed/`, `/v/`, and `/live/`
video permalinks, and query parameters in any order/combination.
"""

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import unquote

_HANDLE_RE = re.compile(r"[A-Za-z0-9_.-]+")
_YOUTU_BE_RE = re.compile(r"youtu\.be", re.IGNORECASE)
# Matches youtube.com and its other first-party hostnames (m., music.,
# youtube-nocookie.com) — the search-and-take-remainder approach in
# _split_domain doesn't care what precedes the match, so a "www."/"m."/
# "music." prefix (or none at all) is already handled without special-casing.
_YOUTUBE_COM_RE = re.compile(r"youtube(?:-nocookie)?\.com", re.IGNORECASE)

# A path segment right after the domain that means "what follows is a video
# id", for every video-permalink shape YouTube has shipped.
_VIDEO_PATH_KEYWORDS = {"shorts", "embed", "v", "live"}

ParsedKind = Literal["video", "channel_id", "handle"]


@dataclass(frozen=True)
class ParsedLink:
    kind: ParsedKind
    value: str


class ChannelLinkParseError(ValueError):
    pass


def _split_domain(text: str) -> tuple[str | None, str]:
    """Returns (which YouTube domain matched, everything after it) — or
    (None, text unchanged) if neither did, so the caller can treat the
    whole input as a bare path (e.g. "channel/UC...", "@handle", or a plain
    handle guess pasted without a URL around it)."""

    for name, pattern in (("youtu.be", _YOUTU_BE_RE), ("youtube.com", _YOUTUBE_COM_RE)):
        match = pattern.search(text)
        if match:
            return name, text[match.end() :].lstrip("/")
    return None, text


def _strip_query_and_fragment(text: str) -> str:
    for sep in ("?", "#"):
        index = text.find(sep)
        if index != -1:
            text = text[:index]
    return text


def _path_segments(text: str) -> list[str]:
    return [segment for segment in _strip_query_and_fragment(text).split("/") if segment]


def _parse_query(query: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        if key:
            params[key] = unquote(value)
    return params


def _query_string(text: str) -> str:
    index = text.find("?")
    return text[index + 1 :] if index != -1 else ""


def _parse_path(remainder: str, raw: str) -> ParsedLink:
    segments = _path_segments(remainder)
    if not segments:
        raise ChannelLinkParseError(f"could not parse channel link: {raw!r}")

    first, rest = segments[0], segments[1:]
    first_lower = first.lower()

    if first_lower == "watch":
        video_id = _parse_query(_query_string(remainder)).get("v")
        if video_id:
            return ParsedLink(kind="video", value=video_id)
        raise ChannelLinkParseError("missing 'v' parameter after 'watch?'")

    if first_lower in _VIDEO_PATH_KEYWORDS:
        if rest and rest[0]:
            return ParsedLink(kind="video", value=rest[0])
        raise ChannelLinkParseError(f"missing video id after '{first_lower}/'")

    if first_lower == "channel":
        if rest and rest[0]:
            return ParsedLink(kind="channel_id", value=rest[0])
        raise ChannelLinkParseError("empty channel ID after 'channel/'")

    if first_lower in ("c", "user"):
        raise ChannelLinkParseError(
            "legacy /c/ or /user/ custom URLs aren't supported — use the channel's "
            "@handle, its youtube.com/channel/UC... link, or a video link instead"
        )

    # A bare channel ID, with or without a trailing tab like "/videos" —
    # only the first segment is the ID, so that trailing path never leaks
    # into it.
    if first.startswith("UC"):
        return ParsedLink(kind="channel_id", value=first)

    # Handle, similarly tolerant of a trailing "/videos", "/shorts",
    # "/streams", etc. — a share link to a specific tab of the channel is
    # still a link to the channel.
    handle_candidate = first[1:] if first.startswith("@") else first
    if len(handle_candidate) > 3 and _HANDLE_RE.fullmatch(handle_candidate):
        return ParsedLink(kind="handle", value=f"@{handle_candidate}")

    raise ChannelLinkParseError(f"could not parse channel link: {raw!r}")


def parse_channel_link(raw: str) -> ParsedLink:
    text = raw.strip()
    if not text:
        raise ChannelLinkParseError("channel link is empty")

    domain, remainder = _split_domain(text)

    if domain == "youtu.be":
        # youtu.be is YouTube's link-shortener for videos only — it never
        # points at a channel, so the whole path (sans query/fragment) is
        # unconditionally a video id, unlike youtube.com's many shapes.
        segments = _path_segments(remainder)
        if segments:
            return ParsedLink(kind="video", value=segments[0])
        raise ChannelLinkParseError(f"could not parse channel link: {raw!r}")

    # domain == "youtube.com", or no recognized domain at all — in the
    # latter case `remainder` is just `text` unchanged, so a bare
    # "watch?v=...", "channel/UC...", "@handle", or plain handle guess
    # (all supported without a URL wrapped around them) is parsed exactly
    # like the same shape would be after stripping youtube.com off a real
    # link.
    return _parse_path(remainder, raw)
