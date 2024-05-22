
import time

import asyncio
from concurrent.futures import ThreadPoolExecutor

from music_feed.extension import db
from music_feed.config import app_config
from music_feed.db_models import Upload, Channel
from music_feed.youtube.uploads._base import YT_Uploads_Handler_Base
from music_feed.youtube.uploads.web import YT_Uploads_Handler_WEB
from music_feed.youtube.uploads.api import YT_Uploads_Handler_API

####################################################################################################
####################################################################################################


def update_channel(channel: Channel):
    # print(f"Start channel: {channel.name}")

    uploads_handler: YT_Uploads_Handler_Base = YT_Uploads_Handler_WEB

    update_methode = app_config.yt_config.methode_update_upload
    if update_methode == "API":
        uploads_handler = YT_Uploads_Handler_API

    elif update_methode != "WEB":
        print(
            f"config 'yt_config.methode_update_upload' has invalid value '{update_methode}'")

    channel_Uploads, errors = uploads_handler.get_channel_uploads(
        channel=channel)

    # TODO
    # if errors
    #     fail-over to different handler

    # print(f"done channel: {channel.name}")

    return channel_Uploads


def check_video_type(uploads: list[Upload]):
    update_methode = app_config.yt_config.methode_check_video_type

    uploads_handler: YT_Uploads_Handler_Base = YT_Uploads_Handler_WEB

    if update_methode == "API":
        # uploads_handler = YT_Uploads_Handler_API
        uploads_handler = None

    elif update_methode != "WEB":
        print(
            f"config 'yt_config.methode_check_video_type' has invalid value '{update_methode}'")

    channel_Uploads = uploads_handler.check_videos_type(
        uploads=uploads)

    return channel_Uploads

####################################################################################################
####################################################################################################


async def _update_channel(channel: Channel, executor):
    loop = asyncio.get_event_loop()
    channel_uploads = await loop.run_in_executor(executor, update_channel, channel)

    return channel_uploads


async def _load_channel_uploads() -> tuple[list[Upload], int]:
    channels = Channel.get_all()#[:300]

    with ThreadPoolExecutor() as executor:
        tasks = [
            _update_channel(channel, executor) for channel in channels
        ]

        new_uploads: list[list[Upload]] = await asyncio.gather(*tasks)

    all_uploads: list[Upload] = []

    for channel_uploads in new_uploads:
        all_uploads.extend(channel_uploads)

    # remove Uploads that already exist
    # this is done here as in the sub-threads the app_context is missing.
    # The app_context is needed for DB interactions (check if exists)
    all_uploads = [upload for upload in all_uploads if not upload.exists()]

    return all_uploads, len(channels)

####################################################################################################


async def _check_video_type_groups(upload_group: list[Upload], executor):
    loop = asyncio.get_event_loop()
    uploads = await loop.run_in_executor(executor, check_video_type, upload_group)

    return uploads


async def _check_video_type(uploads: list[Upload]):
    check_methode = app_config.yt_config.methode_check_video_type
    max_group_size = 50 if check_methode == "API" else 10

    uploads_groups = [uploads[i:i + max_group_size]
                      for i in range(0, len(uploads), max_group_size)]

    with ThreadPoolExecutor() as executor:
        tasks = [
            _check_video_type_groups(upload_group, executor) for upload_group in uploads_groups
        ]

        new_uploads: list[list[Upload]] = await asyncio.gather(*tasks)

    all_uploads = []
    for channel_uploads in new_uploads:
        all_uploads.extend(channel_uploads)

    return all_uploads


####################################################################################################
def _print_debug_info(num_channels, new_uploads: list[Upload], start_all, end_load, end_all):

    time_load = end_load - start_all
    time_type = end_all - end_load
    time_taken = end_all - start_all

    print()
    print()
    print(f"{num_channels} Channels have been updated")
    print()

    headers = ["action", "time abs.", "avg. per C"]
    data = [
        ["load", time_load, time_load/num_channels],
        ["type", time_type, time_type/num_channels],
        ["total", time_taken, time_taken/num_channels]
    ]

    # Round the last two fields of each row to three decimal places
    for row in data:
        row[-2] = round(row[-2], 3)
        row[-1] = round(row[-1], 3)

    max_widths = [max(len(str(item)) for item in column)
                  for column in zip(headers, *data)]

    # Print the table headers
    print(" | ".join(f"{header:{width}}" for header,
          width in zip(headers, max_widths)))

    # Print separator line
    print("-" * (sum(max_widths) + len(headers) * 3 - 2))

    # Print the data rows
    for row in data:
        print(" | ".join(f"{item:{width}}" for item,
              width in zip(row, max_widths)))

    print()
    print(f"Loaded {len(new_uploads)} new uploads")
    print(f"Normal \t -{len([upload for upload in new_uploads if not upload.is_short])}")
    # print(f"Normal \t -{len([upload for upload in new_uploads if not upload.is_short and not upload.is_livestream])}")
    print(f"Shorts \t -{len([upload for upload in new_uploads if upload.is_short])}")
    # print(f"Live   \t -{len([upload for upload in new_uploads if upload.is_livestream])}")
    print()


def update_all_channels():
    print()
    print("DEBUG updating uploads...")

    start_all = time.time()

    new_uploads, num_channels = asyncio.run(_load_channel_uploads())

    end_load = time.time()

    if app_config.yt_config._check_video_type_:
        # new_uploads = asyncio.run(_check_video_type(new_uploads))
        asyncio.run(_check_video_type(new_uploads))

    end_all = time.time()

    db.session.add_all(new_uploads)
    # db.session.rollback()
    db.session.commit()

    _print_debug_info(num_channels, new_uploads,
                      start_all, end_load, end_all)

    return len(new_uploads)