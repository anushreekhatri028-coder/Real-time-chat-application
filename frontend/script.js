/**
 * NexusChat - Client Logic
 * Handles WebSocket communication, UI updates, sound synthesis, and real-time state.
 */

// ==============================================================================
// Configuration
// ==============================================================================

const API_BASE_URL = 'http://localhost:5000';

// The login page shown when using VS Code Live Server.
// Change to '/login' if your frontend is served by Flask instead.
const LOGIN_PAGE = 'index.html';

function apiFetch(path, options = {}) {
  const url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;

  return fetch(url, {
    ...options,
    credentials: 'include'
  });
}

// ==============================================================================
// State Variables
// ==============================================================================

let socket = null;
let currentUser = null;
let currentRoom = null;
let channels = [];
let allUsers = [];
let activeMessages = [];
let typingTimeout = null;
let isTyping = false;
let pendingAttachment = null;
let soundEnabled = true;
let selectedIcon = '💬';

const EMOJI_LIST = [
  '😀', '😂', '😍', '🥳', '😎', '🤔', '🙌',
  '👍', '👎', '❤️', '🔥', '🚀', '🎉', '✨',
  '💡', '💻', '⚡', '☕', '💯', '🤖', '🔒',
  '👋', '👀', '🎯', '🎈', '⭐', '🌈', '🍕'
];

// ==============================================================================
// Audio Notifications
// ==============================================================================

let audioCtx = null;

function getAudioContext() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }

  if (audioCtx.state === 'suspended') {
    audioCtx.resume();
  }

  return audioCtx;
}

