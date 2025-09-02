// filepath: frontend/src/components/Settings.js
import React from 'react';
import { Box, Typography, Switch, FormControlLabel } from '@mui/material';

const Settings = () => {
  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="h5">Settings</Typography>
      <FormControlLabel control={<Switch />} label="Enable Notifications" />
      {/* Add more settings here */}
    </Box>
  );
};

export default Settings;