/**
 * NexusChat - Client Logic
 * Handles WebSocket communication, UI updates, sound synthesis, and real-time state.
 */

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

// Web Audio API Sound Synthesizer
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
    osc.frequency.exponentialRampToValueAtTime(750, ctx.currentTime + 0.08);
    gain.gain.setValueAtTime(0.06, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.08);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.09);
  } catch (e) {
    // Audio context may require prior user interaction
  }
}

function playReceiveSound() {
  if (!soundEnabled) return;
  try {
    const ctx = getAudioContext();
    const now = ctx.currentTime;
    // Two-tone pleasant notification chime
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const gain = ctx.createGain();

    osc1.type = 'sine';
    osc2.type = 'sine';
    osc1.frequency.setValueAtTime(587.33, now); // D5
    osc2.frequency.setValueAtTime(880.00, now + 0.08); // A5

    gain.gain.setValueAtTime(0.08, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.25);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(ctx.destination);

    osc1.start(now);
    osc1.stop(now + 0.08);
    osc2.start(now + 0.08);
    osc2.stop(now + 0.25);
  } catch (e) {
    // Ignore sound errors
  }
}

// ==============================================================================
// Initialization
// ==============================================================================
document.addEventListener('DOMContentLoaded', async () => {
  initEmojiGrid();
  await checkAuthAndInitialize();
  initScrollListener();
});

async function checkAuthAndInitialize() {
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) {
      window.location.href = '/login';
      return;
    }
    const data = await res.json();
    currentUser = data.user;

    renderCurrentUserProfile();
    initSocketConnection();
    await loadChannels();
    await loadUsers();

    // Default to general channel
    const generalChannel = channels.find(c => c.name === 'general') || channels[0];
    if (generalChannel) {
      selectChannel(generalChannel.id);
    }
  } catch (err) {
    console.error('Initialization error:', err);
    window.location.href = '/login';
  }
}

function renderCurrentUserProfile() {
  document.getElementById('footer-user-avatar').textContent = (currentUser.display_name || currentUser.username)[0].toUpperCase();
  document.getElementById('footer-user-avatar').style.backgroundColor = currentUser.avatar_color || '#6366f1';
  document.getElementById('footer-user-name').textContent = currentUser.display_name;
  document.getElementById('footer-user-status-text').textContent = currentUser.status || 'Online';

  const indicator = document.getElementById('footer-user-status-indicator');
  indicator.className = `status-indicator status-${currentUser.status || 'online'}`;
}

// ==============================================================================
// WebSocket & Socket.IO Setup
// ==============================================================================
function initSocketConnection() {
  socket = io({
    auth: { user_id: currentUser.id }
  });

  socket.on('connect', () => {
    updateConnectionStatus(true);
  });

  socket.on('disconnect', () => {
    updateConnectionStatus(false);
  });

  socket.on('new_message', (msg) => {
    handleIncomingMessage(msg);
  });

  socket.on('user_typing', (data) => {
    if (currentRoom && data.room_id === currentRoom.id && data.user_id !== currentUser.id) {
      showTypingIndicator(data.display_name || data.username);
    }
  });

  socket.on('user_stop_typing', (data) => {
    if (currentRoom && data.room_id === currentRoom.id) {
      hideTypingIndicator();
    }
  });

  socket.on('reaction_updated', (data) => {
    handleReactionUpdate(data);
  });

  socket.on('user_status_change', (data) => {
    handleUserStatusChange(data);
  });

  socket.on('new_channel_created', (room) => {
    if (!channels.some(c => c.id === room.id)) {
      channels.push(room);
      renderChannelList();
    }
  });
}

function updateConnectionStatus(isOnline) {
  const dot = document.querySelector('.connection-dot');
  const text = document.getElementById('connection-text');
  const pill = document.getElementById('connection-pill');

  if (isOnline) {
    text.textContent = 'Live';
    pill.style.color = 'var(--status-online)';
    pill.style.background = 'rgba(16, 185, 129, 0.12)';
  } else {
    text.textContent = 'Connecting...';
    pill.style.color = 'var(--status-away)';
    pill.style.background = 'rgba(245, 158, 11, 0.12)';
  }
}