function playSendSound() {
  if (!soundEnabled) return;

  try {
    const ctx = getAudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();

    osc.type = 'sine';
    osc.frequency.setValueAtTime(380, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(
      750,
      ctx.currentTime + 0.08
    );

    gain.gain.setValueAtTime(0.06, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(
      0.001,
      ctx.currentTime + 0.08
    );

    osc.connect(gain);
    gain.connect(ctx.destination);

    osc.start();
    osc.stop(ctx.currentTime + 0.09);
  } catch (error) {
    console.warn('Send sound unavailable:', error);
  }
}

function playReceiveSound() {
  if (!soundEnabled) return;

  try {
    const ctx = getAudioContext();
    const now = ctx.currentTime;

    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const gain = ctx.createGain();

    osc1.type = 'sine';
    osc2.type = 'sine';

    osc1.frequency.setValueAtTime(587.33, now);
    osc2.frequency.setValueAtTime(880, now + 0.08);

    gain.gain.setValueAtTime(0.08, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(ctx.destination);

    osc1.start(now);
    osc1.stop(now + 0.08);

    osc2.start(now + 0.08);
    osc2.stop(now + 0.25);
  } catch (error) {
    console.warn('Receive sound unavailable:', error);
  }
}

// ==============================================================================
// Initialization
// ==============================================================================

document.addEventListener('DOMContentLoaded', async () => {
  initEmojiGrid();
  initScrollListener();

  await checkAuthAndInitialize();
});

async function checkAuthAndInitialize() {
  try {
    const res = await apiFetch('/api/auth/me');

    if (!res.ok) {
      window.location.href = LOGIN_PAGE;
      return;
    }

    const data = await res.json();

    if (data.success === false || !data.user) {
      window.location.href = LOGIN_PAGE;
      return;
    }

    currentUser = data.user;

    renderCurrentUserProfile();
    initSocketConnection();

    await loadChannels();
    await loadUsers();

    const generalChannel =
      channels.find(channel => channel.name === 'general') ||
      channels[0];

    if (generalChannel) {
      await selectChannel(generalChannel.id);
    }
  } catch (error) {
    console.error('Initialization error:', error);
    showToast(
      'Unable to connect to the backend. Check that Flask is running on port 5000.',
      'error'
    );
  }
}

function renderCurrentUserProfile() {
  if (!currentUser) return;

  const avatar = document.getElementById('footer-user-avatar');
  const name = document.getElementById('footer-user-name');
  const statusText = document.getElementById('footer-user-status-text');
  const indicator = document.getElementById('footer-user-status-indicator');

  if (avatar) {
    avatar.textContent =
      (currentUser.display_name || currentUser.username || '?')[0].toUpperCase();

    avatar.style.backgroundColor =
      currentUser.avatar_color || '#6366f1';
  }

  if (name) {
    name.textContent =
      currentUser.display_name || currentUser.username || 'User';
  }

  if (statusText) {
    statusText.textContent = currentUser.status || 'Online';
  }

  if (indicator) {
    indicator.className =
      `status-indicator status-${currentUser.status || 'online'}`;
  }
}

// ==============================================================================
// Socket.IO Connection
// ==============================================================================

function initSocketConnection() {
  if (typeof io !== 'function') {
    console.error(
      'Socket.IO client library is missing. Check the Socket.IO script in chat.html.'
    );

    showToast('Socket.IO library is not loaded.', 'error');
    return;
  }

  if (socket) {
    socket.disconnect();
  }

  socket = io(API_BASE_URL, {
    withCredentials: true,
    auth: {
      user_id: currentUser.id
    }
  });

  socket.on('connect', () => {
    console.log('Socket.IO connected:', socket.id);
    updateConnectionStatus(true);
  });

  socket.on('connect_error', error => {
    console.error('Socket.IO connection error:', error.message);
    updateConnectionStatus(false);
  });

  socket.on('disconnect', reason => {
    console.warn('Socket.IO disconnected:', reason);
    updateConnectionStatus(false);
  });

  socket.on('new_message', msg => {
    handleIncomingMessage(msg);
  });

  socket.on('user_typing', data => {
    if (
      currentRoom &&
      String(data.room_id) === String(currentRoom.id) &&
      String(data.user_id) !== String(currentUser.id)
    ) {
      showTypingIndicator(data.display_name || data.username || 'Someone');
    }
  });

  socket.on('user_stop_typing', data => {
    if (
      currentRoom &&
      String(data.room_id) === String(currentRoom.id)
    ) {
      hideTypingIndicator();
    }
  });

  // Support the alternate event name if your backend emits it.
  socket.on('display_typing', data => {
    if (
      !currentRoom ||
      String(data.room_id) !== String(currentRoom.id)
    ) {
      return;
    }

    if (data.is_typing) {
      showTypingIndicator(data.display_name || data.username || 'Someone');
    } else {
      hideTypingIndicator();
    }
  });

  socket.on('reaction_updated', data => {
    handleReactionUpdate(data);
  });

  socket.on('user_status_change', data => {
    handleUserStatusChange(data);
  });

  socket.on('new_channel_created', room => {
    if (!channels.some(channel => String(channel.id) === String(room.id))) {
      channels.push(room);
      renderChannelList();
    }
  });
}

function updateConnectionStatus(isOnline) {
  const text = document.getElementById('connection-text');
  const pill = document.getElementById('connection-pill');

  if (text) {
    text.textContent = isOnline ? 'Live' : 'Connecting...';
  }

  if (pill) {
    pill.style.color = isOnline
      ? 'var(--status-online)'
      : 'var(--status-away)';

    pill.style.background = isOnline
      ? 'rgba(16, 185, 129, 0.12)'
      : 'rgba(245, 158, 11, 0.12)';
  }
}

// ==============================================================================
// Channels
// ==============================================================================

async function loadChannels() {
  try {
    const res = await apiFetch('/api/rooms');
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || `Request failed: ${res.status}`);
    }

    if (data.success) {
      channels = data.rooms || [];
      renderChannelList();
    }
  } catch (error) {
    console.error('Failed to load channels:', error);
    showToast('Could not load channels.', 'error');
  }
}

function renderChannelList() {
  const container = document.getElementById('channel-list');
  if (!container) return;

  container.innerHTML = '';

  channels.forEach(channel => {
    const isActive =
      currentRoom &&
      String(currentRoom.id) === String(channel.id);

    const item = document.createElement('div');
    item.className = `channel-item ${isActive ? 'active' : ''}`;
    item.onclick = () => selectChannel(channel.id);

    item.innerHTML = `
      <span class="channel-icon">${escapeHtml(channel.icon || '#')}</span>
      <span class="channel-name">${escapeHtml(channel.name)}</span>
      <span class="unread-badge"
            id="unread-room-${channel.id}"
            style="display:none;">0</span>
    `;

    container.appendChild(item);
  });
}

// ==============================================================================
// Users and Direct Messages
// ==============================================================================

async function loadUsers() {
  try {
    const res = await apiFetch('/api/users');
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.error || `Request failed: ${res.status}`);
    }

    if (data.success) {
      allUsers = (data.users || []).filter(
        user => String(user.id) !== String(currentUser.id)
      );

      renderDMList();
      renderMembersPanel();
    }
  } catch (error) {
    console.error('Failed to load users:', error);
    showToast('Could not load users.', 'error');
  }
}

