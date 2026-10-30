/**
 * NexusChat - Client Logic (Enhanced)
 * Handles WebSocket communication, UI updates, sound synthesis, real-time state,
 * read receipts, group messaging, notifications, editing, replies, forwarding & reporting.
 */

// ==============================================================================
// Configuration
// ==============================================================================

const API_BASE_URL = ''; // Relative to origin when served by Flask on port 5000
const LOGIN_PAGE = '/login';

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
let groups = [];
let allUsers = [];
let activeMessages = [];
let notifications = [];
let unreadCounts = {};
let typingTimeout = null;
let isTyping = false;
let pendingAttachment = null;
let soundEnabled = true;
let selectedIcon = '💬';
let selectedGroupColor = '#8b5cf6';

// Context actions state
let replyingToMessage = null;
let forwardingMessageId = null;
let editingMessageId = null;
let reportingMessageId = null;

const EMOJI_LIST = [
  '😀', '😂', '😍', '🥳', '😎', '🤔', '🙌',
  '👍', '👎', '❤️', '🔥', '🚀', '🎉', '✨',
  '💡', '💻', '⚡', '☕', '💯', '🤖', '🔒',
  '👋', '👀', '🎯', '🎈', '⭐', '🌈', '🍕'
];

// ==============================================================================
// Audio Synthesis Notifications
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
    osc.frequency.exponentialRampToValueAtTime(750, ctx.currentTime + 0.08);

    gain.gain.setValueAtTime(0.06, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.08);

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
    if (!data.authenticated || !data.user) {
      window.location.href = LOGIN_PAGE;
      return;
    }

    currentUser = data.user;
    renderCurrentUserProfile();
    initSocketConnection();

    await loadChannels();
    await loadGroups();
    await loadUsers();
    await loadUnreadCounts();
    await loadNotifications();

    const generalChannel = channels.find(c => c.name === 'general') || channels[0];
    if (generalChannel) {
      await selectChannel(generalChannel.id);
    }
  } catch (error) {
    console.error('Initialization error:', error);
    showToast('Unable to connect to NexusChat backend.', 'error');
  }
}

function renderCurrentUserProfile() {
  if (!currentUser) return;

  const avatar = document.getElementById('footer-user-avatar');
  const name = document.getElementById('footer-user-name');
  const statusText = document.getElementById('footer-user-status-text');
  const indicator = document.getElementById('footer-user-status-indicator');
  const adminBtn = document.getElementById('admin-dashboard-btn');

  if (avatar) {
    avatar.textContent = (currentUser.display_name || currentUser.username || '?')[0].toUpperCase();
    avatar.style.backgroundColor = currentUser.avatar_color || '#6366f1';
  }

  if (name) {
    name.textContent = currentUser.display_name || currentUser.username || 'User';
  }

  if (statusText) {
    statusText.textContent = currentUser.status || 'Online';
  }

  if (indicator) {
    indicator.className = `status-indicator status-${currentUser.status || 'online'}`;
  }

  // Display admin dashboard shortcut if user has administrator role
  if (adminBtn) {
    adminBtn.style.display = (currentUser.role === 'admin') ? 'inline-flex' : 'none';
  }
}

// ==============================================================================
// Socket.IO Connection & Real-Time Event Handlers
// ==============================================================================

function initSocketConnection() {
  if (typeof io !== 'function') {
    showToast('Socket.IO library is not loaded.', 'error');
    return;
  }

  if (socket) {
    socket.disconnect();
  }

  socket = io(window.location.origin, {
    transports: ['websocket', 'polling'],
    withCredentials: true
});

  socket.on('connect', () => {
    updateConnectionStatus(true);
  });

  socket.on('connect_error', error => {
    console.error('Socket.IO connect error:', error.message);
    updateConnectionStatus(false);
  });

  socket.on('disconnect', () => {
    updateConnectionStatus(false);
  });

  // Incoming new message
  socket.on('new_message', msg => {
    handleIncomingMessage(msg);
  });

  // Message edited
  socket.on('message_edited', updatedMsg => {
    handleMessageEdited(updatedMsg);
  });

  // Message deleted
  socket.on('message_deleted', data => {
    handleMessageDeleted(data);
  });

  // Read receipts update
  socket.on('messages_read', data => {
    handleMessagesReadUpdate(data);
  });

  // Reaction updated
  socket.on('reaction_updated', data => {
    handleReactionUpdate(data);
  });

  // Typing indicators
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
    if (currentRoom && String(data.room_id) === String(currentRoom.id)) {
      hideTypingIndicator();
    }
  });

  // Presence updates
  socket.on('user_status_change', data => {
    handleUserStatusChange(data);
  });

  // New public channel created
  socket.on('new_channel_created', room => {
    if (!channels.some(c => String(c.id) === String(room.id))) {
      channels.push(room);
      renderChannelList();
    }
  });

  // User added to a group
  socket.on('group_added', room => {
    if (!groups.some(g => String(g.id) === String(room.id))) {
      groups.push(room);
      renderGroupList();
      showToast(`You were added to group "${room.name}"!`, 'info');
    }
  });

  // Group updated
  socket.on('group_updated', room => {
    const idx = groups.findIndex(g => String(g.id) === String(room.id));
    if (idx !== -1) {
      groups[idx] = { ...groups[idx], ...room };
      renderGroupList();
    }
    if (currentRoom && String(currentRoom.id) === String(room.id)) {
      currentRoom = { ...currentRoom, ...room };
      updateRoomHeader();
    }
  });

  // Group member change
  socket.on('group_member_change', data => {
    if (currentRoom && String(currentRoom.id) === String(data.room_id)) {
      loadGroupMembers(data.room_id);
    }
  });

  // New notification
  socket.on('new_notification', notif => {
    handleIncomingNotification(notif);
  });

  // Account suspended by admin
  socket.on('account_suspended', data => {
    alert(data.message || 'Your account has been suspended by an administrator.');
    window.location.href = LOGIN_PAGE;
  });
}

function updateConnectionStatus(isOnline) {
  const text = document.getElementById('connection-text');
  const pill = document.getElementById('connection-pill');

  if (text) text.textContent = isOnline ? 'Live' : 'Connecting...';
  if (pill) {
    pill.style.color = isOnline ? 'var(--status-online)' : 'var(--status-away)';
    pill.style.background = isOnline ? 'rgba(16, 185, 129, 0.12)' : 'rgba(245, 158, 11, 0.12)';
  }
}

// ==============================================================================
// Channels
// ==============================================================================

async function loadChannels() {
  try {
    const res = await apiFetch('/api/rooms');
    const data = await res.json();
    if (data.success) {
      channels = data.rooms || [];
      renderChannelList();
    }
  } catch (error) {
    console.error('Failed to load channels:', error);
  }
}

