import { useState, useEffect } from 'react';
import { useFeed, Upload, FeedResponse } from '../api/feed';
import { useTags } from '../api/tags';
import UploadCard from '../components/UploadCard';
import '../styles/feed.css';

export default function FeedPage() {
  const [tagFilter, setTagFilter] = useState<number | undefined>();
  const [cursor, setCursor] = useState<string | null | undefined>();
  const [allItems, setAllItems] = useState<Upload[]>([]);
  const [hasLoadedInitial, setHasLoadedInitial] = useState(false);

  const { data: tagsData } = useTags();
  const { data: feedData, isLoading } = useFeed({
    tag_id: tagFilter,
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

  const handleTagChange = (id: number | undefined) => {
    setTagFilter(id);
    setCursor(undefined);
    setAllItems([]);
    setHasLoadedInitial(false);
  };

  return (
    <div className="feed-page">
      <h1>Feed</h1>

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