function renderDMList() {
  const container = document.getElementById('dm-list');
  if (!container) return;

  container.innerHTML = '';

  allUsers.forEach(user => {
    const isActive =
      currentRoom &&
      currentRoom.is_private &&
      (
        String(currentRoom.dm_user1_id) === String(user.id) ||
        String(currentRoom.dm_user2_id) === String(user.id)
      );

    const item = document.createElement('div');
    item.className = `dm-item ${isActive ? 'active' : ''}`;
    item.onclick = () => selectDirectMessage(user.id);

    const initial =
      (user.display_name || user.username || '?')[0].toUpperCase();

    item.innerHTML = `
      <div class="avatar-wrapper">
        <div class="user-avatar"
             style="width:26px;height:26px;font-size:11px;
                    background-color:${safeColor(user.avatar_color)};">
          ${escapeHtml(initial)}
        </div>

        <span class="status-indicator status-${safeStatus(user.status)}"
              id="dm-status-${user.id}"
              style="width:8px;height:8px;bottom:-1px;right:-1px;">
        </span>
      </div>

      <span class="dm-name">
        ${escapeHtml(user.display_name || user.username)}
      </span>

      <span class="unread-badge"
            id="unread-dm-${user.id}"
            style="display:none;">0</span>
    `;

    container.appendChild(item);
  });
}

function renderMembersPanel() {
  const onlineContainer =
    document.getElementById('online-members-list');

  const offlineContainer =
    document.getElementById('offline-members-list');

  if (!onlineContainer || !offlineContainer || !currentUser) return;

  onlineContainer.innerHTML = '';
  offlineContainer.innerHTML = '';

  const onlineUsers = allUsers.filter(user => user.status === 'online');
  const offlineUsers = allUsers.filter(user => user.status !== 'online');

  const onlineCount = document.getElementById('online-count');
  const offlineCount = document.getElementById('offline-count');

  if (onlineCount) {
    onlineCount.textContent =
      onlineUsers.length + (currentUser.status === 'offline' ? 0 : 1);
  }

  if (offlineCount) {
    offlineCount.textContent =
      offlineUsers.length + (currentUser.status === 'offline' ? 1 : 0);
  }

  if (currentUser.status === 'offline') {
    offlineContainer.appendChild(createMemberItem(currentUser, true));
  } else {
    onlineContainer.appendChild(createMemberItem(currentUser, true));
  }

  onlineUsers.forEach(user => {
    onlineContainer.appendChild(createMemberItem(user));
  });

  offlineUsers.forEach(user => {
    offlineContainer.appendChild(createMemberItem(user));
  });
}

function createMemberItem(user, isSelf = false) {
  const div = document.createElement('div');
  div.className = 'member-item';

  div.onclick = () => {
    if (!isSelf) {
      selectDirectMessage(user.id);
    }
  };

  const initial =
    (user.display_name || user.username || '?')[0].toUpperCase();

  const isBot = user.username === 'nova_bot';

  div.innerHTML = `
    <div class="avatar-wrapper">
      <div class="user-avatar"
           style="background-color:${safeColor(user.avatar_color)};">
        ${escapeHtml(initial)}
      </div>
      <span class="status-indicator status-${safeStatus(user.status)}"></span>
    </div>

    <div class="member-info">
      <div style="display:flex;align-items:center;gap:6px;">
        <span class="member-name">
          ${escapeHtml(user.display_name || user.username)}
        </span>

        ${isBot ? '<span class="bot-tag">BOT</span>' : ''}
        ${isSelf ? '<span style="font-size:10px;color:var(--text-muted);">(you)</span>' : ''}
      </div>

      <span class="member-bio">
        ${escapeHtml(user.bio || `@${user.username}`)}
      </span>
    </div>
  `;

  return div;
}

// ==============================================================================
// Switching Channels and Direct Messages
// ==============================================================================

async function selectChannel(roomId) {
  if (
    currentRoom &&
    String(currentRoom.id) === String(roomId)
  ) {
    return;
  }

  if (!socket || !socket.connected) {
    showToast('Connecting to chat server. Please try again.', 'error');
  }

  if (currentRoom && socket) {
    socket.emit('leave_room', { room_id: currentRoom.id });
  }

  const unreadEl = document.getElementById(`unread-room-${roomId}`);
  if (unreadEl) unreadEl.style.display = 'none';

  try {
    const res = await apiFetch(`/api/messages/${encodeURIComponent(roomId)}`);
    const data = await res.json();

    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Could not load channel messages.');
    }

    currentRoom = data.room;
    activeMessages = data.messages || [];

    if (socket) {
      socket.emit('join_room', { room_id: roomId });
    }

    updateRoomHeader();
    renderChannelList();
    renderDMList();
    renderMessagesFeed();
    scrollToBottom(false);

    const textarea = document.getElementById('chat-textarea');
    if (textarea) {
      textarea.placeholder = `Message #${currentRoom.name}...`;
      textarea.focus();
    }
  } catch (error) {
    console.error('Failed to join channel:', error);
    showToast(error.message || 'Failed to join channel.', 'error');
  }
}