function renderChannelList() {
  const container = document.getElementById('channel-list');
  if (!container) return;
  container.innerHTML = '';

  channels.forEach(channel => {
    const isActive = currentRoom && String(currentRoom.id) === String(channel.id);
    const unreadCount = unreadCounts[channel.id] || 0;

    const item = document.createElement('div');
    item.className = `channel-item ${isActive ? 'active' : ''}`;
    item.onclick = () => selectChannel(channel.id);

    item.innerHTML = `
      <span class="channel-icon">${escapeHtml(channel.icon || '#')}</span>
      <span class="channel-name">${escapeHtml(channel.name)}</span>
      <span class="unread-badge" id="unread-room-${channel.id}" style="${unreadCount > 0 ? '' : 'display:none;'}">
        ${unreadCount}
      </span>
    `;

    container.appendChild(item);
  });
}

// ==============================================================================
// Group Conversations
// ==============================================================================

async function loadGroups() {
  try {
    const res = await apiFetch('/api/groups');
    const data = await res.json();
    if (data.success) {
      groups = data.groups || [];
      renderGroupList();
    }
  } catch (error) {
    console.error('Failed to load groups:', error);
  }
}

function renderGroupList() {
  const container = document.getElementById('group-list');
  if (!container) return;
  container.innerHTML = '';

  if (groups.length === 0) {
    container.innerHTML = `
      <div style="font-size:12px;color:var(--text-muted);padding:6px 12px;font-style:italic;">
        No groups yet. Click + to create one!
      </div>
    `;
    return;
  }

  groups.forEach(group => {
    const isActive = currentRoom && String(currentRoom.id) === String(group.id);
    const unreadCount = unreadCounts[group.id] || 0;
    const initial = (group.name || 'G')[0].toUpperCase();
    const avatarColor = group.icon && group.icon.startsWith('#') ? group.icon : '#8b5cf6';

    const item = document.createElement('div');
    item.className = `group-item ${isActive ? 'active' : ''}`;
    item.onclick = () => selectGroup(group.id);

    item.innerHTML = `
      <div class="group-avatar-badge" style="background-color: ${avatarColor};">
        ${escapeHtml(initial)}
      </div>
      <span class="group-name">${escapeHtml(group.name)}</span>
      <span class="unread-badge" id="unread-room-${group.id}" style="${unreadCount > 0 ? '' : 'display:none;'}">
        ${unreadCount}
      </span>
    `;

    container.appendChild(item);
  });
}

async function selectGroup(groupId) {
  if (currentRoom && String(currentRoom.id) === String(groupId)) return;

  if (currentRoom && socket) {
    socket.emit('leave_room', { room_id: currentRoom.id });
  }

  // Clear unread
  unreadCounts[groupId] = 0;
  const unreadEl = document.getElementById(`unread-room-${groupId}`);
  if (unreadEl) unreadEl.style.display = 'none';

  try {
    const res = await apiFetch(`/api/messages/${groupId}`);
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Could not load group messages.');
    }

    currentRoom = data.room;
    activeMessages = data.messages || [];

    if (socket) {
      socket.emit('join_room', { room_id: groupId });
    }

    updateRoomHeader();
    renderChannelList();
    renderGroupList();
    renderDMList();
    renderMessagesFeed();
    loadGroupMembers(groupId);
    scrollToBottom(false);

    const textarea = document.getElementById('chat-textarea');
    if (textarea) {
      textarea.placeholder = `Message ${currentRoom.name}...`;
      textarea.focus();
    }
  } catch (error) {
    showToast(error.message || 'Failed to open group.', 'error');
  }
}

async function loadGroupMembers(roomId) {
  try {
    const res = await apiFetch(`/api/groups/${roomId}/members`);
    const data = await res.json();
    if (data.success) {
      renderGroupMembersPanel(data.members || []);
    }
  } catch (error) {
    console.error('Failed to load group members:', error);
  }
}

function renderGroupMembersPanel(members) {
  const onlineContainer = document.getElementById('online-members-list');
  const offlineContainer = document.getElementById('offline-members-list');
  const onlineCount = document.getElementById('online-count');
  const offlineCount = document.getElementById('offline-count');

  if (!onlineContainer || !offlineContainer) return;

  onlineContainer.innerHTML = '';
  offlineContainer.innerHTML = '';

  const onlineMembers = members.filter(m => m.status === 'online');
  const offlineMembers = members.filter(m => m.status !== 'online');

  if (onlineCount) onlineCount.textContent = onlineMembers.length;
  if (offlineCount) offlineCount.textContent = offlineMembers.length;

  onlineMembers.forEach(m => onlineContainer.appendChild(createGroupMemberItem(m)));
  offlineMembers.forEach(m => offlineContainer.appendChild(createGroupMemberItem(m)));
}

function createGroupMemberItem(member) {
  const div = document.createElement('div');
  div.className = 'member-item';
  const initial = (member.display_name || member.username || '?')[0].toUpperCase();
  const isSelf = String(member.id) === String(currentUser.id);
  const isAdmin = member.role === 'admin';

  div.innerHTML = `
    <div class="avatar-wrapper">
      <div class="user-avatar" style="background-color:${safeColor(member.avatar_color)};">
        ${escapeHtml(initial)}
      </div>
      <span class="status-indicator status-${safeStatus(member.status)}"></span>
    </div>
    <div class="member-info">
      <div style="display:flex;align-items:center;gap:6px;">
        <span class="member-name">${escapeHtml(member.display_name || member.username)}</span>
        ${isAdmin ? '<span class="badge-tag" style="font-size:9px;background:rgba(239,68,68,0.2);color:#f87171;">ADMIN</span>' : ''}
        ${isSelf ? '<span style="font-size:10px;color:var(--text-muted);">(you)</span>' : ''}
      </div>
      <span class="member-bio">${escapeHtml(member.bio || `@${member.username}`)}</span>
    </div>
  `;

  return div;
}

// Group Creation Modal Helpers
function openCreateGroupModal() {
  const modal = document.getElementById('create-group-modal');
  const checklist = document.getElementById('group-member-checklist');

  if (checklist) {
    checklist.innerHTML = '';
    allUsers.forEach(u => {
      const label = document.createElement('label');
      label.className = 'member-check-item';
      label.innerHTML = `
        <input type="checkbox" name="group-member" value="${u.id}">
        <div class="user-avatar" style="width:22px;height:22px;font-size:10px;background-color:${safeColor(u.avatar_color)};">
          ${(u.display_name || u.username)[0].toUpperCase()}
        </div>
        <span style="font-size:13px;color:#fff;">${escapeHtml(u.display_name || u.username)}</span>
        <span style="font-size:11px;color:var(--text-muted);">@${escapeHtml(u.username)}</span>
      `;
      checklist.appendChild(label);
    });
  }

  if (modal) modal.classList.add('active');
}

function closeCreateGroupModal() {
  const modal = document.getElementById('create-group-modal');
  if (modal) modal.classList.remove('active');
}

function selectGroupColor(btn, color) {
  selectedGroupColor = color;
  document.querySelectorAll('#group-color-palette .color-choice-btn').forEach(b => b.classList.remove('selected'));
  if (btn) btn.classList.add('selected');
}

