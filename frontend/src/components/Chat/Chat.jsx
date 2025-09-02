// filepath: frontend/src/components/Chat.js
import React from 'react';
import { Box, TextField, Button, List, ListItem, Typography } from '@mui/material';

const Chat = () => {
  return (
    <Box sx={{ p: 2 }}>
      <Typography variant="h5">Chat with AI Agents</Typography>
      <List>
        {/* Render chat messages here */}
      </List>
      <TextField fullWidth label="Type your message" variant="outlined" />
      <Button variant="contained" sx={{ mt: 1 }}>Send</Button>
    </Box>
  );
};

export default Chat;