async function selectDirectMessage(targetUserId) {
  if (currentRoom && socket) {
    socket.emit('leave_room', { room_id: currentRoom.id });
  }

  const unreadEl = document.getElementById(`unread-dm-${targetUserId}`);
  if (unreadEl) unreadEl.style.display = 'none';

  try {
    const res = await apiFetch(
      `/api/dm/${encodeURIComponent(targetUserId)}`
    );

    const data = await res.json();

    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Could not open direct message.');
    }

    currentRoom = data.room;
    activeMessages = data.messages || [];

    if (socket) {
      socket.emit('join_room', { room_id: currentRoom.id });
    }

    updateRoomHeader();
    renderChannelList();
    renderDMList();
    renderMessagesFeed();
    scrollToBottom(false);

    const textarea = document.getElementById('chat-textarea');

    if (textarea) {
      textarea.placeholder =
        `Message @${currentRoom.display_name || currentRoom.name}...`;

      textarea.focus();
    }
  } catch (error) {
    console.error('Failed to open DM:', error);
    showToast(error.message || 'Failed to open direct message.', 'error');
  }
}

function updateRoomHeader() {
  if (!currentRoom) return;

  const isDM = !!currentRoom.is_private;
  const icon = isDM ? '🔒' : (currentRoom.icon || '#');

  const name = isDM
    ? (currentRoom.display_name || currentRoom.name)
    : currentRoom.name;

  const desc = isDM
    ? 'Private direct message conversation.'
    : (currentRoom.description || '');

  setText('room-header-icon', icon);
  setText('room-header-name', name);
  setText('room-header-desc', desc);

  setText(
    'hero-room-icon',
    icon
  );

  setText(
    'hero-room-name',
    isDM ? `Direct Message with ${name}` : `Welcome to #${name}!`
  );

  setText(
    'hero-room-desc',
    isDM
      ? `This is the beginning of your direct message history with ${name}.`
      : (currentRoom.description || 'Welcome to the channel!')
  );

  setText('panel-room-name', `${icon} ${name}`);
  setText('panel-room-desc', desc);
}

// ==============================================================================
// Rendering Messages
// ==============================================================================

function renderMessagesFeed() {
  const feed = document.getElementById('messages-feed');
  if (!feed) return;

  feed.innerHTML = '';

  activeMessages.forEach(message => {
    feed.appendChild(createMessageElement(message));
  });
}

function createMessageElement(msg) {
  const row = document.createElement('div');
  row.className = 'message-row';
  row.id = `msg-${msg.id}`;

  const initial =
    (msg.display_name || msg.username || '?')[0].toUpperCase();

  const timeFormatted = formatMessageTime(msg.timestamp);

  const isBot =
    msg.username === 'nova_bot' ||
    msg.message_type === 'bot';

  const formattedBody = parseMarkdown(msg.content);

  let fileHtml = '';

  if (msg.file_url) {
    const safeFileUrl = escapeAttribute(msg.file_url);
    const isImage = /\.(png|jpe?g|gif|webp)$/i.test(
      msg.file_url.split('?')[0]
    );

    if (isImage) {
      fileHtml = `
        <div class="message-image-attachment"
             onclick="window.open('${safeFileUrl}', '_blank', 'noopener,noreferrer')">
          <img src="${safeFileUrl}" alt="Attachment" loading="lazy">
        </div>
      `;
    } else {
      fileHtml = `
        <div style="margin-top:8px;">
          <a href="${safeFileUrl}"
             target="_blank"
             rel="noopener noreferrer"
             style="display:inline-flex;align-items:center;gap:6px;
                    background:var(--bg-card);padding:6px 12px;
                    border-radius:6px;border:1px solid var(--border-subtle);
                    color:var(--text-highlight);">
            <span>📎 Download Attachment</span>
          </a>
        </div>
      `;
    }
  }

  const reactionsHtml = renderReactionsHtml(
    msg.id,
    msg.reactions || []
  );

  row.innerHTML = `
    <div class="message-avatar-col">
      <div class="msg-avatar"
           style="background-color:${safeColor(msg.avatar_color)};">
        ${escapeHtml(initial)}
      </div>
    </div>

    <div class="message-content-col">
      <div class="message-meta">
        <span class="message-sender"
              onclick="openUserProfile('${escapeAttribute(String(msg.sender_id))}')">
          ${escapeHtml(msg.display_name || msg.username)}
        </span>

        ${isBot ? '<span class="bot-tag">BOT</span>' : ''}

        <span class="message-time">
          ${escapeHtml(timeFormatted)}
        </span>
      </div>

      <div class="message-body">${formattedBody}</div>

      ${fileHtml}

      <div class="reactions-row" id="reactions-for-${msg.id}">
        ${reactionsHtml}
      </div>
    </div>

    <div class="message-actions-bar">
      <button class="quick-react-btn"
              onclick="sendReaction(${Number(msg.id)}, '👍')">👍</button>
      <button class="quick-react-btn"
              onclick="sendReaction(${Number(msg.id)}, '❤️')">❤️</button>
      <button class="quick-react-btn"
              onclick="sendReaction(${Number(msg.id)}, '😂')">😂</button>
      <button class="quick-react-btn"
              onclick="sendReaction(${Number(msg.id)}, '🔥')">🔥</button>
      <button class="quick-react-btn"
              onclick="sendReaction(${Number(msg.id)}, '🚀')">🚀</button>
      <button class="quick-react-btn"
              onclick="copyMessageText('${escapeAttribute(msg.content || '')}')"
              title="Copy Text">📋</button>
    </div>
  `;

  return row;
}