async function handleCreateGroup(e) {
  e.preventDefault();
  const name = document.getElementById('new-group-name')?.value.trim();
  const description = document.getElementById('new-group-desc')?.value.trim();
  const checkboxes = document.querySelectorAll('input[name="group-member"]:checked');
  const member_ids = Array.from(checkboxes).map(cb => parseInt(cb.value, 10));

  if (!name) {
    showToast('Please enter a group name.', 'error');
    return;
  }

  try {
    const res = await apiFetch('/api/groups', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        description,
        member_ids,
        avatar_color: selectedGroupColor
      })
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Failed to create group.');
    }

    closeCreateGroupModal();
    document.getElementById('new-group-name').value = '';
    document.getElementById('new-group-desc').value = '';

    groups.unshift(data.group);
    renderGroupList();
    await selectGroup(data.group.id);
    showToast(`Group "${name}" created!`, 'success');
  } catch (err) {
    showToast(err.message || 'Group creation error.', 'error');
  }
}

function openAddGroupMemberModal() {
  if (!currentRoom || currentRoom.room_type !== 'group') return;
  const modal = document.getElementById('add-group-member-modal');
  const select = document.getElementById('add-member-select');

  if (select) {
    select.innerHTML = '<option value="">-- Choose a user to add --</option>';
    allUsers.forEach(u => {
      select.innerHTML += `<option value="${u.id}">${escapeHtml(u.display_name || u.username)} (@${escapeHtml(u.username)})</option>`;
    });
  }

  if (modal) modal.classList.add('active');
}

function closeAddGroupMemberModal() {
  const modal = document.getElementById('add-group-member-modal');
  if (modal) modal.classList.remove('active');
}

async function handleAddGroupMember(e) {
  e.preventDefault();
  if (!currentRoom || currentRoom.room_type !== 'group') return;
  const select = document.getElementById('add-member-select');
  const userId = select?.value;

  if (!userId) {
    showToast('Please select a user.', 'error');
    return;
  }

  try {
    const res = await apiFetch(`/api/groups/${currentRoom.id}/members`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: parseInt(userId, 10) })
    });
    const data = await res.json();
    if (data.success) {
      closeAddGroupMemberModal();
      showToast('Member added to group!', 'success');
      loadGroupMembers(currentRoom.id);
    } else {
      showToast(data.error || 'Could not add member.', 'error');
    }
  } catch (err) {
    showToast('Operation failed.', 'error');
  }
}

async function handleLeaveGroup() {
  if (!currentRoom || currentRoom.room_type !== 'group') return;
  if (!confirm(`Are you sure you want to leave ${currentRoom.name}?`)) return;

  try {
    const res = await apiFetch(`/api/groups/${currentRoom.id}/members/${currentUser.id}`, {
      method: 'DELETE'
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Left group ${currentRoom.name}.`, 'info');
      groups = groups.filter(g => String(g.id) !== String(currentRoom.id));
      renderGroupList();
      const general = channels.find(c => c.name === 'general') || channels[0];
      if (general) selectChannel(general.id);
    } else {
      showToast(data.error || 'Failed to leave group.', 'error');
    }
  } catch (err) {
    showToast('Operation failed.', 'error');
  }
}

// ==============================================================================
// Users and Direct Messages
// ==============================================================================

async function loadUsers() {
  try {
    const res = await apiFetch('/api/users');
    const data = await res.json();
    if (data.success) {
      allUsers = (data.users || []).filter(u => String(u.id) !== String(currentUser.id));
      renderDMList();
      if (!currentRoom || currentRoom.room_type !== 'group') {
        renderMembersPanel();
      }
    }
  } catch (error) {
    console.error('Failed to load users:', error);
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
      currentRoom.room_type === 'dm' &&
      (String(currentRoom.dm_user1_id) === String(user.id) || String(currentRoom.dm_user2_id) === String(user.id));

    // Target room ID for DM unread check
    let unreadCount = 0;
    if (user.dm_room_id && unreadCounts[user.dm_room_id]) {
      unreadCount = unreadCounts[user.dm_room_id];
    }

    const item = document.createElement('div');
    item.className = `dm-item ${isActive ? 'active' : ''}`;
    item.onclick = () => selectDirectMessage(user.id);

    const initial = (user.display_name || user.username || '?')[0].toUpperCase();

    item.innerHTML = `
      <div class="avatar-wrapper">
        <div class="user-avatar" style="width:26px;height:26px;font-size:11px;background-color:${safeColor(user.avatar_color)};">
          ${escapeHtml(initial)}
        </div>
        <span class="status-indicator status-${safeStatus(user.status)}" id="dm-status-${user.id}" style="width:8px;height:8px;bottom:-1px;right:-1px;"></span>
      </div>
      <span class="dm-name">${escapeHtml(user.display_name || user.username)}</span>
      <span class="unread-badge" id="unread-dm-${user.id}" style="${unreadCount > 0 ? '' : 'display:none;'}">${unreadCount}</span>
    `;

    container.appendChild(item);
  });
}

function renderMembersPanel() {
  const onlineContainer = document.getElementById('online-members-list');
  const offlineContainer = document.getElementById('offline-members-list');
  if (!onlineContainer || !offlineContainer || !currentUser) return;

  onlineContainer.innerHTML = '';
  offlineContainer.innerHTML = '';

  const onlineUsers = allUsers.filter(u => u.status === 'online');
  const offlineUsers = allUsers.filter(u => u.status !== 'online');

  setText('online-count', onlineUsers.length + (currentUser.status === 'offline' ? 0 : 1));
  setText('offline-count', offlineUsers.length + (currentUser.status === 'offline' ? 1 : 0));

  if (currentUser.status === 'offline') {
    offlineContainer.appendChild(createMemberItem(currentUser, true));
  } else {
    onlineContainer.appendChild(createMemberItem(currentUser, true));
  }

  onlineUsers.forEach(u => onlineContainer.appendChild(createMemberItem(u)));
  offlineUsers.forEach(u => offlineContainer.appendChild(createMemberItem(u)));
}

function createMemberItem(user, isSelf = false) {
  const div = document.createElement('div');
  div.className = 'member-item';
  div.onclick = () => { if (!isSelf) selectDirectMessage(user.id); };

  const initial = (user.display_name || user.username || '?')[0].toUpperCase();
  const isBot = user.username === 'nova_bot';

  div.innerHTML = `
    <div class="avatar-wrapper">
      <div class="user-avatar" style="background-color:${safeColor(user.avatar_color)};">
        ${escapeHtml(initial)}
      </div>
      <span class="status-indicator status-${safeStatus(user.status)}"></span>
    </div>
    <div class="member-info">
      <div style="display:flex;align-items:center;gap:6px;">
        <span class="member-name">${escapeHtml(user.display_name || user.username)}</span>
        ${isBot ? '<span class="bot-tag">BOT</span>' : ''}
        ${isSelf ? '<span style="font-size:10px;color:var(--text-muted);">(you)</span>' : ''}
      </div>
      <span class="member-bio">${escapeHtml(user.bio || `@${user.username}`)}</span>
    </div>
  `;
  return div;
}

// ==============================================================================
// Switching Channels and DMs
// ==============================================================================

async function selectChannel(roomId) {
  if (currentRoom && String(currentRoom.id) === String(roomId)) return;

  if (currentRoom && socket) {
    socket.emit('leave_room', { room_id: currentRoom.id });
  }

  // Clear unread badge
  unreadCounts[roomId] = 0;
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
    renderGroupList();
    renderDMList();
    renderMembersPanel();
    renderMessagesFeed();
    scrollToBottom(false);

    const textarea = document.getElementById('chat-textarea');
    if (textarea) {
      textarea.placeholder = `Message #${currentRoom.name}...`;
      textarea.focus();
    }
  } catch (error) {
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
    const res = await apiFetch(`/api/dm/${encodeURIComponent(targetUserId)}`);
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Could not open direct message.');
    }

    currentRoom = data.room;
    activeMessages = data.messages || [];

    if (currentRoom?.id) {
      unreadCounts[currentRoom.id] = 0;
    }

    if (socket) {
      socket.emit('join_room', { room_id: currentRoom.id });
    }

    updateRoomHeader();
    renderChannelList();
    renderGroupList();
    renderDMList();
    renderMembersPanel();
    renderMessagesFeed();
    scrollToBottom(false);

    const textarea = document.getElementById('chat-textarea');
    if (textarea) {
      textarea.placeholder = `Message @${currentRoom.display_name || currentRoom.name}...`;
      textarea.focus();
    }
  } catch (error) {
    showToast(error.message || 'Failed to open direct message.', 'error');
  }
}

