import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { login, ApiError } from '../api/auth';
import '../styles/login.css';

export default function LoginPage() {
  const [secret, setSecret] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const result = await login(secret);
      if (result.ok) {
        // The auth status query is cached for 5 minutes (see main.tsx);
        // without invalidating it here, ProtectedRoute keeps reading the
        // stale pre-login "not authenticated" result and bounces back to
        // the login form even though the cookie is now set.
        await queryClient.invalidateQueries({ queryKey: ['auth', 'status'] });
        navigate('/feed', { replace: true });
      }
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        setError('Invalid secret');
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Login failed');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="login-container">
      <div className="login-card">
        <h1>Music Badger</h1>
        <form onSubmit={handleSubmit}>
          <input
            type="password"
            placeholder="Enter secret"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            disabled={isLoading}
            autoFocus
          />
          <button type="submit" disabled={isLoading}>
            {isLoading ? 'Logging in...' : 'Login'}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
