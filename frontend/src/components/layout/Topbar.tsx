import React, { useState } from "react";
import {
  AppBar,
  Toolbar,
  IconButton,
  Typography,
  InputBase,
  Badge,
  Avatar,
  Menu,
  MenuItem,
  Box,
  useTheme,
  alpha,
  styled,
} from "@mui/material";
import MenuIcon from "@mui/icons-material/Menu";
import SearchIcon from "@mui/icons-material/Search";
import NotificationsIcon from "@mui/icons-material/Notifications";
import MoreVertIcon from "@mui/icons-material/MoreVert";

interface TopbarProps {
  title?: string;
  onMenuClick?: () => void;
  onProfile?: () => void;
  onLogout?: () => void;
  notificationsCount?: number;
}

const Search = styled("div")(({ theme }) => ({
  position: "relative",
  borderRadius: theme.shape.borderRadius,
  backgroundColor: alpha(theme.palette.common.white, 0.06),
  "&:hover": { backgroundColor: alpha(theme.palette.common.white, 0.09) },
  marginRight: theme.spacing(2),
  marginLeft: 0,
  width: "100%",
  [theme.breakpoints.up("sm")]: { width: "auto" },
}));

const SearchIconWrapper = styled("div")(({ theme }) => ({
  padding: theme.spacing(0, 1),
  height: "100%",
  position: "absolute",
  pointerEvents: "none",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
}));

const StyledInputBase = styled(InputBase)(({ theme }) => ({
  color: "inherit",
  "& .MuiInputBase-input": {
    padding: theme.spacing(1, 1, 1, 0),
    // vertical padding + font size from searchIcon
    paddingLeft: `calc(1em + ${theme.spacing(3)})`,
    transition: theme.transitions.create("width"),
    width: "12ch",
    [theme.breakpoints.up("md")]: { width: "20ch" },
  },
}));

const Topbar: React.FC<TopbarProps> = ({
  title = "Intelligent Business Assistant",
  onMenuClick,
  onProfile,
  onLogout,
  notificationsCount = 0,
}) => {
  const theme = useTheme();
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const [mobileAnchor, setMobileAnchor] = useState<HTMLElement | null>(null);

  const handleProfileOpen = (e: React.MouseEvent<HTMLElement>) => setAnchorEl(e.currentTarget);
  const handleProfileClose = () => setAnchorEl(null);

  const handleMobileOpen = (e: React.MouseEvent<HTMLElement>) => setMobileAnchor(e.currentTarget);
  const handleMobileClose = () => setMobileAnchor(null);

  const handleLogout = () => {
    handleProfileClose();
    if (onLogout) onLogout();
  };

  return (
    <AppBar position="fixed" sx={{ zIndex: (t) => t.zIndex.drawer + 1 }}>
      <Toolbar>
        <IconButton
          color="inherit"
          edge="start"
          onClick={onMenuClick}
          sx={{ mr: 2, display: { md: "none" } }}
          aria-label="open drawer"
          size="large"
        >
          <MenuIcon />
        </IconButton>

        <Typography variant="h6" noWrap component="div" sx={{ flexShrink: 0 }}>
          {title}
        </Typography>

        <Box sx={{ flexGrow: 1 }} />

        <Search sx={{ display: { xs: "none", sm: "flex" }, mr: 1 }}>
          <SearchIconWrapper>
            <SearchIcon />
          </SearchIconWrapper>
          <StyledInputBase placeholder="Search…" inputProps={{ "aria-label": "search" }} />
        </Search>

        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <IconButton color="inherit" aria-label="notifications" size="large">
            <Badge badgeContent={notificationsCount} color="error">
              <NotificationsIcon />
            </Badge>
          </IconButton>

          <IconButton
            color="inherit"
            onClick={handleProfileOpen}
            aria-label="account"
            size="large"
            sx={{ ml: 0.5 }}
          >
            <Avatar sx={{ width: 32, height: 32 }}>IU</Avatar>
          </IconButton>

          <IconButton
            color="inherit"
            sx={{ display: { md: "none" } }}
            onClick={handleMobileOpen}
            aria-label="more"
            size="large"
          >
            <MoreVertIcon />
          </IconButton>
        </Box>

        {/* Profile menu */}
        <Menu
          anchorEl={anchorEl}
          open={Boolean(anchorEl)}
          onClose={handleProfileClose}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          transformOrigin={{ vertical: "top", horizontal: "right" }}
        >
          <MenuItem
            onClick={() => {
              handleProfileClose();
              if (onProfile) onProfile();
            }}
          >
            Profile
          </MenuItem>
          <MenuItem onClick={() => { handleProfileClose(); }}>
            Settings
          </MenuItem>
          <MenuItem onClick={handleLogout}>Logout</MenuItem>
        </Menu>

        {/* Mobile menu */}
        <Menu
          anchorEl={mobileAnchor}
          open={Boolean(mobileAnchor)}
          onClose={handleMobileClose}
          anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
          transformOrigin={{ vertical: "top", horizontal: "right" }}
        >
          <MenuItem>
            <IconButton color="inherit" aria-label="notifications" size="large">
              <Badge badgeContent={notificationsCount} color="error">
                <NotificationsIcon />
              </Badge>
            </IconButton>
            <Typography sx={{ ml: 1 }}>Notifications</Typography>
          </MenuItem>
          <MenuItem
            onClick={() => {
              handleMobileClose();
              handleProfileOpen as any;
            }}
          >
            <Typography>Account</Typography>
          </MenuItem>
        </Menu>
      </Toolbar>
    </AppBar>
  );
};

export default Topbar;