function updateRoomHeader() {
  if (!currentRoom) return;

  const isDM = currentRoom.room_type === 'dm' || (currentRoom.is_private && !currentRoom.room_type);
  const isGroup = currentRoom.room_type === 'group';

  let icon = currentRoom.icon || '#';
  if (isDM) icon = '🔒';
  if (isGroup) icon = '👥';

  let name = currentRoom.name;
  if (isDM) name = currentRoom.display_name || currentRoom.name;

  let desc = currentRoom.description || '';
  if (isDM) desc = 'Private direct message conversation.';

  setText('room-header-icon', icon);
  setText('room-header-name', name);
  setText('room-header-desc', desc);

  const groupBadge = document.getElementById('room-header-badge');
  if (groupBadge) {
    groupBadge.style.display = isGroup ? 'inline-block' : 'none';
  }

  setText('hero-room-icon', icon);
  setText('hero-room-name', isDM ? `Direct Message with ${name}` : (isGroup ? `Group: ${name}` : `Welcome to #${name}!`));
  setText('hero-room-desc', isDM ? `This is the beginning of your direct message history with ${name}.` : desc);

  setText('panel-room-name', `${icon} ${name}`);
  setText('panel-room-desc', desc);

  const panelGroupBadge = document.getElementById('panel-group-badge');
  if (panelGroupBadge) panelGroupBadge.style.display = isGroup ? 'inline-block' : 'none';

  const groupActions = document.getElementById('group-actions-bar');
  if (groupActions) groupActions.style.display = isGroup ? 'flex' : 'none';
}

// ==============================================================================
// Message Rendering (Replies, Forwarding, Editing, Read Receipts)
// ==============================================================================

function renderMessagesFeed() {
  const feed = document.getElementById('messages-feed');
  if (!feed) return;
  feed.innerHTML = '';

  activeMessages.forEach(msg => {
    feed.appendChild(createMessageElement(msg));
  });
}

function createMessageElement(msg) {
  const row = document.createElement('div');
  row.className = 'message-row';
  row.id = `msg-${msg.id}`;

  const initial = (msg.display_name || msg.username || '?')[0].toUpperCase();
  const timeFormatted = formatMessageTime(msg.timestamp);
  const isBot = msg.username === 'nova_bot' || msg.message_type === 'bot';
  const isSelf = currentUser && String(msg.sender_id) === String(currentUser.id);
  const isAdmin = currentUser && currentUser.role === 'admin';
  const isDeleted = !!msg.is_deleted;
  const isEdited = !!msg.is_edited;

  // Format message body
  let formattedBody = isDeleted
    ? `<span style="font-style:italic;color:var(--text-muted);">This message was deleted.</span>`
    : parseMarkdown(msg.content);

  // Quoted Reply Preview
  let replyQuoteHtml = '';
  if (msg.reply_to && !isDeleted) {
    replyQuoteHtml = `
      <div class="reply-quote-box" onclick="scrollToMessage(${msg.reply_to.id})">
        <div class="reply-quote-sender">↩ Replying to ${escapeHtml(msg.reply_to.sender_name)}</div>
        <div class="reply-quote-snippet">${escapeHtml(msg.reply_to.content)}</div>
      </div>
    `;
  }

  // Forwarded Label
  let forwardBannerHtml = '';
  if (msg.forwarded_from_sender && !isDeleted) {
    forwardBannerHtml = `
      <div class="forwarded-banner">
        <span>↪ Forwarded from</span> <strong>${escapeHtml(msg.forwarded_from_sender)}</strong>
      </div>
    `;
  }

  // Edited Label
  const editedHtml = (isEdited && !isDeleted) ? `<span class="edited-label">(edited)</span>` : '';

  // File Attachment Preview
  let fileHtml = '';
  if (msg.file_url && !isDeleted) {
    const safeFileUrl = escapeAttribute(msg.file_url);
    const isImage = /\.(png|jpe?g|gif|webp)$/i.test(msg.file_url.split('?')[0]);

    if (isImage) {
      fileHtml = `
        <div class="message-image-attachment" onclick="window.open('${safeFileUrl}', '_blank', 'noopener,noreferrer')">
          <img src="${safeFileUrl}" alt="Attachment" loading="lazy">
        </div>
      `;
    } else {
      fileHtml = `
        <div style="margin-top:8px;">
          <a href="${safeFileUrl}" target="_blank" rel="noopener noreferrer"
             style="display:inline-flex;align-items:center;gap:6px;background:var(--bg-card);padding:6px 12px;border-radius:6px;border:1px solid var(--border-subtle);color:var(--text-highlight);">
            <span>📎 Download Attachment</span>
          </a>
        </div>
      `;
    }
  }

  // Read Receipt Indicator for messages sent by current user
  let readReceiptHtml = '';
  if (isSelf && !isDeleted) {
    const status = msg.read_status || 'sent';
    let tickSymbols = '✓';
    let statusClass = 'read-status sent';

    if (status === 'delivered') {
      tickSymbols = '✓✓';
      statusClass = 'read-status delivered';
    } else if (status === 'read') {
      tickSymbols = '✓✓';
      statusClass = 'read-status read';
    }

    readReceiptHtml = `
      <span class="${statusClass}" id="receipt-msg-${msg.id}" title="${status.toUpperCase()}">
        ${tickSymbols}
      </span>
    `;
  }

  // Reactions HTML
  const reactionsHtml = isDeleted ? '' : renderReactionsHtml(msg.id, msg.reactions || []);

  // Action Buttons
  let actionButtonsHtml = '';
  if (!isDeleted) {
    actionButtonsHtml = `
      <div class="message-actions-bar">
        <button class="quick-react-btn" onclick="sendReaction(${Number(msg.id)}, '👍')" title="Thumbs up">👍</button>
        <button class="quick-react-btn" onclick="sendReaction(${Number(msg.id)}, '❤️')" title="Heart">❤️</button>
        <button class="quick-react-btn" onclick="sendReaction(${Number(msg.id)}, '😂')" title="Laugh">😂</button>
        <button class="quick-react-btn" onclick="sendReaction(${Number(msg.id)}, '🔥')" title="Fire">🔥</button>
        <button class="quick-react-btn" onclick="sendReaction(${Number(msg.id)}, '🚀')" title="Rocket">🚀</button>
        <button class="quick-react-btn" onclick="handleStartReply(${Number(msg.id)})" title="Reply">↩️</button>
        <button class="quick-react-btn" onclick="openForwardModal(${Number(msg.id)})" title="Forward">↪️</button>
        <button class="quick-react-btn" onclick="copyMessageText('${escapeAttribute(msg.content || '')}')" title="Copy Text">📋</button>
        ${!isSelf ? `<button class="quick-react-btn" onclick="openReportModal(${Number(msg.id)})" title="Report Message">🚩</button>` : ''}
        ${isSelf ? `<button class="quick-react-btn" onclick="openEditMessageModal(${Number(msg.id)})" title="Edit Message">✏️</button>` : ''}
        ${isSelf || isAdmin ? `<button class="quick-react-btn" onclick="handleDeleteMessage(${Number(msg.id)})" title="Delete Message" style="color:#f87171;">🗑️</button>` : ''}
      </div>
    `;
  }

  row.innerHTML = `
    <div class="message-avatar-col">
      <div class="msg-avatar" style="background-color:${safeColor(msg.avatar_color)};">
        ${escapeHtml(initial)}
      </div>
    </div>
    <div class="message-content-col">
      <div class="message-meta">
        <span class="message-sender" onclick="openUserProfile('${escapeAttribute(String(msg.sender_id))}')">
          ${escapeHtml(msg.display_name || msg.username)}
        </span>
        ${isBot ? '<span class="bot-tag">BOT</span>' : ''}
        <span class="message-time">
          ${escapeHtml(timeFormatted)}
          ${editedHtml}
        </span>
        ${readReceiptHtml}
      </div>

      ${forwardBannerHtml}
      ${replyQuoteHtml}

      <div class="message-body" id="body-msg-${msg.id}">${formattedBody}</div>
      ${fileHtml}

      <div class="reactions-row" id="reactions-for-${msg.id}">
        ${reactionsHtml}
      </div>
    </div>
    ${actionButtonsHtml}
  `;

  return row;
}

