
import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "../context/AuthContext";
import ProtectedRoute from "../components/auth/ProtectedRoute";

import MainLayout from "../components/layout/MainLayout";
import Login from "../pages/Login";
import Signup from "../pages/signup";
import Dashboard from "../components/Dashboard/Dashboard";
import Chat from "../components/Chat/Chat";
import Analytics from "../components/Analytics/Analytics";
import Settings from "../components/Settings/Settings";
import AgentStatus from "../components/AgentStatus/AgentStatus";

const AppRoutes: React.FC = () => {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />

          {/* Protected app routes with MainLayout as shell */}
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<MainLayout />}>
              <Route index element={<Navigate to="dashboard" replace />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="chat" element={<Chat />} />
              <Route path="analytics" element={<Analytics />} />
              <Route path="agents" element={<AgentStatus />} />
              <Route path="settings" element={<Settings />} />
              {/* additional protected routes go here */}
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
          </Route>

          {/* Fallback for any unmatched route */}
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
};

export default AppRoutes;