// ==============================================================================
// Channels & Direct Messages
// ==============================================================================
async function loadChannels() {
  try {
    const res = await fetch('/api/rooms');
    const data = await res.json();
    if (data.success) {
      channels = data.rooms;
      renderChannelList();
    }
  } catch (e) {
    console.error('Failed to load channels', e);
  }
}

function renderChannelList() {
  const container = document.getElementById('channel-list');
  container.innerHTML = '';

  channels.forEach(ch => {
    const isActive = currentRoom && currentRoom.id === ch.id;
    const item = document.createElement('div');
    item.className = `channel-item ${isActive ? 'active' : ''}`;
    item.onclick = () => selectChannel(ch.id);

    item.innerHTML = `
      <span class="channel-icon">${ch.icon || '#'}</span>
      <span class="channel-name">${escapeHtml(ch.name)}</span>
      <span class="unread-badge" id="unread-room-${ch.id}" style="display: none;">0</span>
    `;
    container.appendChild(item);
  });
}

async function loadUsers() {
  try {
    const res = await fetch('/api/users');
    const data = await res.json();
    if (data.success) {
      allUsers = data.users.filter(u => u.id !== currentUser.id);
      renderDMList();
      renderMembersPanel();
    }
  } catch (e) {
    console.error('Failed to load users', e);
  }
}

function renderDMList() {
  const container = document.getElementById('dm-list');
  container.innerHTML = '';

  allUsers.forEach(u => {
    const isActive = currentRoom && currentRoom.is_private && (currentRoom.dm_user1_id === u.id || currentRoom.dm_user2_id === u.id);
    const item = document.createElement('div');
    item.className = `dm-item ${isActive ? 'active' : ''}`;
    item.onclick = () => selectDirectMessage(u.id);

    const initial = (u.display_name || u.username)[0].toUpperCase();
    const statusClass = `status-${u.status || 'offline'}`;

    item.innerHTML = `
      <div class="avatar-wrapper">
        <div class="user-avatar" style="width: 26px; height: 26px; font-size: 11px; background-color: ${u.avatar_color || '#6366f1'};">${initial}</div>
        <span class="status-indicator ${statusClass}" id="dm-status-${u.id}" style="width: 8px; height: 8px; bottom: -1px; right: -1px;"></span>
      </div>
      <span class="dm-name">${escapeHtml(u.display_name)}</span>
      <span class="unread-badge" id="unread-dm-${u.id}" style="display: none;">0</span>
    `;
    container.appendChild(item);
  });
}

function renderMembersPanel() {
  const onlineContainer = document.getElementById('online-members-list');
  const offlineContainer = document.getElementById('offline-members-list');
  onlineContainer.innerHTML = '';
  offlineContainer.innerHTML = '';

  const onlineUsers = allUsers.filter(u => u.status === 'online');
  const offlineUsers = allUsers.filter(u => u.status !== 'online');

  // Also include current user in online count
  document.getElementById('online-count').textContent = onlineUsers.length + 1;
  document.getElementById('offline-count').textContent = offlineUsers.length;

  // Add current user to online members
  const selfItem = createMemberItem(currentUser, true);
  onlineContainer.appendChild(selfItem);

  onlineUsers.forEach(u => {
    onlineContainer.appendChild(createMemberItem(u));
  });

  offlineUsers.forEach(u => {
    offlineContainer.appendChild(createMemberItem(u));
  });
}

function createMemberItem(user, isSelf = false) {
  const div = document.createElement('div');
  div.className = 'member-item';
  div.onclick = () => {
    if (!isSelf) selectDirectMessage(user.id);
  };

  const initial = (user.display_name || user.username)[0].toUpperCase();
  const statusClass = `status-${user.status || 'online'}`;
  const isBot = user.username === 'nova_bot';

  div.innerHTML = `
    <div class="avatar-wrapper">
      <div class="user-avatar" style="background-color: ${user.avatar_color || '#6366f1'};">${initial}</div>
      <span class="status-indicator ${statusClass}"></span>
    </div>
    <div class="member-info">
      <div style="display: flex; align-items: center; gap: 6px;">
        <span class="member-name">${escapeHtml(user.display_name)}</span>
        ${isBot ? '<span class="bot-tag">BOT</span>' : ''}
        ${isSelf ? '<span style="font-size: 10px; color: var(--text-muted);">(you)</span>' : ''}
      </div>
      <span class="member-bio">${escapeHtml(user.bio || `@${user.username}`)}</span>
    </div>
  `;
  return div;
}

