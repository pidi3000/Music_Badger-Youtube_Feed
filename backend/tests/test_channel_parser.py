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
        ("https://youtu.be/CHANNEL_HANDLE", "handle", "@CHANNEL_HANDLE"),
        ("youtube.com/@CHANNEL_HANDLE", "handle", "@CHANNEL_HANDLE"),
        ("@CHANNEL_HANDLE", "handle", "@CHANNEL_HANDLE"),
        ("CHANNEL_HANDLE", "handle", "@CHANNEL_HANDLE"),
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
