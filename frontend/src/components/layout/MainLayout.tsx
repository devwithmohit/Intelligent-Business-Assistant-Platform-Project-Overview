import React, { useState, Suspense } from "react";
import { Outlet, useNavigate } from "react-router-dom";
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
  useTheme,
  Theme,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import Sidebar from "./Sidebar";

const drawerWidth = 260;

const MainLayout: React.FC = () => {
  const theme = useTheme() as Theme;
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);

  const handleDrawerToggle = () => setMobileOpen((v) => !v);

  const handleNavigate = (path: string) => {
    if (!path) return;
    navigate(path);
    setMobileOpen(false);
  };

  const handleProfileOpen = (e: React.MouseEvent<HTMLElement>) =>
    setAnchorEl(e.currentTarget);
  const handleProfileClose = () => setAnchorEl(null);

  return (
    <Box sx={{ display: "flex" }}>
      <CssBaseline />

      <AppBar
        position="fixed"
        sx={{ zIndex: (themeVar) => themeVar.zIndex.drawer + 1 }}
      >
        <Toolbar>
          <IconButton
            color="inherit"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{ mr: 2, display: { md: "none" } }}
            aria-label="open drawer"
            size="large"
          >
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
            <MenuItem onClick={() => { handleProfileClose(); navigate("/profile"); }}>
              Profile
            </MenuItem>
            <MenuItem onClick={() => { handleProfileClose(); navigate("/settings"); }}>
              Settings
            </MenuItem>
            <MenuItem onClick={() => { handleProfileClose(); navigate("/login"); }}>
              Logout
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      {/* Sidebar: passes navigation handler; Sidebar should handle responsive behavior */}
      <Sidebar onNavigate={handleNavigate} />

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: 3,
          width: { xs: "100%", md: `calc(100% - ${drawerWidth}px)` },
          ml: { md: `${drawerWidth}px` },
        }}
      >
        <Toolbar /> {/* spacing for fixed AppBar */}

        <Suspense
          fallback={
            <Box sx={{ display: "flex", justifyContent: "center", p: 4 }}>
              <CircularProgress />
            </Box>
          }
        >
          {/* Route children will render here */}
          <Outlet />
        </Suspense>
      </Box>
    </Box>
  );
};
export default MainLayout;