// ==============================================================================
// Switching Channels & DMs
// ==============================================================================
async function selectChannel(roomId) {
  if (currentRoom && currentRoom.id === roomId) return;

  // Leave previous room in socket
  if (currentRoom) {
    socket.emit('leave_room', { room_id: currentRoom.id });
  }

  // Clear unread
  const unreadEl = document.getElementById(`unread-room-${roomId}`);
  if (unreadEl) unreadEl.style.display = 'none';

  try {
    const res = await fetch(`/api/messages/${roomId}`);
    const data = await res.json();
    if (!data.success) return;

    currentRoom = data.room;
    activeMessages = data.messages;

    // Join room in socket
    socket.emit('join_room', { room_id: roomId });

    updateRoomHeader();
    renderChannelList();
    renderDMList();
    renderMessagesFeed();
    scrollToBottom(false);

    // Focus input
    document.getElementById('chat-textarea').placeholder = `Message #${currentRoom.name}...`;
    document.getElementById('chat-textarea').focus();
  } catch (e) {
    console.error('Failed to join channel', e);
  }
}

async function selectDirectMessage(targetUserId) {
  if (currentRoom) {
    socket.emit('leave_room', { room_id: currentRoom.id });
  }

  // Clear unread
  const unreadEl = document.getElementById(`unread-dm-${targetUserId}`);
  if (unreadEl) unreadEl.style.display = 'none';

  try {
    const res = await fetch(`/api/dm/${targetUserId}`);
    const data = await res.json();
    if (!data.success) return;

    currentRoom = data.room;
    activeMessages = data.messages;

    socket.emit('join_room', { room_id: currentRoom.id });

    updateRoomHeader();
    renderChannelList();
    renderDMList();
    renderMessagesFeed();
    scrollToBottom(false);

    document.getElementById('chat-textarea').placeholder = `Message @${currentRoom.display_name}...`;
    document.getElementById('chat-textarea').focus();
  } catch (e) {
    console.error('Failed to open DM', e);
  }
}

function updateRoomHeader() {
  const isDM = !!currentRoom.is_private;
  const icon = isDM ? '🔒' : (currentRoom.icon || '#');
  const name = isDM ? (currentRoom.display_name || currentRoom.name) : currentRoom.name;
  const desc = isDM ? 'Private direct message conversation.' : (currentRoom.description || '');

  document.getElementById('room-header-icon').textContent = icon;
  document.getElementById('room-header-name').textContent = name;
  document.getElementById('room-header-desc').textContent = desc;

  // Hero Card update
  document.getElementById('hero-room-icon').textContent = icon;
  document.getElementById('hero-room-name').textContent = isDM ? `Direct Message with ${name}` : `Welcome to #${name}!`;
  document.getElementById('hero-room-desc').textContent = isDM
    ? `This is the beginning of your direct message history with ${name}.`
    : (currentRoom.description || 'Welcome to the channel!');

  // Right Panel info update
  document.getElementById('panel-room-name').textContent = `${icon} ${name}`;
  document.getElementById('panel-room-desc').textContent = desc;
}

// ==============================================================================
// Messages Rendering & Markdown Formatting
// ==============================================================================
function renderMessagesFeed() {
  const feed = document.getElementById('messages-feed');
  feed.innerHTML = '';

  activeMessages.forEach(msg => {
    feed.appendChild(createMessageElement(msg));
  });
}

