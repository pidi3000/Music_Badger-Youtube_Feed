import { useEffect, useState } from 'react';
import {
  useChannels,
  useCreateChannel,
  useDeleteChannel,
  useUpdateChannel,
  useAckUnsubscribe,
  Channel,
  ChannelSort,
} from '../api/channels';
import { useTags } from '../api/tags';
import { useToast } from '../context/ToastContext';
import { getErrorMessage } from '../utils/errors';
import ChannelRow from '../components/ChannelRow';
import AddChannelModal from '../components/AddChannelModal';
import '../styles/channels.css';

const SORT_OPTIONS: { value: ChannelSort; label: string }[] = [
  { value: 'name', label: 'Name' },
  { value: 'subscribed_at', label: 'Subscribed date' },
  { value: 'latest_upload', label: 'Latest upload' },
  { value: 'upload_count', label: 'Upload count' },
];

// "tag:<id>" | "untagged" | "all" — one control for both the tag and
// untagged filters, since they're mutually exclusive.
type TagFilterValue = 'all' | 'untagged' | `tag:${number}`;

export default function ChannelsPage() {
  const [showAddModal, setShowAddModal] = useState(false);
  const [tagFilterValue, setTagFilterValue] = useState<TagFilterValue>('all');
  const [source, setSource] = useState<'manual' | 'subscription' | undefined>(undefined);
  const [sort, setSort] = useState<ChannelSort>('name');
  const [order, setOrder] = useState<'asc' | 'desc'>('asc');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');

  // Debounce so typing a channel name doesn't fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const tagId = tagFilterValue.startsWith('tag:') ? Number(tagFilterValue.slice(4)) : undefined;
  const untagged = tagFilterValue === 'untagged';

  const { data: channelsData, isLoading } = useChannels({
    tag_id: tagId,
    untagged,
    source,
    search: search || undefined,
    sort,
    order,
  });
  const { data: tagsData } = useTags();

  const channels = channelsData as Channel[] | undefined;
  const createChannelMutation = useCreateChannel();
  const deleteChannelMutation = useDeleteChannel();
  const updateChannelMutation = useUpdateChannel();
  const ackUnsubscribeMutation = useAckUnsubscribe();
  const { showError } = useToast();

  const handleAddChannel = async (channelLink: string, tagIds: number[]) => {
    // Deliberately not caught here — AddChannelModal displays this error
    // inline itself (it's right next to the form the user just submitted),
    // so it re-throws rather than swallowing it silently.
    await createChannelMutation.mutateAsync({
      channel_link: channelLink,
      tag_ids: tagIds.length > 0 ? tagIds : undefined,
    });
    setShowAddModal(false);
  };

  const handleDeleteChannel = async (id: number, title: string, uploadCount: number) => {
    const warning =
      uploadCount > 0
        ? `Delete "${title}"? This will also permanently delete all ${uploadCount} cached upload${uploadCount === 1 ? '' : 's'} for this channel. This cannot be undone.`
        : `Delete "${title}"? This cannot be undone.`;
    if (confirm(warning)) {
      try {
        await deleteChannelMutation.mutateAsync(id);
      } catch (err) {
        showError(getErrorMessage(err, 'Failed to delete channel'));
      }
    }
  };

  const handleUpdateChannel = async (id: number, tagIds: number[]) => {
    try {
      await updateChannelMutation.mutateAsync({ id, payload: { tag_ids: tagIds } });
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to update channel'));
    }
  };

  const handleAckUnsubscribe = async (id: number) => {
    try {
      await ackUnsubscribeMutation.mutateAsync(id);
    } catch (err) {
      showError(getErrorMessage(err, 'Failed to acknowledge unsubscribe'));
    }
  };

  return (
    <div className="channels-page">
      <div className="channels-header">
        <h1>Channels {channels ? <span className="channel-count">({channels.length})</span> : null}</h1>
        <button className="btn-primary" onClick={() => setShowAddModal(true)}>
          Add Channel
        </button>
      </div>

      {showAddModal && (
        <AddChannelModal onClose={() => setShowAddModal(false)} onSubmit={handleAddChannel} tags={tagsData || []} />
      )}

      <div className="channels-filter-bar">
        <input
          type="search"
          className="channels-search"
          placeholder="Search channels..."
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />

        <select value={tagFilterValue} onChange={(e) => setTagFilterValue(e.target.value as TagFilterValue)}>
          <option value="all">All tags</option>
          <option value="untagged">Untagged</option>
          {tagsData?.map((tag) => (
            <option key={tag.id} value={`tag:${tag.id}`}>
              {tag.name}
            </option>
          ))}
        </select>

        <select
          value={source ?? 'all'}
          onChange={(e) => setSource(e.target.value === 'all' ? undefined : (e.target.value as 'manual' | 'subscription'))}
        >
          <option value="all">All sources</option>
          <option value="manual">Added manually</option>
          <option value="subscription">Subscribed</option>
        </select>

        <div className="sort-control">
          <select value={sort} onChange={(e) => setSort(e.target.value as ChannelSort)}>
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                Sort: {opt.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="sort-order-btn"
            title={order === 'asc' ? 'Ascending' : 'Descending'}
            onClick={() => setOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))}
          >
            {order === 'asc' ? '↑' : '↓'}
          </button>
        </div>
      </div>

      {isLoading ? (
        <p>Loading...</p>
      ) : !channels || channels.length === 0 ? (
        <p>No channels match these filters</p>
      ) : (
        <div className="channels-grid">
          {channels.map((channel) => (
            <ChannelRow
              key={channel.id}
              channel={channel}
              allTags={tagsData || []}
              onDelete={() => handleDeleteChannel(channel.id, channel.title, channel.upload_count)}
              onUpdate={handleUpdateChannel}
              onAckUnsubscribe={handleAckUnsubscribe}
            />
          ))}
        </div>
      )}
    </div>
  );
}
