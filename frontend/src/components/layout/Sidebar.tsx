import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
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
  useTheme,
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

type NavItem = {
  key: string;
  label: string;
  icon: React.ReactNode;
  path: string;
};

const navItems: NavItem[] = [
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

type SidebarProps = {
  onNavigate?: (path: string) => void;
  mobileOpen?: boolean;
  onClose?: () => void;
};

const Sidebar: React.FC<SidebarProps> = ({
  onNavigate,
  mobileOpen = false,
  onClose,
}) => {
  const theme = useTheme();
  const navigate = useNavigate();
  const location = useLocation();

  const handleClick = (path: string) => {
    if (onNavigate) onNavigate(path);
    else navigate(path);
    if (onClose) onClose();
  };

  const drawerContent = (
    <>
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
        {navItems.map((item) => {
          const selected = location.pathname === item.path;
          return (
            <ListItemButton
              key={item.key}
              selected={selected}
              onClick={() => handleClick(item.path)}
              aria-label={item.label}
              sx={{
                "&.Mui-selected": {
                  backgroundColor: theme.palette.action.selected,
                },
              }}
            >
              <ListItemIcon>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          );
        })}
      </List>
    </>
  );

  return (
    <Box
      component="nav"
      aria-label="main navigation"
      sx={{ width: { md: drawerWidth }, flexShrink: { md: 0 } }}
    >
      {/* Mobile temporary drawer */}
      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={onClose}
        ModalProps={{ keepMounted: true }}
        sx={{
          display: { xs: "block", md: "none" },
          "& .MuiDrawer-paper": { width: drawerWidth, boxSizing: "border-box" },
        }}
      >
        {drawerContent}
      </Drawer>

      {/* Desktop permanent drawer */}
      <Drawer
        variant="permanent"
        sx={{
          display: { xs: "none", md: "block" },
          "& .MuiDrawer-paper": { width: drawerWidth, boxSizing: "border-box" },
        }}
        open
      >
        {drawerContent}
      </Drawer>
    </Box>
  );
};

export default Sidebar;
