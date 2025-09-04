import React, { useState } from "react";
import {
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Toolbar,
  Box,
  Typography,
  Divider,
} from "@mui/material";
import DashboardIcon from "@mui/icons-material/Dashboard";
import ChatIcon from "@mui/icons-material/Chat";
import AnalyticsIcon from "@mui/icons-material/Analytics";
import StorageIcon from "@mui/icons-material/Storage";
import InventoryIcon from "@mui/icons-material/Inventory";
import IntegrationInstructionsIcon from "@mui/icons-material/IntegrationInstructions";
import SettingsIcon from "@mui/icons-material/Settings";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";

const drawerWidth = 260;

const navItems = [
  {
    key: "dashboard",
    label: "Dashboard",
    icon: <DashboardIcon />,
    path: "/dashboard",
  },
  { key: "chat", label: "Chat", icon: <ChatIcon />, path: "/chat" },
  {
    key: "agents",
    label: "Agent Status",
    icon: <AnalyticsIcon />,
    path: "/agents",
  },
  {
    key: "analytics",
    label: "Analytics",
    icon: <StorageIcon />,
    path: "/analytics",
  },
  {
    key: "tasks",
    label: "Task Queue",
    icon: <InventoryIcon />,
    path: "/tasks",
  },
  {
    key: "integrations",
    label: "Integrations",
    icon: <IntegrationInstructionsIcon />,
    path: "/integrations",
  },
  {
    key: "settings",
    label: "Settings",
    icon: <SettingsIcon />,
    path: "/settings",
  },
  { key: "help", label: "Help", icon: <HelpOutlineIcon />, path: "/help" },
];

const Sidebar = ({ onNavigate = () => {} }) => {
  const [selected, setSelected] = useState("dashboard");

  const handleClick = (item) => {
    setSelected(item.key);
    try {
      onNavigate(item.path || item.key);
    } catch {
      // noop
    }
  };

  return (
    <Box component="nav" aria-label="main navigation">
      <Drawer
        variant="permanent"
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          "& .MuiDrawer-paper": {
            width: drawerWidth,
            boxSizing: "border-box",
          },
        }}
      >
        <Toolbar>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <img src="/vite.svg" alt="logo" style={{ height: 32 }} />
            <Typography variant="h6" noWrap>
              Intelligent Assistant
            </Typography>
          </Box>
        </Toolbar>

        <Divider />

        <List>
          {navItems.map((item) => (
            <ListItemButton
              key={item.key}
              selected={selected === item.key}
              onClick={() => handleClick(item)}
              aria-label={item.label}
            >
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>
    </Box>
  );
};

export default Sidebar;
