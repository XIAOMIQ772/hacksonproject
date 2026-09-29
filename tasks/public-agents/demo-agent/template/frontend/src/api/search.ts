import apiClient from './index';

export function searchTickets(params: { from?: string; to?: string; date?: string }) {
  return apiClient.get('/search/tickets', { params });
}

export function fetchTrainDetail(trainId: string, date: string) {
  return apiClient.get(`/search/trains/${trainId}`, { params: { date } });
}
