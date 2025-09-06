import jwt_decode from "jwt-decode";

const TOKEN_KEY = "access_token";

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else removeToken();
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function removeToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function decodeToken(token = getToken()) {
  if (!token) return null;
  try {
    return jwt_decode(token);
  } catch {
    return null;
  }
}

export function isTokenExpired(token = getToken()) {
  const decoded = decodeToken(token);
  if (!decoded) return true;
  const exp = decoded.exp;
  if (typeof exp !== "number") return false;
  return Date.now() >= exp * 1000;
}

export function getUserFromToken(token = getToken()) {
  const decoded = decodeToken(token);
  if (!decoded) return null;
  return decoded.user ?? decoded;
}

export function getAuthHeader(token = getToken()) {
  const t = token ?? getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

export default {
  setToken,
  getToken,
  removeToken,
  decodeToken,
  isTokenExpired,
  getUserFromToken,
  getAuthHeader,
}