function renderReactionsHtml(messageId, reactions) {
  if (!Array.isArray(reactions) || reactions.length === 0) {
    return '';
  }

  return reactions.map(reaction => {
    const users = reaction.users || [];

    const userReacted = users.some(
      user => String(user.id) === String(currentUser.id)
    );

    const userNames = users
      .map(user => user.display_name || user.username)
      .join(', ');

    return `
      <div class="reaction-chip ${userReacted ? 'reacted' : ''}"
           onclick="sendReaction(${Number(messageId)}, '${escapeAttribute(reaction.emoji)}')"
           title="${escapeAttribute(userNames)}">
        <span class="emoji-icon">${escapeHtml(reaction.emoji)}</span>
        <span class="reaction-count">${Number(reaction.count) || 0}</span>
      </div>
    `;
  }).join('');
}

function handleReactionUpdate(data) {
  const container = document.getElementById(
    `reactions-for-${data.message_id}`
  );

  if (container) {
    container.innerHTML = renderReactionsHtml(
      data.message_id,
      data.reactions || []
    );
  }
}

function sendReaction(messageId, emoji) {
  if (!socket || !currentRoom) return;

  socket.emit('reaction', {
    message_id: messageId,
    room_id: currentRoom.id,
    emoji
  });
}

// ==============================================================================
// Markdown and HTML Escaping
// ==============================================================================