function createMessageElement(msg) {
  const row = document.createElement('div');
  row.className = 'message-row';
  row.id = `msg-${msg.id}`;

  const initial = (msg.display_name || msg.username)[0].toUpperCase();
  const timeFormatted = formatMessageTime(msg.timestamp);
  const isBot = msg.username === 'nova_bot' || msg.message_type === 'bot';

  // Format content with markdown
  const formattedBody = parseMarkdown(msg.content);

  // File attachment HTML
  let fileHtml = '';
  if (msg.file_url) {
    const isImage = msg.file_url.match(/\.(png|jpe?g|gif|webp)$/i);
    if (isImage) {
      fileHtml = `
        <div class="message-image-attachment" onclick="window.open('${msg.file_url}', '_blank')">
          <img src="${msg.file_url}" alt="Attachment">
        </div>
      `;
    } else {
      fileHtml = `
        <div style="margin-top: 8px;">
          <a href="${msg.file_url}" target="_blank" style="display: inline-flex; align-items: center; gap: 6px; background: var(--bg-card); padding: 6px 12px; border-radius: 6px; border: 1px solid var(--border-subtle); color: var(--text-highlight);">
            <span>📎 Download Attachment</span>
          </a>
        </div>
      `;
    }
  }

  // Reactions HTML
  const reactionsHtml = renderReactionsHtml(msg.id, msg.reactions || []);

  row.innerHTML = `
    <div class="message-avatar-col">
      <div class="msg-avatar" style="background-color: ${msg.avatar_color || '#6366f1'};">${initial}</div>
    </div>
    <div class="message-content-col">
      <div class="message-meta">
        <span class="message-sender" onclick="openUserProfile('${msg.sender_id}')">${escapeHtml(msg.display_name || msg.username)}</span>
        ${isBot ? '<span class="bot-tag">BOT</span>' : ''}
        <span class="message-time">${timeFormatted}</span>
      </div>
      <div class="message-body">${formattedBody}</div>
      ${fileHtml}
      <div class="reactions-row" id="reactions-for-${msg.id}">${reactionsHtml}</div>
    </div>

    <!-- Quick Reaction Hover Bar -->
    <div class="message-actions-bar">
      <button class="quick-react-btn" onclick="sendReaction(${msg.id}, '👍')">👍</button>
      <button class="quick-react-btn" onclick="sendReaction(${msg.id}, '❤️')">❤️</button>
      <button class="quick-react-btn" onclick="sendReaction(${msg.id}, '😂')">😂</button>
      <button class="quick-react-btn" onclick="sendReaction(${msg.id}, '🔥')">🔥</button>
      <button class="quick-react-btn" onclick="sendReaction(${msg.id}, '🚀')">🚀</button>
      <button class="quick-react-btn" onclick="copyMessageText('${escapeAttribute(msg.content)}')" title="Copy Text">📋</button>
    </div>
  `;
  return row;
}

function renderReactionsHtml(messageId, reactions) {
  if (!reactions || reactions.length === 0) return '';
  return reactions.map(r => {
    const userReacted = r.users && r.users.some(u => u.id === currentUser.id);
    const userNames = r.users ? r.users.map(u => u.display_name).join(', ') : '';
    return `
      <div class="reaction-chip ${userReacted ? 'reacted' : ''}" onclick="sendReaction(${messageId}, '${r.emoji}')" title="${escapeHtml(userNames)}">
        <span class="emoji-icon">${r.emoji}</span>
        <span class="reaction-count">${r.count}</span>
      </div>
    `;
  }).join('');
}

function handleReactionUpdate(data) {
  const container = document.getElementById(`reactions-for-${data.message_id}`);
  if (container) {
    container.innerHTML = renderReactionsHtml(data.message_id, data.reactions);
  }
}

function sendReaction(messageId, emoji) {
  if (!socket || !currentRoom) return;
  socket.emit('reaction', {
    message_id: messageId,
    room_id: currentRoom.id,
    emoji: emoji
  });
}

