import { useState, useEffect, useRef, Fragment } from 'react';
import { useFeed, Upload, FeedResponse, VideoType } from '../api/feed';
import { useTags } from '../api/tags';
import UploadCard from '../components/UploadCard';
import { relativeTimeInfo } from '../utils/dates';
import '../styles/feed.css';

const VIDEO_TYPE_FILTERS: { value: VideoType | undefined; label: string }[] = [
  { value: undefined, label: 'All types' },
  { value: 'video', label: 'Videos' },
  { value: 'short', label: 'Shorts' },
  { value: 'live', label: 'Live' },
];

// Past this many pixels of scroll, the sticky header switches to its
// compact spacing — small enough to kick in almost as soon as scrolling
// starts, since the header is stuck to the top from the very first pixel.
const COMPACT_SCROLL_THRESHOLD = 24;

export default function FeedPage() {
  const [tagFilter, setTagFilter] = useState<number | undefined>();
  const [videoTypeFilter, setVideoTypeFilter] = useState<VideoType | undefined>();
  const [cursor, setCursor] = useState<string | null | undefined>();
  const [allItems, setAllItems] = useState<Upload[]>([]);
  const [isCompact, setIsCompact] = useState(false);
  // Which cursor's page has already been appended into allItems — guards
  // against double-appending if that page's query refetches in the
  // background (staleTime: 0 means every window refocus does) while the
  // user is still looking at it.
  const appendedCursorRef = useRef<string | null | undefined>(undefined);

  const { data: tagsData } = useTags();
  const { data: feedData, isLoading } = useFeed({
    tag_id: tagFilter,
    video_type: videoTypeFilter,
    cursor: cursor || undefined,
  });

  const feed = feedData as FeedResponse | undefined;

  // Keep the first page in sync with every response for it, not just the
  // first one — background jobs (sync, backfill) keep adding new uploads,
  // and react-query's staleTime: 0 means a background refetch fires (and
  // can return newer data) on every mount/refocus. Gating this on "have we
  // ever loaded once" silently discarded that fresher data, which is why
  // opening the Feed page didn't always show the newest uploads.
  useEffect(() => {
    if (feed && !cursor) {
      setAllItems(feed.items);
      appendedCursorRef.current = undefined;
    }
  }, [feed, cursor]);

  // Append a later page exactly once per cursor value.
  useEffect(() => {
    if (feed && cursor && appendedCursorRef.current !== cursor) {
      setAllItems((prev) => [...prev, ...feed.items]);
      appendedCursorRef.current = cursor;
    }
  }, [feed, cursor]);

  const handleLoadMore = () => {
    if (feed?.next_cursor && !isLoading) {
      setCursor(feed.next_cursor);
    }
  };

  // Auto-load the next page once the sentinel below the grid scrolls into
  // view, instead of requiring a manual "Load More" click. rootMargin
  // triggers it a bit before it's actually on screen so the next page is
  // usually ready by the time the user reaches the bottom.
  const loadMoreRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const sentinel = loadMoreRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          handleLoadMore();
        }
      },
      { rootMargin: '400px' },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [feed?.next_cursor, isLoading]);

  // The page itself scrolls (see layout.css's note on .main-content), so
  // window scroll position is what drives the sticky header's compact
  // state — the spacing between title/tags/type-selector tightens once
  // scrolled, while all three stay pinned together at the top.
  useEffect(() => {
    const handleScroll = () => setIsCompact(window.scrollY > COMPACT_SCROLL_THRESHOLD);
    handleScroll();
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  const resetPaging = () => {
    setCursor(undefined);
    setAllItems([]);
    appendedCursorRef.current = undefined;
  };

  const handleTagChange = (id: number | undefined) => {
    setTagFilter(id);
    resetPaging();
  };

  const handleVideoTypeChange = (type: VideoType | undefined) => {
    setVideoTypeFilter(type);
    resetPaging();
  };

  const hasActiveFilters = tagFilter !== undefined || videoTypeFilter !== undefined;

  return (
    <div className="feed-page">
      <div className={`feed-sticky-header${isCompact ? ' is-compact' : ''}`}>
        <div className="feed-header">
          <h1>Feed</h1>
          {feed && (
            <p className="total-uploads">
              {feed.total_uploads.toLocaleString()} upload{feed.total_uploads === 1 ? '' : 's'}
              {hasActiveFilters ? '' : ' total'}
            </p>
          )}
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
      </div>

      <div className="upload-grid">
        {allItems.length === 0 && !isLoading ? (
          <p>No uploads found</p>
        ) : (
          (() => {
            // allItems is newest-first (see api.feed), so bucketKey only
            // ever moves from more-recent to less-recent buckets as we
            // scan down — one separator per bucket, right before its first
            // upload. Anything under 24h old has bucketKey === null and
            // never gets a separator (see relativeTimeInfo).
            let lastBucketKey: string | null | undefined;
            return allItems.map((upload) => {
              const { bucketKey, label } = relativeTimeInfo(upload.published_at);
              const showSeparator = bucketKey !== null && bucketKey !== lastBucketKey;
              lastBucketKey = bucketKey;
              return (
                <Fragment key={upload.id}>
                  {showSeparator && (
                    <div className="feed-separator">
                      <span>{label}</span>
                    </div>
                  )}
                  <UploadCard upload={upload} />
                </Fragment>
              );
            });
          })()
        )}
      </div>

      {feed?.next_cursor && (
        <div ref={loadMoreRef} className="load-more-container">
          {isLoading && <p>Loading...</p>}
        </div>
      )}
    </div>
  );
}