function renderReactionsHtml(messageId, reactions) {
  if (!Array.isArray(reactions) || reactions.length === 0) return '';

  return reactions.map(reaction => {
    const users = reaction.users || [];
    const userReacted = currentUser && users.some(u => String(u.id) === String(currentUser.id));
    const userNames = users.map(u => u.display_name || u.username).join(', ');

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
  const container = document.getElementById(`reactions-for-${data.message_id}`);
  if (container) {
    container.innerHTML = renderReactionsHtml(data.message_id, data.reactions || []);
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

// Scroll smoothly to replied message and flash highlight
function scrollToMessage(messageId) {
  const target = document.getElementById(`msg-${messageId}`);
  if (target) {
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.remove('message-highlighted');
    void target.offsetWidth; // Trigger reflow
    target.classList.add('message-highlighted');
  } else {
    showToast('Original message is not in recent history.', 'info');
  }
}

// ==============================================================================
// Message Actions: Reply, Forward, Edit, Delete, Report
// ==============================================================================

// 1. Reply
function handleStartReply(messageId) {
  const msg = activeMessages.find(m => String(m.id) === String(messageId));
  if (!msg) return;

  replyingToMessage = msg;
  const bar = document.getElementById('reply-preview-bar');
  const userEl = document.getElementById('reply-preview-user');
  const textEl = document.getElementById('reply-preview-text');

  if (userEl) userEl.textContent = `Replying to ${msg.display_name || msg.username}`;
  if (textEl) textEl.textContent = msg.content || 'Attachment';
  if (bar) bar.style.display = 'flex';

  const textarea = document.getElementById('chat-textarea');
  if (textarea) textarea.focus();
}

function cancelReply() {
  replyingToMessage = null;
  const bar = document.getElementById('reply-preview-bar');
  if (bar) bar.style.display = 'none';
}

// 2. Forward
function openForwardModal(messageId) {
  const msg = activeMessages.find(m => String(m.id) === String(messageId));
  if (!msg) return;

  forwardingMessageId = messageId;
  const modal = document.getElementById('forward-message-modal');
  const preview = document.getElementById('forward-preview-box');
  const select = document.getElementById('forward-destination-select');

  if (preview) {
    preview.innerHTML = `<strong>${escapeHtml(msg.display_name || msg.username)}:</strong> ${escapeHtml(msg.content || '[Attachment]')}`;
  }

  if (select) {
    select.innerHTML = '<option value="">-- Choose destination --</option>';

    // Public Channels
    const channelOptGroup = document.createElement('optgroup');
    channelOptGroup.label = 'Channels';
    channels.forEach(c => {
      channelOptGroup.innerHTML += `<option value="${c.id}"># ${escapeHtml(c.name)}</option>`;
    });
    select.appendChild(channelOptGroup);

    // Groups
    if (groups.length > 0) {
      const groupOptGroup = document.createElement('optgroup');
      groupOptGroup.label = 'Groups';
      groups.forEach(g => {
        groupOptGroup.innerHTML += `<option value="${g.id}">👥 ${escapeHtml(g.name)}</option>`;
      });
      select.appendChild(groupOptGroup);
    }
  }

  if (modal) modal.classList.add('active');
}

function closeForwardModal() {
  forwardingMessageId = null;
  const modal = document.getElementById('forward-message-modal');
  if (modal) modal.classList.remove('active');
}

async function handleExecuteForward(e) {
  e.preventDefault();
  const select = document.getElementById('forward-destination-select');
  const targetRoomId = select?.value;

  if (!forwardingMessageId || !targetRoomId) {
    showToast('Please select a destination.', 'error');
    return;
  }

  try {
    const res = await apiFetch('/api/messages/forward', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message_id: forwardingMessageId,
        target_room_id: parseInt(targetRoomId, 10)
      })
    });
    const data = await res.json();
    if (data.success) {
      closeForwardModal();
      showToast('Message forwarded successfully!', 'success');
      // If forwarded to current room, it will appear via socket event
    } else {
      showToast(data.error || 'Failed to forward message.', 'error');
    }
  } catch (err) {
    showToast('Forwarding error.', 'error');
  }
}

// 3. Edit Message
function openEditMessageModal(messageId) {
  const msg = activeMessages.find(m => String(m.id) === String(messageId));
  if (!msg) return;

  editingMessageId = messageId;
  const modal = document.getElementById('edit-message-modal');
  const textarea = document.getElementById('edit-message-textarea');

  if (textarea) {
    textarea.value = msg.content || '';
  }

  if (modal) modal.classList.add('active');
}

function closeEditMessageModal() {
  editingMessageId = null;
  const modal = document.getElementById('edit-message-modal');
  if (modal) modal.classList.remove('active');
}

async function handleSaveEditedMessage(e) {
  e.preventDefault();
  const textarea = document.getElementById('edit-message-textarea');
  const newContent = textarea?.value.trim();

  if (!editingMessageId || !newContent) {
    showToast('Message content cannot be empty.', 'error');
    return;
  }

  try {
    const res = await apiFetch(`/api/messages/${editingMessageId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: newContent })
    });
    const data = await res.json();
    if (data.success) {
      closeEditMessageModal();
      showToast('Message updated.', 'success');
      handleMessageEdited(data.message);
    } else {
      showToast(data.error || 'Failed to update message.', 'error');
    }
  } catch (err) {
    showToast('Failed to edit message.', 'error');
  }
}

function handleMessageEdited(updatedMsg) {
  const idx = activeMessages.findIndex(m => String(m.id) === String(updatedMsg.id));
  if (idx !== -1) {
    activeMessages[idx] = { ...activeMessages[idx], ...updatedMsg };
  }

  const row = document.getElementById(`msg-${updatedMsg.id}`);
  if (row) {
    const body = row.querySelector('.message-body');
    if (body) body.innerHTML = parseMarkdown(updatedMsg.content);

    const timeEl = row.querySelector('.message-time');
    if (timeEl && !timeEl.querySelector('.edited-label')) {
      timeEl.innerHTML += `<span class="edited-label">(edited)</span>`;
    }
  }
}

// 4. Delete Message
async function handleDeleteMessage(messageId) {
  if (!confirm('Are you sure you want to delete this message? This cannot be undone.')) return;

  try {
    const res = await apiFetch(`/api/messages/${messageId}`, {
      method: 'DELETE'
    });
    const data = await res.json();
    if (data.success) {
      showToast('Message deleted.', 'info');
      handleMessageDeleted({ message_id: messageId });
    } else {
      showToast(data.error || 'Could not delete message.', 'error');
    }
  } catch (err) {
    showToast('Delete operation failed.', 'error');
  }
}

function handleMessageDeleted(data) {
  const msgId = data.message_id;
  const idx = activeMessages.findIndex(m => String(m.id) === String(msgId));
  if (idx !== -1) {
    activeMessages[idx].is_deleted = 1;
    activeMessages[idx].content = 'This message was deleted.';
    activeMessages[idx].file_url = null;
  }

  const row = document.getElementById(`msg-${msgId}`);
  if (row) {
    const body = row.querySelector('.message-body');
    if (body) {
      body.innerHTML = `<span style="font-style:italic;color:var(--text-muted);">This message was deleted.</span>`;
    }
    const attachment = row.querySelector('.message-image-attachment');
    if (attachment) attachment.remove();
    const actions = row.querySelector('.message-actions-bar');
    if (actions) actions.remove();
    const reactions = row.querySelector('.reactions-row');
    if (reactions) reactions.remove();
    const receipt = row.querySelector('.read-status');
    if (receipt) receipt.remove();
  }
}

// 5. Report Message
function openReportModal(messageId) {
  reportingMessageId = messageId;
  const modal = document.getElementById('report-message-modal');
  if (modal) modal.classList.add('active');
}

function closeReportModal() {
  reportingMessageId = null;
  const modal = document.getElementById('report-message-modal');
  if (modal) modal.classList.remove('active');
}

async function handleSubmitReport(e) {
  e.preventDefault();
  if (!reportingMessageId) return;

  const reason = document.getElementById('report-reason-select')?.value;
  const details = document.getElementById('report-details-input')?.value.trim();

  try {
    const res = await apiFetch('/api/reports', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message_id: reportingMessageId,
        reason,
        details
      })
    });
    const data = await res.json();
    if (data.success) {
      closeReportModal();
      document.getElementById('report-details-input').value = '';
      showToast('Report submitted. A moderator will review it.', 'success');
    } else {
      showToast(data.error || 'Failed to submit report.', 'error');
    }
  } catch (err) {
    showToast('Failed to submit report.', 'error');
  }
}

// ==============================================================================
// Read Receipts & Unread Badges
// ==============================================================================

async function loadUnreadCounts() {
  try {
    const res = await apiFetch('/api/unread-counts');
    const data = await res.json();
    if (data.success) {
      unreadCounts = data.unread_counts || {};
      renderChannelList();
      renderGroupList();
      renderDMList();
    }
  } catch (err) {
    console.error('Failed to load unread counts:', err);
  }
}

function handleMessagesReadUpdate(data) {
  if (currentRoom && String(data.room_id) === String(currentRoom.id)) {
    // Other member in room has read messages; turn receipts to blue double tick!
    (data.message_ids || []).forEach(mid => {
      const receipt = document.getElementById(`receipt-msg-${mid}`);
      if (receipt) {
        receipt.className = 'read-status read';
        receipt.textContent = '✓✓';
        receipt.title = 'READ';
      }
    });
  }
}

// ==============================================================================
// Notification Center
// ==============================================================================

async function loadNotifications() {
  try {
    const res = await apiFetch('/api/notifications');
    const data = await res.json();
    if (data.success) {
      notifications = data.notifications || [];
      updateNotificationBadge(data.unread_count || 0);
      renderNotificationDropdown();
    }
  } catch (err) {
    console.error('Failed to load notifications:', err);
  }
}

function updateNotificationBadge(count) {
  const badge = document.getElementById('notif-badge');
  if (badge) {
    if (count > 0) {
      badge.style.display = 'inline-block';
      badge.textContent = count > 99 ? '99+' : count;
    } else {
      badge.style.display = 'none';
    }
  }
}

function renderNotificationDropdown() {
  const container = document.getElementById('notif-dropdown-list');
  if (!container) return;
  container.innerHTML = '';

  if (notifications.length === 0) {
    container.innerHTML = '<div class="notif-empty-state">No notifications yet</div>';
    return;
  }

  notifications.forEach(n => {
    const div = document.createElement('div');
    div.className = `notif-item ${n.is_read ? '' : 'unread'}`;
    div.onclick = () => handleNotificationClick(n);

    let icon = '🔔';
    if (n.type === 'dm') icon = '💬';
    if (n.type === 'group_message') icon = '👥';
    if (n.type === 'mention') icon = '@';
    if (n.type === 'reply') icon = '↩️';
    if (n.type === 'reaction') icon = '❤️';
    if (n.type === 'group_invite') icon = '🎉';
    if (n.type === 'admin') icon = '🛡️';

    div.innerHTML = `
      <div class="notif-item-icon">${icon}</div>
      <div class="notif-item-content">
        <div class="notif-item-title">${escapeHtml(n.title)}</div>
        <div class="notif-item-body">${escapeHtml(n.content)}</div>
        <div class="notif-item-time">${formatDateRelative(n.created_at)}</div>
      </div>
    `;

    container.appendChild(div);
  });
}

function toggleNotificationCenter(e) {
  if (e) e.stopPropagation();
  const dropdown = document.getElementById('notif-dropdown');
  if (dropdown) dropdown.classList.toggle('active');
}

document.addEventListener('click', e => {
  const dropdown = document.getElementById('notif-dropdown');
  const btn = document.getElementById('notif-bell-btn');
  if (dropdown && !dropdown.contains(e.target) && !btn?.contains(e.target)) {
    dropdown.classList.remove('active');
  }
});

async function handleNotificationClick(notif) {
  // Mark as read
  if (!notif.is_read) {
    notif.is_read = 1;
    apiFetch(`/api/notifications/${notif.id}/read`, { method: 'POST' });
    const currentCount = parseInt(document.getElementById('notif-badge')?.textContent || '1', 10);
    updateNotificationBadge(Math.max(0, currentCount - 1));
    renderNotificationDropdown();
  }

  // Close dropdown
  const dropdown = document.getElementById('notif-dropdown');
  if (dropdown) dropdown.classList.remove('active');

  // Navigate to conversation
  if (notif.room_id) {
    const targetRoom = channels.find(c => String(c.id) === String(notif.room_id))
                    || groups.find(g => String(g.id) === String(notif.room_id));

    if (targetRoom) {
      if (targetRoom.room_type === 'group') {
        await selectGroup(targetRoom.id);
      } else {
        await selectChannel(targetRoom.id);
      }
    } else {
      // Might be a DM or new group
      await selectChannel(notif.room_id);
    }

    if (notif.message_id) {
      setTimeout(() => scrollToMessage(notif.message_id), 300);
    }
  }
}

async function handleMarkAllNotificationsRead() {
  try {
    await apiFetch('/api/notifications/read-all', { method: 'POST' });
    notifications.forEach(n => { n.is_read = 1; });
    updateNotificationBadge(0);
    renderNotificationDropdown();
    showToast('All notifications marked as read.', 'info');
  } catch (err) {
    console.error('Failed to mark notifications read:', err);
  }
}

function handleIncomingNotification(notif) {
  notifications.unshift(notif);
  const currentCount = parseInt(document.getElementById('notif-badge')?.textContent || '0', 10);
  updateNotificationBadge(currentCount + 1);
  renderNotificationDropdown();
  playReceiveSound();
  showToast(`🔔 ${notif.title}: ${notif.content}`, 'info');
}

// ==============================================================================
// Sending and Incoming Messages
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
  textarea.style.height = Math.min(textarea.scrollHeight, 140) + 'px';

  if (!socket || !currentRoom) return;

  if (!isTyping) {
    isTyping = true;
    socket.emit('typing', { room_id: currentRoom.id });
  }

  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(() => {
    isTyping = false;
    if (socket && currentRoom) {
      socket.emit('stop_typing', { room_id: currentRoom.id });
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
    file_url: pendingAttachment ? pendingAttachment.file_url : null,
    reply_to_id: replyingToMessage ? replyingToMessage.id : null
  };

  socket.emit('send_message', payload);

  clearTimeout(typingTimeout);
  isTyping = false;
  socket.emit('stop_typing', { room_id: currentRoom.id });

  textarea.value = '';
  textarea.style.height = 'auto';

  removePendingAttachment();
  cancelReply();
  playSendSound();
}

function handleIncomingMessage(msg) {
  if (currentRoom && String(msg.room_id) === String(currentRoom.id)) {
    activeMessages.push(msg);

    const feed = document.getElementById('messages-feed');
    if (feed) {
      feed.appendChild(createMessageElement(msg));
    }

    if (String(msg.sender_id) !== String(currentUser.id)) {
      playReceiveSound();
      // Mark read in current room
      socket.emit('mark_read', { room_id: currentRoom.id });
    }

    const container = document.getElementById('messages-container');
    if (container) {
      const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 160;
      if (isNearBottom || String(msg.sender_id) === String(currentUser.id)) {
        scrollToBottom(true);
      } else {
        const button = document.getElementById('scroll-bottom-btn');
        if (button) button.classList.add('active');
      }
    }
  } else {
    // Inactive room: increment unread counter
    showUnreadBadge(msg.room_id, msg.sender_id);
    if (String(msg.sender_id) !== String(currentUser.id)) {
      playReceiveSound();
    }
  }
}

function showUnreadBadge(roomId, senderId) {
  unreadCounts[roomId] = (unreadCounts[roomId] || 0) + 1;

  const roomBadge = document.getElementById(`unread-room-${roomId}`);
  if (roomBadge) {
    roomBadge.style.display = 'inline-block';
    roomBadge.textContent = unreadCounts[roomId];
  }

  const dmBadge = document.getElementById(`unread-dm-${senderId}`);
  if (dmBadge) {
    dmBadge.style.display = 'inline-block';
    dmBadge.textContent = (parseInt(dmBadge.textContent || '0', 10) + 1);
  }
}

function showTypingIndicator(name) {
  const indicator = document.getElementById('typing-indicator');
  const text = document.getElementById('typing-text');
  if (text) text.textContent = `${name} is typing...`;
  if (indicator) indicator.style.visibility = 'visible';
}

function hideTypingIndicator() {
  const indicator = document.getElementById('typing-indicator');
  if (indicator) indicator.style.visibility = 'hidden';
}

// ==============================================================================
// User Status & Presence
// ==============================================================================

function handleUserStatusChange(data) {
  const user = allUsers.find(item => String(item.id) === String(data.user_id));
  if (user) {
    user.status = data.status;
  }

  if (currentUser && String(currentUser.id) === String(data.user_id)) {
    currentUser.status = data.status;
    renderCurrentUserProfile();
  }

  renderDMList();
  if (currentRoom && currentRoom.room_type === 'group') {
    loadGroupMembers(currentRoom.id);
  } else {
    renderMembersPanel();
  }
}

function toggleUserStatusMenu(event) {
  if (event) event.stopPropagation();
  if (!currentUser) return;

  const statuses = ['online', 'away', 'busy'];
  const currentIndex = statuses.indexOf(currentUser.status || 'online');
  const nextStatus = statuses[(currentIndex + 1) % statuses.length];

  currentUser.status = nextStatus;
  renderCurrentUserProfile();

  if (socket && socket.connected) {
    socket.emit('status_update', { status: nextStatus });
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
    showToast(error.message || 'File upload error.', 'error');
  } finally {
    event.target.value = '';
  }
}

function showAttachmentPreview(attachment) {
  const previewBar = document.getElementById('attachment-preview-bar');
  const previewImg = document.getElementById('attachment-preview-img');
  const previewName = document.getElementById('attachment-preview-name');

  if (previewName) previewName.textContent = attachment.filename || 'Attachment';
  if (previewImg) {
    if (attachment.is_image) {
      previewImg.src = attachment.file_url;
      previewImg.style.display = 'block';
    } else {
      previewImg.style.display = 'none';
    }
  }
  if (previewBar) previewBar.classList.add('active');
}

function removePendingAttachment() {
  pendingAttachment = null;
  const previewBar = document.getElementById('attachment-preview-bar');
  if (previewBar) previewBar.classList.remove('active');
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
  if (popover) popover.classList.toggle('active');
}

function insertEmoji(emoji) {
  const textarea = document.getElementById('chat-textarea');
  if (!textarea) return;

  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const text = textarea.value;

  textarea.value = text.substring(0, start) + emoji + text.substring(end);
  textarea.selectionStart = textarea.selectionEnd = start + emoji.length;
  textarea.focus();

  const popover = document.getElementById('emoji-popover');
  if (popover) popover.classList.remove('active');
}

document.addEventListener('click', event => {
  const popover = document.getElementById('emoji-popover');
  const trigger = document.getElementById('emoji-trigger-btn');
  if (popover && !popover.contains(event.target) && !trigger?.contains(event.target)) {
    popover.classList.remove('active');
  }
});

// ==============================================================================
// Search Messages
// ==============================================================================

function handleSearchMessages(query) {
  const search = query.toLowerCase().trim();
  const rows = document.querySelectorAll('.message-row');

  rows.forEach(row => {
    const body = row.querySelector('.message-body')?.textContent.toLowerCase() || '';
    const sender = row.querySelector('.message-sender')?.textContent.toLowerCase() || '';
    const matches = !search || body.includes(search) || sender.includes(search);

    row.style.display = matches ? 'flex' : 'none';
    row.style.backgroundColor = search && matches ? 'rgba(99, 102, 241, 0.12)' : 'transparent';
  });
}

// ==============================================================================
// Channel Creation Modal
// ==============================================================================

function openCreateChannelModal() {
  const modal = document.getElementById('create-channel-modal');
  const input = document.getElementById('new-channel-name');
  if (modal) modal.classList.add('active');
  if (input) input.focus();
}

function closeCreateChannelModal() {
  const modal = document.getElementById('create-channel-modal');
  if (modal) modal.classList.remove('active');
}

function selectChannelIcon(button, icon) {
  selectedIcon = icon;
  document.querySelectorAll('.icon-option-btn').forEach(item => item.classList.remove('selected'));
  if (button) button.classList.add('selected');
}

async function handleCreateChannel(event) {
  event.preventDefault();
  const name = document.getElementById('new-channel-name')?.value.trim() || '';
  const description = document.getElementById('new-channel-desc')?.value.trim() || '';

  if (!name) {
    showToast('Please enter a channel name.', 'error');
    return;
  }

  try {
    const res = await apiFetch('/api/rooms', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description, icon: selectedIcon })
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || 'Failed to create channel.');
    }

    closeCreateChannelModal();
    document.getElementById('new-channel-name').value = '';
    document.getElementById('new-channel-desc').value = '';

    if (data.room?.id) {
      if (!channels.some(c => String(c.id) === String(data.room.id))) {
        channels.push(data.room);
        renderChannelList();
      }
      await selectChannel(data.room.id);
    }
    showToast(`Channel #${name} created!`, 'success');
  } catch (error) {
    showToast(error.message || 'Failed to create channel.', 'error');
  }
}

// ==============================================================================
// User Profile Modal
// ==============================================================================

function openProfileModal() {
  if (currentUser) openUserProfile(currentUser.id);
}

function openUserProfile(userId) {
  if (!currentUser) return;
  const user = String(userId) === String(currentUser.id)
    ? currentUser
    : allUsers.find(item => String(item.id) === String(userId));

  if (!user) return;

  const avatar = document.getElementById('modal-avatar');
  if (avatar) {
    avatar.textContent = (user.display_name || user.username || '?')[0].toUpperCase();
    avatar.style.backgroundColor = safeColor(user.avatar_color);
  }

  setText('modal-display-name', user.display_name || user.username);
  setText('modal-username', `@${user.username}`);
  setText('modal-bio', user.bio || 'No status bio provided.');

  const roleBadge = document.getElementById('modal-role-badge');
  if (roleBadge) {
    roleBadge.textContent = (user.role || 'user').toUpperCase();
    roleBadge.className = `badge-tag ${user.role === 'admin' ? 'badge-admin' : 'badge-user'}`;
  }

  const modal = document.getElementById('user-profile-modal');
  if (modal) modal.classList.add('active');
}

function closeProfileModal() {
  const modal = document.getElementById('user-profile-modal');
  if (modal) modal.classList.remove('active');
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
    showToast('Could not copy message text.', 'error');
  }
}

function toggleSound() {
  soundEnabled = !soundEnabled;
  const button = document.getElementById('sound-toggle-btn');
  const icon = document.getElementById('sound-icon');
  if (button) button.classList.toggle('active', soundEnabled);
  if (icon) icon.textContent = soundEnabled ? '🔔' : '🔕';
  showToast(soundEnabled ? 'Audio notifications enabled' : 'Audio notifications muted', 'info');
}

function toggleRightPanel() {
  const panel = document.getElementById('right-panel');
  const button = document.getElementById('right-panel-toggle-btn');
  if (!panel) return;
  panel.classList.toggle('hidden');
  if (button) button.classList.toggle('active', !panel.classList.contains('hidden'));
}

function toggleMobileSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (sidebar) sidebar.classList.toggle('open');
}

