import { useState, useEffect } from 'react';
import { useFeed, Upload, FeedResponse, VideoType } from '../api/feed';
import { useTags } from '../api/tags';
import UploadCard from '../components/UploadCard';
import '../styles/feed.css';

const VIDEO_TYPE_FILTERS: { value: VideoType | undefined; label: string }[] = [
  { value: undefined, label: 'All types' },
  { value: 'video', label: 'Videos' },
  { value: 'short', label: 'Shorts' },
  { value: 'live', label: 'Live' },
];

export default function FeedPage() {
  const [tagFilter, setTagFilter] = useState<number | undefined>();
  const [videoTypeFilter, setVideoTypeFilter] = useState<VideoType | undefined>();
  const [cursor, setCursor] = useState<string | null | undefined>();
  const [allItems, setAllItems] = useState<Upload[]>([]);
  const [hasLoadedInitial, setHasLoadedInitial] = useState(false);

  const { data: tagsData } = useTags();
  const { data: feedData, isLoading } = useFeed({
    tag_id: tagFilter,
    video_type: videoTypeFilter,
    cursor: cursor || undefined,
  });

  const feed = feedData as FeedResponse | undefined;

  // Load initial items
  useEffect(() => {
    if (feed && !hasLoadedInitial && !cursor) {
      setAllItems(feed.items);
      setHasLoadedInitial(true);
    }
  }, [feed, hasLoadedInitial, cursor]);

  // Append new items when cursor changes
  useEffect(() => {
    if (feed && cursor && hasLoadedInitial) {
      setAllItems((prev) => [...prev, ...feed.items]);
    }
  }, [feed, cursor, hasLoadedInitial]);

  const handleLoadMore = () => {
    if (feed?.next_cursor) {
      setCursor(feed.next_cursor);
    }
  };

  const resetPaging = () => {
    setCursor(undefined);
    setAllItems([]);
    setHasLoadedInitial(false);
  };

  const handleTagChange = (id: number | undefined) => {
    setTagFilter(id);
    resetPaging();
  };

  const handleVideoTypeChange = (type: VideoType | undefined) => {
    setVideoTypeFilter(type);
    resetPaging();
  };

  return (
    <div className="feed-page">
      <div className="feed-header">
        <h1>Feed</h1>
        {feed && <p className="total-uploads">{feed.total_uploads.toLocaleString()} uploads total</p>}
      </div>

      <div className="tag-filter">
        <button
          className={`tag-chip ${!tagFilter ? 'active' : ''}`}
          onClick={() => handleTagChange(undefined)}
        >
          All
        </button>
        {tagsData?.map((tag) => (
          <button
            key={tag.id}
            className={`tag-chip ${tagFilter === tag.id ? 'active' : ''}`}
            onClick={() => handleTagChange(tag.id)}
            style={tagFilter === tag.id ? { backgroundColor: tag.color, color: '#fff' } : { borderColor: tag.color }}
          >
            {tag.name}
          </button>
        ))}
      </div>

      <div className="video-type-filter">
        {VIDEO_TYPE_FILTERS.map((opt) => (
          <button
            key={opt.label}
            className={`type-chip ${videoTypeFilter === opt.value ? 'active' : ''}`}
            onClick={() => handleVideoTypeChange(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>

      <div className="upload-grid">
        {allItems.length === 0 && !isLoading ? (
          <p>No uploads found</p>
        ) : (
          allItems.map((upload) => <UploadCard key={upload.id} upload={upload} />)
        )}
      </div>

      {feed?.next_cursor && (
        <div className="load-more-container">
          <button onClick={handleLoadMore} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Load More'}
          </button>
        </div>
      )}
    </div>
  );
}