function parseMarkdown(text) {
  if (!text) return '';

  let str = escapeHtml(text);

  str = str.replace(
    /```([\s\S]*?)```/g,
    '<pre><code>$1</code></pre>'
  );

  str = str.replace(
    /`([^`]+)`/g,
    '<code>$1</code>'
  );

  str = str.replace(
    /\*\*([^*]+)\*\*/g,
    '<strong>$1</strong>'
  );

  str = str.replace(
    /\*([^*]+)\*/g,
    '<em>$1</em>'
  );

  str = str.replace(/\n/g, '<br>');

  str = str.replace(
    /(https?:\/\/[^\s<]+)/g,
    '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  return str;
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';

  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };

  return String(text).replace(/[&<>"']/g, char => map[char]);
}

function escapeAttribute(text) {
  if (text === null || text === undefined) return '';

  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/'/g, '&#039;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function formatMessageTime(isoString) {
  if (!isoString) return '';

  let normalized = String(isoString).replace(' ', 'T');

  if (!normalized.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(normalized)) {
    normalized += 'Z';
  }

  const date = new Date(normalized);

  if (Number.isNaN(date.getTime())) {
    return String(isoString);
  }

  const hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  const displayHours = hours % 12 || 12;

  return `Today at ${displayHours}:${minutes} ${ampm}`;
}

// ==============================================================================
// Sending Messages and Typing Indicators
// ==============================================================================

function handleKeyDown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
}

function handleTypingInput(event) {
  const textarea = event.target;

  textarea.style.height = 'auto';
  textarea.style.height =
    Math.min(textarea.scrollHeight, 140) + 'px';

  if (!socket || !currentRoom) return;

  if (!isTyping) {
    isTyping = true;

    socket.emit('typing', {
      room_id: currentRoom.id
    });
  }

  clearTimeout(typingTimeout);

  typingTimeout = setTimeout(() => {
    isTyping = false;

    if (socket && currentRoom) {
      socket.emit('stop_typing', {
        room_id: currentRoom.id
      });
    }
  }, 1600);
}

async function sendMessage() {
  const textarea = document.getElementById('chat-textarea');
  if (!textarea) return;

  const content = textarea.value.trim();

  if (!content && !pendingAttachment) return;

  if (!currentRoom || !socket || !socket.connected) {
    showToast('Chat server is not connected yet.', 'error');
    return;
  }

  const payload = {
    room_id: currentRoom.id,
    content,
    message_type: 'text',
    file_url: pendingAttachment
      ? pendingAttachment.file_url
      : null
  };

  socket.emit('send_message', payload);

  clearTimeout(typingTimeout);
  isTyping = false;

  socket.emit('stop_typing', {
    room_id: currentRoom.id
  });

  textarea.value = '';
  textarea.style.height = 'auto';

  removePendingAttachment();
  playSendSound();
}

function handleIncomingMessage(msg) {
  if (
    currentRoom &&
    String(msg.room_id) === String(currentRoom.id)
  ) {
    activeMessages.push(msg);

    const feed = document.getElementById('messages-feed');

    if (feed) {
      feed.appendChild(createMessageElement(msg));
    }

    if (String(msg.sender_id) !== String(currentUser.id)) {
      playReceiveSound();
    }

    const container = document.getElementById('messages-container');

    if (container) {
      const isNearBottom =
        container.scrollHeight -
        container.scrollTop -
        container.clientHeight < 160;

      if (
        isNearBottom ||
        String(msg.sender_id) === String(currentUser.id)
      ) {
        scrollToBottom(true);
      } else {
        const button = document.getElementById('scroll-bottom-btn');
        if (button) button.classList.add('active');
      }
    }
  } else {
    showUnreadBadge(msg.room_id, msg.sender_id);

    if (String(msg.sender_id) !== String(currentUser.id)) {
      playReceiveSound();
    }
  }
}

function showUnreadBadge(roomId, senderId) {
  const roomBadge = document.getElementById(`unread-room-${roomId}`);

  if (roomBadge) {
    roomBadge.style.display = 'inline-block';
    roomBadge.textContent =
      (parseInt(roomBadge.textContent || '0', 10) + 1);
  }

  const dmBadge = document.getElementById(`unread-dm-${senderId}`);

  if (dmBadge) {
    dmBadge.style.display = 'inline-block';
    dmBadge.textContent =
      (parseInt(dmBadge.textContent || '0', 10) + 1);
  }
}

function showTypingIndicator(name) {
  const indicator = document.getElementById('typing-indicator');
  const text = document.getElementById('typing-text');

  if (text) {
    text.textContent = `${name} is typing...`;
  }

  if (indicator) {
    indicator.style.visibility = 'visible';
  }
}

function hideTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');

  if (indicator) {
    indicator.style.visibility = 'hidden';
  }
}

// ==============================================================================
// User Status
// ==============================================================================

function handleUserStatusChange(data) {
  const user = allUsers.find(
    item => String(item.id) === String(data.user_id)
  );

  if (user) {
    user.status = data.status;
  }

  if (
    currentUser &&
    String(currentUser.id) === String(data.user_id)
  ) {
    currentUser.status = data.status;
    renderCurrentUserProfile();
  }

  renderDMList();
  renderMembersPanel();
}

function toggleUserStatusMenu(event) {
  if (event) event.stopPropagation();

  if (!currentUser) return;

  const statuses = ['online', 'away', 'busy'];
  const currentIndex = statuses.indexOf(
    currentUser.status || 'online'
  );

  const nextStatus = statuses[(currentIndex + 1) % statuses.length];

  currentUser.status = nextStatus;
  renderCurrentUserProfile();

  if (socket && socket.connected) {
    socket.emit('status_update', {
      status: nextStatus
    });
  }
}

// ==============================================================================
// File Uploads
// ==============================================================================

async function handleFileUpload(event) {
  const file = event.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await apiFetch('/api/upload', {
      method: 'POST',
      body: formData
    });

    const data = await res.json();

    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Upload failed.');
    }

    pendingAttachment = data;
    showAttachmentPreview(data);
  } catch (error) {
    console.error('File upload failed:', error);
    showToast(error.message || 'File upload error.', 'error');
  } finally {
    event.target.value = '';
  }
}

function showAttachmentPreview(attachment) {
  const previewBar =
    document.getElementById('attachment-preview-bar');

  const previewImg =
    document.getElementById('attachment-preview-img');

  const previewName =
    document.getElementById('attachment-preview-name');

  if (previewName) {
    previewName.textContent = attachment.filename || 'Attachment';
  }

  if (previewImg) {
    if (attachment.is_image) {
      previewImg.src = attachment.file_url;
      previewImg.style.display = 'block';
    } else {
      previewImg.style.display = 'none';
    }
  }

  if (previewBar) {
    previewBar.classList.add('active');
  }
}

function removePendingAttachment() {
  pendingAttachment = null;

  const previewBar =
    document.getElementById('attachment-preview-bar');

  if (previewBar) {
    previewBar.classList.remove('active');
  }
}

// ==============================================================================
// Emoji Picker
// ==============================================================================

function initEmojiGrid() {
  const grid = document.getElementById('emoji-grid');
  if (!grid) return;

  grid.innerHTML = '';

  EMOJI_LIST.forEach(emoji => {
    const button = document.createElement('button');

    button.type = 'button';
    button.className = 'emoji-grid-btn';
    button.textContent = emoji;

    button.onclick = event => {
      event.stopPropagation();
      insertEmoji(emoji);
    };

    grid.appendChild(button);
  });
}

function toggleEmojiPicker(event) {
  if (event) event.stopPropagation();

  const popover = document.getElementById('emoji-popover');

  if (popover) {
    popover.classList.toggle('active');
  }
}

function insertEmoji(emoji) {
  const textarea = document.getElementById('chat-textarea');
  if (!textarea) return;

  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const text = textarea.value;

  textarea.value =
    text.substring(0, start) +
    emoji +
    text.substring(end);

  textarea.selectionStart =
    textarea.selectionEnd = start + emoji.length;

  textarea.focus();

  const popover = document.getElementById('emoji-popover');

  if (popover) {
    popover.classList.remove('active');
  }
}

document.addEventListener('click', event => {
  const popover = document.getElementById('emoji-popover');
  const trigger = document.getElementById('emoji-trigger-btn');

  if (
    popover &&
    !popover.contains(event.target) &&
    !trigger?.contains(event.target)
  ) {
    popover.classList.remove('active');
  }
});

// ==============================================================================
// Search and Filter Messages
// ==============================================================================

function handleSearchMessages(query) {
  const search = query.toLowerCase().trim();
  const rows = document.querySelectorAll('.message-row');

  rows.forEach(row => {
    const body =
      row.querySelector('.message-body')?.textContent.toLowerCase() || '';

    const sender =
      row.querySelector('.message-sender')?.textContent.toLowerCase() || '';

    const matches =
      !search ||
      body.includes(search) ||
      sender.includes(search);

    row.style.display = matches ? 'flex' : 'none';
    row.style.backgroundColor =
      search && matches ? 'rgba(99, 102, 241, 0.12)' : 'transparent';
  });
}

// ==============================================================================
// Channel Creation
// ==============================================================================

function openCreateChannelModal() {
  const modal = document.getElementById('create-channel-modal');
  const input = document.getElementById('new-channel-name');

  if (modal) modal.classList.add('active');
  if (input) input.focus();
}

function closeCreateChannelModal() {
  const modal = document.getElementById('create-channel-modal');

  if (modal) {
    modal.classList.remove('active');
  }
}

function selectChannelIcon(button, icon) {
  selectedIcon = icon;

  document.querySelectorAll('.icon-option-btn').forEach(item => {
    item.classList.remove('selected');
  });

  if (button) {
    button.classList.add('selected');
  }
}

async function handleCreateChannel(event) {
  event.preventDefault();

  const name =
    document.getElementById('new-channel-name')?.value.trim() || '';

  const description =
    document.getElementById('new-channel-desc')?.value.trim() || '';

  if (!name) {
    showToast('Please enter a channel name.', 'error');
    return;
  }

  try {
    const res = await apiFetch('/api/rooms', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        name,
        description,
        icon: selectedIcon
      })
    });

    const data = await res.json();

    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Failed to create channel.');
    }

    closeCreateChannelModal();

    document.getElementById('new-channel-name').value = '';
    document.getElementById('new-channel-desc').value = '';

    if (data.room?.id) {
      if (!channels.some(channel =>
        String(channel.id) === String(data.room.id)
      )) {
        channels.push(data.room);
        renderChannelList();
      }

      await selectChannel(data.room.id);
    } else {
      await loadChannels();
    }

    showToast(`Channel #${name} created!`, 'success');
  } catch (error) {
    console.error('Channel creation failed:', error);
    showToast(error.message || 'Failed to create channel.', 'error');
  }
}