function scrollToBottom(smooth = true) {
  const container = document.getElementById('messages-container');
  if (!container) return;
  container.scrollTo({
    top: container.scrollHeight,
    behavior: smooth ? 'smooth' : 'auto'
  });
  const button = document.getElementById('scroll-bottom-btn');
  if (button) button.classList.remove('active');
}

function initScrollListener() {
  const container = document.getElementById('messages-container');
  if (!container) return;
  container.addEventListener('scroll', () => {
    const isNearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
    if (isNearBottom) {
      const button = document.getElementById('scroll-bottom-btn');
      if (button) button.classList.remove('active');
    }
  });
}

async function handleLogout() {
  try {
    await apiFetch('/api/auth/logout', { method: 'POST' });
  } catch (error) {
    console.error('Logout request failed:', error);
  } finally {
    if (socket) socket.disconnect();
    window.location.href = LOGIN_PAGE;
  }
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

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

// Markdown parsing and HTML escaping
function parseMarkdown(text) {
  if (!text) return '';
  let str = escapeHtml(text);
  str = str.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
  str = str.replace(/`([^`]+)`/g, '<code>$1</code>');
  str = str.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  str = str.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  str = str.replace(/\n/g, '<br>');
  str = str.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
  return str;
}

function escapeHtml(text) {
  if (text === null || text === undefined) return '';
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(text).replace(/[&<>"']/g, char => map[char]);
}

function escapeAttribute(text) {
  if (text === null || text === undefined) return '';
  return String(text).replace(/&/g, '&amp;').replace(/'/g, '&#039;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatMessageTime(isoString) {
  if (!isoString) return '';
  let normalized = String(isoString).replace(' ', 'T');
  if (!normalized.endsWith('Z') && !/[+-]\d{2}:\d{2}$/.test(normalized)) normalized += 'Z';
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return String(isoString);
  const hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  const displayHours = hours % 12 || 12;
  return `Today at ${displayHours}:${minutes} ${ampm}`;
}

function formatDateRelative(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString.replace(' ', 'T') + (isoString.includes('Z') ? '' : 'Z'));
  if (isNaN(d.getTime())) return isoString;
  const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diffSec < 60) return 'Just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  return `${Math.floor(diffSec / 86400)}d ago`;
}

function setText(elementId, value) {
  const element = document.getElementById(elementId);
  if (element) element.textContent = value ?? '';
}

function safeColor(value) {
  if (typeof value === 'string' && /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgb[a]?\([\d\s%,.]+\)|hsl[a]?\([\d\s%,.]+\))$/.test(value)) {
    return value;
  }
  return '#6366f1';
}

function safeStatus(value) {
  const allowed = ['online', 'offline', 'away', 'busy'];
  return allowed.includes(value) ? value : 'offline';
}
