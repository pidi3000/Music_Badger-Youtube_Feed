import pytest

from app.services.channel_parser import ChannelLinkParseError, parse_channel_link


@pytest.mark.parametrize(
    "raw, kind, value",
    [
        ("youtube.com/watch?v=VIDEO_ID", "video", "VIDEO_ID"),
        ("watch?si=xyz&v=VIDEO_ID", "video", "VIDEO_ID"),
        ("https://www.youtube.com/watch?v=VIDEO_ID&si=xyz", "video", "VIDEO_ID"),
        ("channel/CHANNEL_ID", "channel_id", "CHANNEL_ID"),
        ("UCabc", "channel_id", "UCabc"),
        ("youtube.com/@CHANNEL_HANDLE", "handle", "@CHANNEL_HANDLE"),
        ("@CHANNEL_HANDLE", "handle", "@CHANNEL_HANDLE"),
        ("CHANNEL_HANDLE", "handle", "@CHANNEL_HANDLE"),
        # youtu.be is YouTube's link shortener for videos only — it never
        # points at a channel, regardless of what the path looks like.
        ("https://youtu.be/VIDEO_ID", "video", "VIDEO_ID"),
        ("youtu.be/VIDEO_ID?si=xyz&t=30", "video", "VIDEO_ID"),
        # A share link to a specific tab of a channel is still a link to
        # the channel — the trailing segment must not break parsing.
        ("https://www.youtube.com/@hibbi_cusofficial/shorts", "handle", "@hibbi_cusofficial"),
        ("youtube.com/@CHANNEL_HANDLE/videos", "handle", "@CHANNEL_HANDLE"),
        ("youtube.com/@CHANNEL_HANDLE/streams/", "handle", "@CHANNEL_HANDLE"),
        ("youtube.com/channel/CHANNEL_ID/videos", "channel_id", "CHANNEL_ID"),
        ("UCabc/about", "channel_id", "UCabc"),
        # Query params in an arbitrary order/mix, and other video-permalink
        # shapes YouTube has shipped over the years.
        ("youtube.com/watch?list=PL123&v=VIDEO_ID&t=30s", "video", "VIDEO_ID"),
        ("https://m.youtube.com/watch?v=VIDEO_ID", "video", "VIDEO_ID"),
        ("https://music.youtube.com/watch?v=VIDEO_ID&feature=share", "video", "VIDEO_ID"),
        # An actual Short's own watch page (not a channel's Shorts tab).
        ("https://www.youtube.com/shorts/VIDEO_ID", "video", "VIDEO_ID"),
        ("youtube.com/shorts/VIDEO_ID?feature=share", "video", "VIDEO_ID"),
        ("youtube.com/embed/VIDEO_ID", "video", "VIDEO_ID"),
        ("youtube.com/v/VIDEO_ID", "video", "VIDEO_ID"),
        ("youtube.com/live/VIDEO_ID", "video", "VIDEO_ID"),
    ],
)
def test_good_examples(raw, kind, value):
    result = parse_channel_link(raw)
    assert result.kind == kind
    assert result.value == value


@pytest.mark.parametrize(
    "raw",
    [
        "@ab",
        "@abcd!",
        "v=VIDEO_ID",
        "",
        "   ",
        "youtube.com/watch?list=PL123",  # no v= param at all
        "youtube.com/shorts/",  # keyword with no id after it
        "youtube.com/channel/",  # same, for channel/
        "youtube.com/c/SomeCustomName",  # legacy custom URL, not supported
        "youtube.com/user/SomeUsername",  # legacy username, not supported
    ],
)
def test_bad_examples(raw):
    with pytest.raises(ChannelLinkParseError):
        parse_channel_link(raw)


def test_bare_channel_id_without_uc_prefix_is_treated_as_handle():
    result = parse_channel_link("SomeChannelName")
    assert result.kind == "handle"
    assert result.value == "@SomeChannelName"


def test_channel_slash_form_does_not_require_uc_prefix():
    result = parse_channel_link("channel/notUCstart")
    assert result.kind == "channel_id"
    assert result.value == "notUCstart"