// ==============================================================================
// User Profile
// ==============================================================================

function openProfileModal() {
  if (currentUser) {
    openUserProfile(currentUser.id);
  }
}

function openUserProfile(userId) {
  if (!currentUser) return;

  const user =
    String(userId) === String(currentUser.id)
      ? currentUser
      : allUsers.find(item => String(item.id) === String(userId));

  if (!user) return;

  const avatar = document.getElementById('modal-avatar');

  if (avatar) {
    avatar.textContent =
      (user.display_name || user.username || '?')[0].toUpperCase();

    avatar.style.backgroundColor =
      safeColor(user.avatar_color);
  }

  setText('modal-display-name', user.display_name || user.username);
  setText('modal-username', `@${user.username}`);
  setText('modal-bio', user.bio || 'No status bio provided.');

  const modal = document.getElementById('user-profile-modal');

  if (modal) {
    modal.classList.add('active');
  }
}

function closeProfileModal() {
  const modal = document.getElementById('user-profile-modal');

  if (modal) {
    modal.classList.remove('active');
  }
}

// ==============================================================================
// UI Helpers
// ==============================================================================

function insertBotCommand() {
  const textarea = document.getElementById('chat-textarea');
  if (!textarea) return;

  textarea.value = '/help';
  textarea.focus();
}

