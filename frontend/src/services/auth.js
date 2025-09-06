import api from "./api";

const TOKEN_KEY = "access_token";

function setAuthToken(token) {
  if (!api || !api.defaults) return;
  if (token) {
    api.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  } else {
    delete api.defaults.headers.common["Authorization"];
  }
}

function readStoredToken() {
  return localStorage.getItem(TOKEN_KEY);
}

async function login({ email, password }) {
  try {
    const res = await api.post("/api/v1/auth/login", { email, password });
    const data = res.data ?? res;
    const token = data?.access_token ?? data?.token ?? null;
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
      setAuthToken(token);
    }
    return data;
  } catch (err) {
    const message = err?.response?.data?.detail || err?.response?.data?.message || err.message || "Login failed";
    throw new Error(message);
  }
}

async function signup(payload) {
  try {
    // try common register endpoints
    const endpoint = "/api/v1/auth/register";
    const res = await api.post(endpoint, payload);
    const data = res.data ?? res;
    const token = data?.access_token ?? data?.token ?? null;
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
      setAuthToken(token);
    }
    return data;
  } catch (err) {
    const message = err?.response?.data?.detail || err?.response?.data?.message || err.message || "Signup failed";
    throw new Error(message);
  }
}

async function logout() {
  try {
    // attempt server logout but don't block on failure
    try {
      await api.post("/api/v1/auth/logout");
    } catch (_) {
      // ignore
    }
  } finally {
    localStorage.removeItem(TOKEN_KEY);
    setAuthToken(null);
  }
}

async function getCurrentUser() {
  const token = readStoredToken();
  if (!token) return null;
  setAuthToken(token);
  try {
    const res = await api.get("/api/v1/auth/me");
    return res.data ?? res;
  } catch (err) {
    // try alternate endpoint
    try {
      const res2 = await api.get("/api/v1/me");
      return res2.data ?? res2;
    } catch {
      return null;
    }
  }
}

// ensure axios instance has token if stored
const stored = readStoredToken();
if (stored) setAuthToken(stored);

export { login, signup, logout, getCurrentUser, setAuthToken };
export default { login, signup, logout, getCurrentUser, setAuthToken };