// Markdown and Text Sanitizer
function parseMarkdown(text) {
  if (!text) return '';
  let str = escapeHtml(text);

  // Code blocks: ```code```
  str = str.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');

  // Inline code: `code`
  str = str.replace(/`([^`]+)`/g, '<code>$1</code>');

  // Bold: **text**
  str = str.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

  // Italic: *text*
  str = str.replace(/\*([^*]+)\*/g, '<em>$1</em>');

  // Line breaks
  str = str.replace(/\n/g, '<br>');

  // URLs
  str = str.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');

  return str;
}

function escapeHtml(text) {
  if (!text) return '';
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return text.toString().replace(/[&<>"']/g, m => map[m]);
}

function escapeAttribute(text) {
  if (!text) return '';
  return text.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function formatMessageTime(isoString) {
  if (!isoString) return '';
  // Support UTC or SQLite format
  const date = new Date(isoString.replace(' ', 'T') + (isoString.includes('Z') ? '' : 'Z'));
  if (isNaN(date.getTime())) return isoString;

  const hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  const displayHours = hours % 12 || 12;

  return `Today at ${displayHours}:${minutes} ${ampm}`;
}

// ==============================================================================
// Sending Messages & Typing Debounce
// ==============================================================================
function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function handleTypingInput(e) {
  // Auto-grow textarea
  const textarea = e.target;
  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 140) + 'px';

  if (!socket || !currentRoom) return;

  if (!isTyping) {
    isTyping = true;
    socket.emit('typing', { room_id: currentRoom.id });
  }

  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(() => {
    isTyping = false;
    socket.emit('stop_typing', { room_id: currentRoom.id });
  }, 1600);
}

async function sendMessage() {
  const textarea = document.getElementById('chat-textarea');
  const content = textarea.value.trim();

  if (!content && !pendingAttachment) return;
  if (!currentRoom || !socket) return;

  const payload = {
    room_id: currentRoom.id,
    content: content,
    message_type: 'text',
    file_url: pendingAttachment ? pendingAttachment.file_url : null
  };

  socket.emit('send_message', payload);

  // Clear typing state
  clearTimeout(typingTimeout);
  isTyping = false;
  socket.emit('stop_typing', { room_id: currentRoom.id });

  // Reset input and attachments
  textarea.value = '';
  textarea.style.height = 'auto';
  removePendingAttachment();
  playSendSound();
}

function handleIncomingMessage(msg) {
  if (currentRoom && msg.room_id === currentRoom.id) {
    activeMessages.push(msg);
    const feed = document.getElementById('messages-feed');
    const msgEl = createMessageElement(msg);
    feed.appendChild(msgEl);

    // Audio ping if not current user
    if (msg.sender_id !== currentUser.id) {
      playReceiveSound();
    }

    // Scroll to bottom if user is close to bottom, or alert
    const container = document.getElementById('messages-container');
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 160;
    if (isNearBottom || msg.sender_id === currentUser.id) {
      scrollToBottom(true);
    } else {
      document.getElementById('scroll-bottom-btn').classList.add('active');
    }
  } else {
    // Message in another room - update badge
    showUnreadBadge(msg.room_id, msg.sender_id);
    playReceiveSound();
  }
}

function showUnreadBadge(roomId, senderId) {
  const roomBadge = document.getElementById(`unread-room-${roomId}`);
  if (roomBadge) {
    roomBadge.style.display = 'inline-block';
    roomBadge.textContent = (parseInt(roomBadge.textContent || '0') + 1);
  }
  const dmBadge = document.getElementById(`unread-dm-${senderId}`);
  if (dmBadge) {
    dmBadge.style.display = 'inline-block';
    dmBadge.textContent = (parseInt(dmBadge.textContent || '0') + 1);
  }
}

// Typing Indicator Handlers
function showTypingIndicator(name) {
  const indicator = document.getElementById('typing-indicator');
  const text = document.getElementById('typing-text');
  text.textContent = `${name} is typing...`;
  indicator.style.visibility = 'visible';
}

function hideTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');
  indicator.style.visibility = 'hidden';
}

// ==============================================================================
// Real-Time Presence & Status Updates
// ==============================================================================
function handleUserStatusChange(data) {
  const user = allUsers.find(u => u.id === data.user_id);
  if (user) {
    user.status = data.status;
  }
  renderDMList();
  renderMembersPanel();
}

function toggleUserStatusMenu(e) {
  e.stopPropagation();
  const statuses = ['online', 'away', 'busy'];
  const currentIndex = statuses.indexOf(currentUser.status || 'online');
  const nextStatus = statuses[(currentIndex + 1) % statuses.length];

  currentUser.status = nextStatus;
  renderCurrentUserProfile();

  if (socket) {
    socket.emit('status_update', { status: nextStatus });
  }
}

// ==============================================================================
// File & Attachment Handling
// ==============================================================================
async function handleFileUpload(e) {
  const file = e.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (data.success) {
      pendingAttachment = data;
      showAttachmentPreview(data);
    } else {
      showToast(data.error || 'Upload failed', 'error');
    }
  } catch (err) {
    showToast('File upload error', 'error');
  } finally {
    e.target.value = '';
  }
}

function showAttachmentPreview(attachment) {
  const previewBar = document.getElementById('attachment-preview-bar');
  const previewImg = document.getElementById('attachment-preview-img');
  const previewName = document.getElementById('attachment-preview-name');

  previewName.textContent = attachment.filename;
  if (attachment.is_image) {
    previewImg.src = attachment.file_url;
    previewImg.style.display = 'block';
  } else {
    previewImg.style.display = 'none';
  }
  previewBar.classList.add('active');
}

function removePendingAttachment() {
  pendingAttachment = null;
  const previewBar = document.getElementById('attachment-preview-bar');
  previewBar.classList.remove('active');
}

// ==============================================================================
// Emoji Picker
// ==============================================================================
function initEmojiGrid() {
  const grid = document.getElementById('emoji-grid');
  grid.innerHTML = '';
  EMOJI_LIST.forEach(emoji => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'emoji-grid-btn';
    btn.textContent = emoji;
    btn.onclick = (e) => {
      e.stopPropagation();
      insertEmoji(emoji);
    };
    grid.appendChild(btn);
  });
}

function toggleEmojiPicker(e) {
  e.stopPropagation();
  const popover = document.getElementById('emoji-popover');
  popover.classList.toggle('active');
}

function insertEmoji(emoji) {
  const textarea = document.getElementById('chat-textarea');
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const text = textarea.value;

  textarea.value = text.substring(0, start) + emoji + text.substring(end);
  textarea.selectionStart = textarea.selectionEnd = start + emoji.length;
  textarea.focus();
  document.getElementById('emoji-popover').classList.remove('active');
}

// Close emoji popover on outside click
document.addEventListener('click', (e) => {
  const popover = document.getElementById('emoji-popover');
  const trigger = document.getElementById('emoji-trigger-btn');
  if (popover && !popover.contains(e.target) && e.target !== trigger) {
    popover.classList.remove('active');
  }
});

// ==============================================================================
// Search & Filter Messages
// ==============================================================================
function handleSearchMessages(query) {
  const q = query.toLowerCase().trim();
  const rows = document.querySelectorAll('.message-row');

  rows.forEach(row => {
    if (!q) {
      row.style.display = 'flex';
      return;
    }
    const text = row.querySelector('.message-body').textContent.toLowerCase();
    const sender = row.querySelector('.message-sender').textContent.toLowerCase();
    if (text.includes(q) || sender.includes(q)) {
      row.style.display = 'flex';
      row.style.backgroundColor = 'rgba(99, 102, 241, 0.12)';
    } else {
      row.style.display = 'none';
      row.style.backgroundColor = 'transparent';
    }
  });
}

// ==============================================================================
// Channel Creation Modal
// ==============================================================================
function openCreateChannelModal() {
  document.getElementById('create-channel-modal').classList.add('active');
  document.getElementById('new-channel-name').focus();
}

function closeCreateChannelModal() {
  document.getElementById('create-channel-modal').classList.remove('active');
}

function selectChannelIcon(btn, icon) {
  selectedIcon = icon;
  document.querySelectorAll('.icon-option-btn').forEach(b => b.classList.remove('selected'));
  btn.classList.add('selected');
}

async function handleCreateChannel(e) {
  e.preventDefault();
  const name = document.getElementById('new-channel-name').value.trim();
  const description = document.getElementById('new-channel-desc').value.trim();

  try {
    const res = await fetch('/api/rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description, icon: selectedIcon })
    });
    const data = await res.json();
    if (data.success) {
      closeCreateChannelModal();
      document.getElementById('new-channel-name').value = '';
      document.getElementById('new-channel-desc').value = '';
      selectChannel(data.room.id);
      showToast(`Channel #${name} created!`, 'success');
    } else {
      showToast(data.error || 'Failed to create channel', 'error');
    }
  } catch (err) {
    showToast('Failed to create channel', 'error');
  }
}