async function copyMessageText(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast('Message text copied to clipboard.', 'info');
  } catch (error) {
    console.error('Clipboard error:', error);
    showToast('Could not copy message text.', 'error');
  }
}

function toggleSound() {
  soundEnabled = !soundEnabled;

  const button = document.getElementById('sound-toggle-btn');
  const icon = document.getElementById('sound-icon');

  if (button) {
    button.classList.toggle('active', soundEnabled);
  }

  if (icon) {
    icon.textContent = soundEnabled ? '🔔' : '🔕';
  }

  showToast(
    soundEnabled
      ? 'Audio notifications enabled'
      : 'Audio notifications muted',
    'info'
  );
}

function toggleRightPanel() {
  const panel = document.getElementById('right-panel');
  const button = document.getElementById('right-panel-toggle-btn');

  if (!panel) return;

  panel.classList.toggle('hidden');

  if (button) {
    button.classList.toggle(
      'active',
      !panel.classList.contains('hidden')
    );
  }
}

function toggleMobileSidebar() {
  const sidebar = document.getElementById('sidebar');

  if (sidebar) {
    sidebar.classList.toggle('open');
  }
}

function scrollToBottom(smooth = true) {
  const container = document.getElementById('messages-container');
  if (!container) return;

  container.scrollTo({
    top: container.scrollHeight,
    behavior: smooth ? 'smooth' : 'auto'
  });

  const button = document.getElementById('scroll-bottom-btn');

  if (button) {
    button.classList.remove('active');
  }
}

function initScrollListener() {
  const container = document.getElementById('messages-container');
  if (!container) return;

  container.addEventListener('scroll', () => {
    const isNearBottom =
      container.scrollHeight -
      container.scrollTop -
      container.clientHeight < 100;

    if (isNearBottom) {
      const button = document.getElementById('scroll-bottom-btn');

      if (button) {
        button.classList.remove('active');
      }
    }
  });
}

async function handleLogout() {
  try {
    const res = await apiFetch('/api/auth/logout', {
      method: 'POST'
    });

    if (!res.ok) {
      console.warn('Logout endpoint returned:', res.status);
    }
  } catch (error) {
    console.error('Logout request failed:', error);
  } finally {
    if (socket) {
      socket.disconnect();
    }

    window.location.href = LOGIN_PAGE;
  }
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');

  if (!container) {
    console.log(`[${type}] ${message}`);
    return;
  }

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';

    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// ==============================================================================
// Small Utility Functions
// ==============================================================================

function setText(elementId, value) {
  const element = document.getElementById(elementId);

  if (element) {
    element.textContent = value ?? '';
  }
}

function safeColor(value) {
  // Accept simple CSS color strings; use a fallback for missing values.
  if (
    typeof value === 'string' &&
    /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgb[a]?\([\d\s%,.]+\)|hsl[a]?\([\d\s%,.]+\))$/.test(value)
  ) {
    return value;
  }

  return '#6366f1';
}

function safeStatus(value) {
  const allowed = ['online', 'offline', 'away', 'busy'];

  return allowed.includes(value) ? value : 'offline';
}
