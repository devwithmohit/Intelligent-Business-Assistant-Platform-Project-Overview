import React, { useState } from "react";
import { Box, Paper, Typography, TextField, Button, Alert } from "@mui/material";
import { useForm } from "react-hook-form";
import { yupResolver } from "@hookform/resolvers/yup";
import * as yup from "yup";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import useAuth from "../hooks/useAuth";
import * as authService from "../services/auth";

const schema = yup.object({
  email: yup.string().email("Enter a valid email").required("Email is required"),
  password: yup.string().required("Password is required"),
});

const Login = () => {
  const navigate = useNavigate();
  const auth = useAuth();
  const [serverError, setServerError] = useState("");
  const [loading, setLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  const onSubmit = async (data) => {
    setServerError("");
    setLoading(true);
    try {
      if (auth && typeof auth.login === "function") {
        await auth.login({ email: data.email, password: data.password });
      } else if (authService && typeof authService.login === "function") {
        await authService.login({ email: data.email, password: data.password });
      } else {
        throw new Error("Login method not implemented");
      }
      navigate("/dashboard");
    } catch (err) {
      setServerError(err?.message || "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ display: "flex", justifyContent: "center", mt: 8 }}>
      <Paper sx={{ width: 440, p: 4 }}>
        <Typography variant="h5" gutterBottom>
          Sign in
        </Typography>

        {serverError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {serverError}
          </Alert>
        )}

        <form onSubmit={handleSubmit(onSubmit)} noValidate>
          <TextField
            label="Email"
            type="email"
            fullWidth
            margin="normal"
            {...register("email")}
            error={Boolean(errors.email)}
            helperText={errors.email?.message}
          />

          <TextField
            label="Password"
            type="password"
            fullWidth
            margin="normal"
            {...register("password")}
            error={Boolean(errors.password)}
            helperText={errors.password?.message}
          />

          <Button type="submit" variant="contained" color="primary" fullWidth sx={{ mt: 2 }} disabled={loading}>
            {loading ? "Signing in..." : "Sign in"}
          </Button>
        </form>

        <Typography variant="body2" sx={{ mt: 2 }}>
          Don't have an account?{" "}
          <RouterLink to="/signup" style={{ color: "inherit", textDecoration: "underline" }}>
            Sign up
          </RouterLink>
        </Typography>
      </Paper>
    </Box>
  );
};

export default Login;