// ==============================================================================
// User Profile Modal
// ==============================================================================
function openProfileModal() {
  openUserProfile(currentUser.id);
}

function openUserProfile(userId) {
  const user = (userId == currentUser.id) ? currentUser : allUsers.find(u => u.id == userId);
  if (!user) return;

  document.getElementById('modal-avatar').textContent = (user.display_name || user.username)[0].toUpperCase();
  document.getElementById('modal-avatar').style.backgroundColor = user.avatar_color || '#6366f1';
  document.getElementById('modal-display-name').textContent = user.display_name;
  document.getElementById('modal-username').textContent = `@${user.username}`;
  document.getElementById('modal-bio').textContent = user.bio || 'No status bio provided.';

  document.getElementById('user-profile-modal').classList.add('active');
}

function closeProfileModal() {
  document.getElementById('user-profile-modal').classList.remove('active');
}

// ==============================================================================
// UI Helpers, Audio & Scroll
// ==============================================================================
function insertBotCommand() {
  const textarea = document.getElementById('chat-textarea');
  textarea.value = '/help';
  textarea.focus();
}

function copyMessageText(text) {
  navigator.clipboard.writeText(text).then(() => {
    showToast('Message text copied to clipboard', 'info');
  });
}

function toggleSound() {
  soundEnabled = !soundEnabled;
  const btn = document.getElementById('sound-toggle-btn');
  const icon = document.getElementById('sound-icon');
  if (soundEnabled) {
    btn.classList.add('active');
    icon.textContent = '🔔';
    showToast('Audio notifications enabled', 'info');
  } else {
    btn.classList.remove('active');
    icon.textContent = '🔕';
    showToast('Audio notifications muted', 'info');
  }
}

