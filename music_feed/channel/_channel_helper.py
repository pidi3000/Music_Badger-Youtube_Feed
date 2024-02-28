
import re

from ..extension import db
from ..db_models import Tag, Channel

from ..youtube import youtube_data as yt_data
from music_feed.config import app_config


###########################################################################################
# Form Handler
###########################################################################################


# TODO remove tags_old use channel.tags instead
def handle_form(channel, form, tags_old):
    name = form['name']
    yt_id = extract_channel_id(form["yt_id"])

    if len(yt_id) < 1:
        error_msg = "ERROR: no youtube channel ID"
        print(error_msg)
        return error_msg

    # Create new channel entry
    if channel == None:

        # Check yt_id already in DB
        temp = Channel.query.filter_by(yt_id=yt_id).first()

        if temp:
            error_msg = "ERROR: Channel already in DB"
            print(error_msg)
            return error_msg

        channel = Channel()

    channel_data = yt_data.get_channel_data(yt_id)
    # check channel data found / channel ID is valid
    if "error" in channel_data:
        # print(channel_data["error"])
        return channel_data["error"]

    if len(name) < 1:
        name = channel_data["name"]

    # yt_id = channel_data["id"]

    channel.name = name
    # channel.yt_link = yt_link
    channel.yt_id = yt_id
    channel.profile_img_url = channel_data["profile_img_url"]

    db.session.add(channel)
    db.session.commit()

    tags_name = form.getlist("tags")
    tags_new = []

    print(tags_name)

    # turn tag name list to Tag object list
    for tag_name in tags_name:
        tag = Tag.query.filter_by(name=tag_name).first()
        tags_new.append(tag)

    tags_old = set(tags_old)
    tags_new = set(tags_new)

    tags_delete = tags_old - tags_new
    tags_add = tags_new - tags_old

    # print()
    # print()
    # print(form)
    # print()
    # print(tags_name)
    # print(channel.id)
    # print(tags_old)
    # print(tags_new)
    # print()
    # print("Delete")
    # print(tags_delete)
    # print()

    for tag in tags_delete:
        channel.tags.remove(tag)
    #     print(tag)
    #     print(channel_tag)
    #     print()

    # print()
    # print()

    # print("Add")
    # print(tags_add)
    # print()
    for tag in tags_add:
        channel.tags.append(tag)

    #     print(tag)
    #     print(channel_tag)
    #     print()

    # print()
    # print()
    # print()

    db.session.commit()


def handle_form_tags(channel, tags_name: list[str]):

    tags_new = []

    print(tags_name)

    # turn tag name list to Tag object list
    for tag_name in tags_name:
        tag = Tag.query.filter_by(name=tag_name).first()
        tags_new.append(tag)

    tags_old = set(channel.tags)
    tags_new = set(tags_new)

    tags_delete = tags_old - tags_new
    tags_add = tags_new - tags_old

    for tag in tags_delete:
        channel.tags.remove(tag)

    for tag in tags_add:
        channel.tags.append(tag)

    db.session.commit()


###########################################################################################
# Helper Functions
###########################################################################################

def extract_channel_id(channel_string):
    yt_id = None

    # Can be:
    # - just the channel ID
    # - video URL from channel
    # - channel URL ONLY if the ID is contained (NOT a custom URL like @mychannelname)

    # Regular expressions to match different YouTube channel URL formats
    patterns = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
        r'(?:https?://)?(?:www\.)?youtube\.com/channel/([a-zA-Z0-9_-]+)',
        r'([a-zA-Z0-9_-]+)',
    ]

    # Loop through patterns to find a match
    for pattern in patterns:
        match = re.search(pattern, channel_string)
        if match:
            yt_id = match.group(1)

            if pattern == patterns[0]:  # matched the video URL pattern
                yt_id = yt_data.get_channel_ID_from_video(video_id=yt_id)

            break

    if yt_id is None:
        raise LookupError("No channel or video ID pattern matched")

    return yt_id

###########################################################################################
# Helper Functions
###########################################################################################


def handle_import_channel(request):  # TODO add error handling

    import_source = request.args.get("source")
    print(import_source)

    if import_source == "youtube":
        all_subs = yt_data.get_all_subscriptions()

        print()
        print(len(all_subs))
        print()

        for sub in all_subs:
            new_channel = Channel.create(
                sub["id"], sub["name"], sub["profile_img_url"])

            if isinstance(new_channel, str):
                # print(new_channel)
                pass

        db.session.commit()
        # db.session.rollback()


###########################################################################################
# Get Channels using filter tags
###########################################################################################
def _get_Channels_Tagged_v1(filter_tag_id: int) -> list[Channel]:
    if filter_tag_id is None:
        filter_tag_id = -1

    if filter_tag_id < 0:
        all_channels = Channel.get_all_latest()

        # Get all channels
        if filter_tag_id == -1:
            return all_channels

        # Get untagged channels
        if filter_tag_id == -2:
            untagged_channels = []
            for channel in all_channels:
                channel: Channel
                tags = channel.tags

                if len(tags) == 0:
                    untagged_channels.append(channel)

            return untagged_channels

    # Get filtered channels

    filter_tag: Tag = Tag.get_by_ID(filter_tag_id)

    tagged_channels = []

    if filter_tag:
        tagged_channels = filter_tag.channels

        tagged_channels = sorted(
            tagged_channels, key=lambda x: x.id, reverse=True)

    return tagged_channels


def _get_next_channels(channel_list: list[Channel], last_channel_id: int | None = None) -> list[Channel]:
    if not isinstance(last_channel_id, int):
        return channel_list

    last_channel = Channel.query.filter_by(
        id=last_channel_id).first()

    if last_channel:
        cut_off_idx = 0
        for idx, channel in enumerate(channel_list):
            if channel.id >= last_channel_id:
                cut_off_idx = idx

        cut_off_idx = cut_off_idx + 1
        # print("cut_off_idx: ", cut_off_idx)
        # print("list length: ", len(tagged_uploads))
        if len(channel_list) > cut_off_idx:
            channel_list = channel_list[cut_off_idx:]
        # print("list length: ", len(tagged_uploads))

    return channel_list


def _limit_channels_list(channel_list: list[Channel]):
    if len(channel_list) > app_config.yt_feed.channels_per_page:
        channel_list = channel_list[:app_config.yt_feed.channels_per_page]

    return channel_list


def get_Channels_Tagged_dict(last_channel_id: int | None = None, filter_tag_id: int | None = None) -> list[dict]:

    channels = _get_Channels_Tagged_v1(filter_tag_id)
    channels = _get_next_channels(channels, last_channel_id)
    channels = _limit_channels_list(channels)

    channel_list = []
    for channel in channels:
        channel: Channel
        channel_list.append(channel.toDict(include_tags=True))

    return channel_list
