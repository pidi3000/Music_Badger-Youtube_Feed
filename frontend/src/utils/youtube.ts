/** Builds the real youtube.com URL for a channel, preferring its handle
 * (a nicer, human-readable URL) over the raw channel ID when available. */
export function youtubeChannelUrl(channel: { youtube_channel_id: string; handle: string | null }): string {
  if (channel.handle) {
    const handle = channel.handle.startsWith('@') ? channel.handle : `@${channel.handle}`;
    return `https://www.youtube.com/${handle}`;
  }
  return `https://www.youtube.com/channel/${channel.youtube_channel_id}`;
}
