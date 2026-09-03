import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useChannels, useCreateChannel, useDeleteChannel, useUpdateChannel, useAckUnsubscribe, Channel } from '../api/channels';
import { useTags } from '../api/tags';
import { useToast } from '../context/ToastContext';
import { getErrorMessage } from '../utils/errors';
import ChannelRow from '../components/ChannelRow';
import AddChannelModal from '../components/AddChannelModal';
import '../styles/channels.css';

export default function ChannelsPage() {
  const [showAddModal, setShowAddModal] = useState(false);
  const { data: channelsData, isLoading } = useChannels();
  const { data: tagsData } = useTags();
  const [searchParams] = useSearchParams();
  const highlightId = searchParams.get('highlight');

  const channels = channelsData as Channel[] | undefined;
  const createChannelMutation = useCreateChannel();
  const deleteChannelMutation = useDeleteChannel();
  const updateChannelMutation = useUpdateChannel();
  const ackUnsubscribeMutation = useAckUnsubscribe();
  const { showError } = useToast();

  const handleAddChannel = async (
    channelLink: string,
    tagIds: number[],
    fetchMethod: 'api' | 'rss' | null,
  ) => {
    // Deliberately not caught here — AddChannelModal displays this error
    // inline itself (it's right next to the form the user just submitted),
    // so it re-throws rather than swallowing it silently.
    await createChannelMutation.mutateAsync({
      channel_link: channelLink,
      tag_ids: tagIds.length > 0 ? tagIds : undefined,
      upload_fetch_method: fetchMethod ?? undefined,
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

  const handleUpdateChannel = async (id: number, tagIds: number[], fetchMethod: string | null) => {
    try {
      await updateChannelMutation.mutateAsync({
        id,
        payload: {
          tag_ids: tagIds,
          upload_fetch_method: (fetchMethod === 'null' ? null : fetchMethod) as 'api' | 'rss' | null,
        },
      });
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

      {isLoading ? (
        <p>Loading...</p>
      ) : !channels || channels.length === 0 ? (
        <p>No channels yet</p>
      ) : (
        <div className="channels-grid">
          {channels.map((channel) => (
            <ChannelRow
              key={channel.id}
              channel={channel}
              allTags={tagsData || []}
              highlighted={highlightId !== null && String(channel.id) === highlightId}
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
