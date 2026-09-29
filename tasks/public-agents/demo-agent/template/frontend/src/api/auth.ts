import apiClient from './index';

export function registerUser(payload: {
  username: string;
  email: string;
  password: string;
  confirmPassword: string;
}) {
  return apiClient.post('/auth/register', payload);
}

export function loginUser(payload: { account: string; password: string }) {
  return apiClient.post('/auth/login', payload);
}

export function fetchCurrentUser() {
  return apiClient.get('/auth/me');
}

export function logoutUser() {
  return apiClient.post('/auth/logout');
}
