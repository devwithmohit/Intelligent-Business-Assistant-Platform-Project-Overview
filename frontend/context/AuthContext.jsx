import React, { createContext, useState, useEffect, useCallback } from "react";
import jwt_decode from "jwt-decode";
import * as authService from "../src/services/auth";

export const AuthContext = createContext({
  user: null,
  loading: true,
  login: async () => {},
  signup: async () => {},
  logout: () => {},
});

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const setSession = useCallback((token) => {
    if (token) {
      localStorage.setItem("access_token", token);
    } else {
      localStorage.removeItem("access_token");
    }
    // If your api client needs an auth header helper, call it here.
    // e.g. api.setAuthToken(token);
  }, []);

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      try {
        const token = localStorage.getItem("access_token");
        if (token) {
          try {
            const decoded = jwt_decode(token);
            // decoded may contain user info or only claims; adapt as needed
            setUser(decoded.user ?? decoded);
          } catch {
            // fallback: try to fetch current user if backend provides endpoint
            if (authService.getCurrentUser) {
              const me = await authService.getCurrentUser();
              setUser(me);
            } else {
              setUser(null);
            }
          }
        } else {
          setUser(null);
        }
      } catch (err) {
        console.error("Auth init error:", err);
        setUser(null);
      } finally {
        setLoading(false);
      }
    };

    init();
  }, []);

  const login = async (creds) => {
    setLoading(true);
    try {
      const res = await authService.login(creds);
      // handle different response shapes
      const token = res?.access_token ?? res?.token ?? res;
      if (!token) throw new Error("No token returned from login");
      setSession(token);

      // set user from response if available, otherwise decode token
      if (res?.user) setUser(res.user);
      else {
        try {
          const decoded = jwt_decode(token);
          setUser(decoded.user ?? decoded);
        } catch {
          setUser(null);
        }
      }

      return res;
    } finally {
      setLoading(false);
    }
  };

  const signup = async (payload) => {
    setLoading(true);
    try {
      const res = await authService.signup(payload);
      const token = res?.access_token ?? res?.token ?? res;
      if (token) {
        setSession(token);
        if (res?.user) setUser(res.user);
        else {
          try {
            const decoded = jwt_decode(token);
            setUser(decoded.user ?? decoded);
          } catch {
            setUser(null);
          }
        }
      }
      return res;
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    setSession(null);
    setUser(null);
    if (authService.logout) authService.logout().catch(() => {});
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export default AuthContext;