function toggleRightPanel() {
  const panel = document.getElementById('right-panel');
  const btn = document.getElementById('right-panel-toggle-btn');
  panel.classList.toggle('hidden');
  btn.classList.toggle('active', !panel.classList.contains('hidden'));
}

function toggleMobileSidebar() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.toggle('open');
}

function scrollToBottom(smooth = true) {
  const container = document.getElementById('messages-container');
  container.scrollTo({
    top: container.scrollHeight,
    behavior: smooth ? 'smooth' : 'auto'
  });
  document.getElementById('scroll-bottom-btn').classList.remove('active');
}

function initScrollListener() {
  const container = document.getElementById('messages-container');
  container.addEventListener('scroll', () => {
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
    if (isNearBottom) {
      document.getElementById('scroll-bottom-btn').classList.remove('active');
    }
  });
}

async function handleLogout() {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
    window.location.href = '/login';
  } catch (e) {
    window.location.href = '/login';
  }
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
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

// --- Feature 2: Client-side Typing Indicator Logic ---
const messageInput = document.getElementById('message-input');
let typingTimeout;

if (messageInput) {
    messageInput.addEventListener('input', () => {
        const currentUsername = localStorage.getItem('username') || 'Someone';
        const currentRoomId = window.activeRoomId || 1; // Current selected room

        // Emit typing = true event to server
        socket.emit('typing', {
            room_id: currentRoomId,
            username: currentUsername,
            is_typing: true
        });

        // Debounce: 1.5 seconds tak quiet hone par typing status off kar do
        clearTimeout(typingTimeout);
        typingTimeout = setTimeout(() => {
            socket.emit('typing', {
                room_id: currentRoomId,
                username: currentUsername,
                is_typing: false
            });
        }, 1500);
    });
}

// --- Client-side Typing Indicator Logic ---
const messageInput = document.getElementById('message-input');
let typingTimeout;

if (messageInput) {
    messageInput.addEventListener('input', () => {
        const currentUsername = localStorage.getItem('username') || 'Someone';
        const currentRoomId = window.activeRoomId || 1;

        // Emit typing event
        socket.emit('typing', {
            room_id: currentRoomId,
            username: currentUsername,
            is_typing: true
        });

        // Clear indicator after 1.5s of inactivity
        clearTimeout(typingTimeout);
        typingTimeout = setTimeout(() => {
            socket.emit('typing', {
                room_id: currentRoomId,
                username: currentUsername,
                is_typing: false
            });
        }, 1500);
    });
}

// Server se aaye typing notification ko render karna
socket.on('display_typing', (data) => {
    const typingBar = document.getElementById('typing-indicator');
    const typingText = document.getElementById('typing-text');
    
    if (typingBar && typingText) {
        if (data.is_typing) {
            typingText.innerText = `${data.username} is typing...`;
            typingBar.style.visibility = 'visible';
        } else {
            typingBar.style.visibility = 'hidden';
        }
    }
});