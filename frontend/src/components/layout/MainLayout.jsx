import React, { useState, Suspense } from "react";
import {
  Box,
  AppBar,
  Toolbar,
  Typography,
  IconButton,
  CssBaseline,
  Avatar,
  Menu,
  MenuItem,
  CircularProgress,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import Sidebar from "./Sidebar";
import Dashboard from "../Dashboard/Dashboard";
import Chat from "../Chat/Chat";
import Analytics from "../Analytics/Analytics";
import Settings from "../Settings/Settings";
// import AgentStatus when available: import AgentStatus from '../AgentStatus/AgentStatus';

const MainLayout = () => {
  const [route, setRoute] = useState("/dashboard");
  const [anchorEl, setAnchorEl] = useState(null);

  const handleNavigate = (path) => {
    setRoute(path || "/dashboard");
  };

  const handleProfileOpen = (e) => setAnchorEl(e.currentTarget);
  const handleProfileClose = () => setAnchorEl(null);

  const renderContent = () => {
    switch (route) {
      case "/chat":
        return <Chat />;
      case "/analytics":
        return <Analytics />;
      case "/settings":
        return <Settings />;
      case "/agents":
        // return <AgentStatus />; // uncomment when AgentStatus component exists
        return (
          <Box sx={{ p: 2 }}>
            <Typography variant="h5">Agent Status</Typography>
            <Typography color="text.secondary">
              AgentStatus component not yet implemented.
            </Typography>
          </Box>
        );
      case "/dashboard":
      default:
        return <Dashboard />;
    }
  };

  return (
    <Box sx={{ display: "flex" }}>
      <CssBaseline />
      <AppBar
        position="fixed"
        sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}
      >
        <Toolbar>
          <IconButton color="inherit" edge="start" sx={{ mr: 2 }}>
            <MenuIcon />
          </IconButton>

          <Typography variant="h6" noWrap component="div" sx={{ flexGrow: 1 }}>
            Intelligent Business Assistant
          </Typography>

          <IconButton
            color="inherit"
            onClick={handleProfileOpen}
            size="small"
            aria-label="profile"
          >
            <Avatar sx={{ width: 32, height: 32 }}>IU</Avatar>
          </IconButton>

          <Menu
            anchorEl={anchorEl}
            open={Boolean(anchorEl)}
            onClose={handleProfileClose}
            anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
            transformOrigin={{ vertical: "top", horizontal: "right" }}
          >
            <MenuItem onClick={handleProfileClose}>Profile</MenuItem>
            <MenuItem onClick={handleProfileClose}>Settings</MenuItem>
            <MenuItem onClick={handleProfileClose}>Logout</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      <Sidebar onNavigate={handleNavigate} />

      <Box component="main" sx={{ flexGrow: 1, p: 3, ml: `${260}px` }}>
        <Toolbar /> {/* spacing for AppBar */}
        <Suspense
          fallback={
            <Box sx={{ display: "flex", justifyContent: "center", p: 4 }}>
              <CircularProgress />
            </Box>
          }
        >
          {renderContent()}
        </Suspense>
      </Box>
    </Box>
  );
};

export default MainLayout;
