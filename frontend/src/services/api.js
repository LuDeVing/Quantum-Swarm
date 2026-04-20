import AsyncStorage from '@react-native-async-storage/async-storage';

// =====================================================
// CONFIGURATION — Point this to your backend server
// =====================================================
const BASE_URL = 'http://localhost:3001/api';

// =====================================================
// HTTP client with auth token injection
// =====================================================
async function getToken() {
  return await AsyncStorage.getItem('authToken');
}

async function request(endpoint, options = {}) {
  const token = await getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token && { Authorization: `Bearer ${token}` }),
    ...options.headers,
  };

  const res = await fetch(`${BASE_URL}${endpoint}`, {
    ...options,
    headers,
  });

  const data = await res.json();

  if (!res.ok) {
    const error = new Error(data.message || 'Request failed');
    error.status = res.status;
    error.data = data;
    throw error;
  }

  return data;
}

// =====================================================
// AUTH ENDPOINTS
// =====================================================

/**
 * POST /api/auth/login
 * Body: { email, password }
 * Response: { user: { id, name, email, avatar }, token }
 */
export async function loginWithEmail(email, password) {
  const data = await request('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  await AsyncStorage.setItem('authToken', data.token);
  await AsyncStorage.setItem('currentUser', JSON.stringify(data.user));
  return data;
}

/**
 * POST /api/auth/register
 * Body: { name, email, password }
 * Response: { user: { id, name, email, avatar }, token }
 */
export async function registerWithEmail(name, email, password) {
  const data = await request('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ name, email, password }),
  });
  await AsyncStorage.setItem('authToken', data.token);
  await AsyncStorage.setItem('currentUser', JSON.stringify(data.user));
  return data;
}

/**
 * POST /api/auth/google
 * Body: { idToken } — Google OAuth ID token from client-side flow
 * Response: { user: { id, name, email, avatar }, token }
 */
export async function loginWithGoogle(idToken) {
  const data = await request('/auth/google', {
    method: 'POST',
    body: JSON.stringify({ idToken }),
  });
  await AsyncStorage.setItem('authToken', data.token);
  await AsyncStorage.setItem('currentUser', JSON.stringify(data.user));
  return data;
}

/**
 * POST /api/auth/github
 * Body: { code } — GitHub OAuth authorization code
 * Response: { user: { id, name, email, avatar }, token }
 */
export async function loginWithGithub(code) {
  const data = await request('/auth/github', {
    method: 'POST',
    body: JSON.stringify({ code }),
  });
  await AsyncStorage.setItem('authToken', data.token);
  await AsyncStorage.setItem('currentUser', JSON.stringify(data.user));
  return data;
}

/**
 * OAuth login via Electron popup window.
 * Opens a popup to the backend's OAuth redirect endpoint.
 * The backend handles the full OAuth flow and redirects back with token + user.
 * @param {'google'|'github'} provider
 * @returns {{ user, token }}
 */
export async function oauthLogin(provider) {
  // Use Electron's IPC bridge (exposed via preload.js)
  if (window.electronAuth) {
    const data = await window.electronAuth.oauthLogin(provider);
    await AsyncStorage.setItem('authToken', data.token);
    await AsyncStorage.setItem('currentUser', JSON.stringify(data.user));
    return data;
  }

  // Fallback for non-Electron (browser): open popup window
  return new Promise((resolve, reject) => {
    const url = `${BASE_URL}/auth/${provider}/redirect`;
    const popup = window.open(url, 'OAuth', 'width=500,height=700');

    if (!popup) {
      reject(new Error('Popup blocked. Please allow popups for this app.'));
      return;
    }

    const handleMessage = async (event) => {
      if (event.data?.type === 'oauth-callback' && event.data.token) {
        window.removeEventListener('message', handleMessage);
        await AsyncStorage.setItem('authToken', event.data.token);
        await AsyncStorage.setItem('currentUser', JSON.stringify(event.data.user));
        resolve({ token: event.data.token, user: event.data.user });
      }
    };

    window.addEventListener('message', handleMessage);

    // Check if popup was closed without completing
    const pollTimer = setInterval(() => {
      if (popup.closed) {
        clearInterval(pollTimer);
        window.removeEventListener('message', handleMessage);
        reject(new Error('Sign-in window was closed'));
      }
    }, 500);
  });
}

/**
 * GET /api/auth/me
 * Headers: Authorization: Bearer <token>
 * Response: { user: { id, name, email, avatar } }
 */
export async function getMe() {
  return await request('/auth/me');
}

/**
 * POST /api/auth/logout
 * Clears local token + notifies backend
 */
export async function logout() {
  try {
    await request('/auth/logout', { method: 'POST' });
  } catch (e) {
    // still clear locally even if backend call fails
  }
  await AsyncStorage.removeItem('authToken');
  await AsyncStorage.removeItem('currentUser');
}

// =====================================================
// PROJECTS ENDPOINTS
// =====================================================

/**
 * GET /api/projects
 * Response: { projects: [{ id, name, status, date, lastMessage }] }
 */
export async function getProjects() {
  return await request('/projects');
}

/**
 * POST /api/projects
 * Body: { name }
 * Response: { project: { id, name, status, date } }
 */
export async function createProject(name) {
  return await request('/projects', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

/**
 * DELETE /api/projects/:id
 * Response: { success: true }
 */
export async function deleteProject(id) {
  return await request(`/projects/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  });
}

/**
 * PATCH /api/projects/:id
 * Body: { name?, status? }
 * Response: { project: { id, name, status, date } }
 */
export async function updateProject(id, updates) {
  return await request(`/projects/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });
}

// =====================================================
// CHAT / AI ENDPOINTS
// =====================================================

/**
 * GET /api/projects/:projectId/messages
 * Query: ?page=1&limit=50
 * Response: { messages: [{ id, text, sender, time, createdAt }] }
 */
export async function getProjectMessages(projectId, page = 1, limit = 50) {
  return await request(
    `/projects/${encodeURIComponent(projectId)}/messages?page=${page}&limit=${limit}`
  );
}

/**
 * POST /api/projects/:projectId/messages
 * Body: { text }
 * Response: { userMessage: { id, text, sender, time }, aiReply: { id, text, sender, time } }
 *
 * The backend processes the user message, sends it to the AI,
 * and returns both the saved user message and the AI response.
 */
export async function sendMessage(projectId, text) {
  return await request(`/projects/${encodeURIComponent(projectId)}/messages`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

/**
 * GET /api/chat/messages
 * General chat (no project context)
 * Query: ?page=1&limit=50
 * Response: { messages: [{ id, text, sender, time, createdAt }] }
 */
export async function getGeneralMessages(page = 1, limit = 50) {
  return await request(`/chat/messages?page=${page}&limit=${limit}`);
}

/**
 * POST /api/chat/messages
 * General chat (no project context)
 * Body: { text }
 * Response: { userMessage: { id, text, sender, time }, aiReply: { id, text, sender, time } }
 */
export async function sendGeneralMessage(text) {
  return await request('/chat/messages', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

export { BASE_URL };
