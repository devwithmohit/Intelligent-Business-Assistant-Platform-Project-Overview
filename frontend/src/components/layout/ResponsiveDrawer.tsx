import React, { useState } from "react";
import { Box, CssBaseline, Toolbar } from "@mui/material";
import { useNavigate } from "react-router-dom";
import Topbar from "./Topbar";
import Sidebar from "./Sidebar";

type ResponsiveDrawerProps = {
  children?: React.ReactNode;
  drawerWidth?: number;
};

const ResponsiveDrawer: React.FC<ResponsiveDrawerProps> = ({ children, drawerWidth = 260 }) => {
  const [mobileOpen, setMobileOpen] = useState(false);
  const navigate = useNavigate();

  const handleDrawerToggle = () => setMobileOpen((v) => !v);
  const handleNavigate = (path: string) => {
    if (!path) return;
    navigate(path);
    setMobileOpen(false);
  };

  const handleProfile = () => navigate("/profile");
  const handleLogout = () => {
    // simple client-side logout navigation - backend/logout should be called elsewhere
    navigate("/login");
  };

  return (
    <Box sx={{ display: "flex" }}>
      <CssBaseline />
      <Topbar
        onMenuClick={handleDrawerToggle}
        onProfile={handleProfile}
        onLogout={handleLogout}
      />

      <Sidebar mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} onNavigate={handleNavigate} />

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          width: { xs: "100%", md: `calc(100% - ${drawerWidth}px)` },
          ml: { md: `${drawerWidth}px` },
        }}
      >
        <Toolbar />
        {children}
      </Box>
    </Box>
  );
};

export default ResponsiveDrawer;
