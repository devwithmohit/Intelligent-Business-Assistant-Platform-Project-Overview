import React from 'react';
import { Box, AppBar, Toolbar, Typography, IconButton, CssBaseline } from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import Sidebar from './Sidebar';
import Dashboard from '../Dashboard/Dashboard';

const MainLayout = () => {
  const handleNavigate = (path) => {
    // placeholder navigation handler — replace with react-router navigation later
    console.log('navigate to', path);
  };

  return (
    <Box sx={{ display: 'flex' }}>
      <CssBaseline />
      <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
        <Toolbar>
          <IconButton color="inherit" edge="start" sx={{ mr: 2 }}>
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" noWrap component="div">
            Intelligent Business Assistant
          </Typography>
        </Toolbar>
      </AppBar>

      <Sidebar onNavigate={handleNavigate} />

      <Box component="main" sx={{ flexGrow: 1, p: 3, ml: `${260}px` }}>
        <Toolbar /> {/* spacing for AppBar */}
        {/* keep using your existing Dashboard component as landing */}
        <Dashboard />
      </Box>
    </Box>
  );
};

export default MainLayout;