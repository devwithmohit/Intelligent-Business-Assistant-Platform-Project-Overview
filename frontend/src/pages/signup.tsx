import React, { useState } from 'react';
import { Box, TextField, Button, Typography, Paper, Alert } from '@mui/material';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import { useNavigate, Link as RouterLink } from 'react-router-dom';
import useAuth from '../hooks/useAuth';
import * as authService from '../services/auth';

const schema = yup.object({
  name: yup.string().required('Name is required'),
  email: yup.string().email('Enter a valid email').required('Email is required'),
  password: yup.string().min(8, 'Minimum 8 characters').required('Password is required'),
  confirm: yup
    .string()
    .oneOf([yup.ref('password')], 'Passwords must match')
    .required('Please confirm your password'),
});

const Signup = () => {
  const navigate = useNavigate();
  const auth = useAuth();
  const [serverError, setServerError] = useState('');
  const [loading, setLoading] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  const onSubmit = async (data) => {
    setServerError('');
    setLoading(true);
    try {
      // prefer context signup if available, fall back to service
      if (auth && typeof auth.signup === 'function') {
        await auth.signup({ name: data.name, email: data.email, password: data.password });
      } else if (authService && typeof authService.signup === 'function') {
        await authService.signup({ name: data.name, email: data.email, password: data.password });
      } else {
        throw new Error('Signup method not implemented');
      }
      navigate('/dashboard');
    } catch (err) {
      setServerError(err?.message || 'Signup failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
      <Paper sx={{ width: 480, p: 4 }}>
        <Typography variant="h5" gutterBottom>
          Create an account
        </Typography>

        {serverError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {serverError}
          </Alert>
        )}

        <form onSubmit={handleSubmit(onSubmit)} noValidate>
          <TextField
            label="Full name"
            fullWidth
            margin="normal"
            {...register('name')}
            error={Boolean(errors.name)}
            helperText={errors.name?.message}
          />

          <TextField
            label="Email"
            type="email"
            fullWidth
            margin="normal"
            {...register('email')}
            error={Boolean(errors.email)}
            helperText={errors.email?.message}
          />

          <TextField
            label="Password"
            type="password"
            fullWidth
            margin="normal"
            {...register('password')}
            error={Boolean(errors.password)}
            helperText={errors.password?.message}
          />

          <TextField
            label="Confirm password"
            type="password"
            fullWidth
            margin="normal"
            {...register('confirm')}
            error={Boolean(errors.confirm)}
            helperText={errors.confirm?.message}
          />

          <Button type="submit" variant="contained" color="primary" fullWidth sx={{ mt: 2 }} disabled={loading}>
            {loading ? 'Creating account...' : 'Sign up'}
          </Button>
        </form>

        <Typography variant="body2" sx={{ mt: 2 }}>
          Already have an account?{' '}
          <RouterLink to="/login" style={{ color: 'inherit', textDecoration: 'underline' }}>
            Log in
          </RouterLink>
        </Typography>
      </Paper>
    </Box>
  );
};

export default Signup;
