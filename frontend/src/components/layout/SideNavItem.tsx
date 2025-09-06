import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { ListItemButton, ListItemIcon, ListItemText, Tooltip, useTheme } from "@mui/material";

type SideNavItemProps = {
  to: string;
  label: string;
  icon: React.ReactNode;
  onClick?: () => void;
  exact?: boolean;
};

const SideNavItem: React.FC<SideNavItemProps> = ({ to, label, icon, onClick, exact = false }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();

  const isActive = exact ? location.pathname === to : location.pathname.startsWith(to);

  const handleClick = () => {
    if (onClick) onClick();
    navigate(to);
  };

  return (
    <Tooltip title={label} placement="right" enterDelay={300}>
      <ListItemButton
        selected={isActive}
        onClick={handleClick}
        aria-current={isActive ? "page" : undefined}
        sx={{
          "&.Mui-selected": {
            backgroundColor: theme.palette.action.selected,
          },
        }}
      >
        <ListItemIcon>{icon}</ListItemIcon>
        <ListItemText primary={label} />
      </ListItemButton>
    </Tooltip>
  );
};

export default SideNavItem;
