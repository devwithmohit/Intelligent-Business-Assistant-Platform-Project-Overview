import React from "react";
import { Box, Typography, Link, useTheme } from "@mui/material";

const Footer: React.FC = () => {
  const theme = useTheme();
  const year = new Date().getFullYear();

  return (
    <Box
      component="footer"
      sx={{
        mt: 4,
        py: 2,
        px: 3,
        borderTop: `1px solid ${theme.palette.divider}`,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        bgcolor: "background.paper",
      }}
    >
      <Typography variant="body2" color="text.secondary">
        © {year} Intelligent Business Assistant
      </Typography>

      <Box sx={{ display: "flex", gap: 2, alignItems: "center" }}>
        <Typography variant="body2" color="text.secondary">
          v0.1.0
        </Typography>
        <Link href="/docs/README.md" underline="hover" variant="body2">
          Docs
        </Link>
        <Link href="/terms" underline="hover" variant="body2">
          Terms
        </Link>
      </Box>
    </Box>
  );
};

export default Footer;
