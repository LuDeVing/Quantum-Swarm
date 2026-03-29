import { requestQueue } from '../src/services/requestQueue';

// Mock global fetch
global.fetch = jest.fn();

describe('RequestQueue Integration Tests', () => {
  beforeEach(() => {
    (fetch as jest.Mock).mockClear();
  });

  test('should process items in sequential order', async () => {
    (fetch as jest.Mock).mockResolvedValue({ ok: true });

    await requestQueue.add({ action: 'add', data: { title: 'Task 1' } });
    await requestQueue.add({ action: 'add', data: { title: 'Task 2' } });

    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenNthCalledWith(1, '/api/tasks', expect.objectContaining({ method: 'POST', body: JSON.stringify({ title: 'Task 1' }) }));
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/tasks', expect.objectContaining({ method: 'POST', body: JSON.stringify({ title: 'Task 2' }) }));
  });

  test('should stop processing and leave item in queue on backend failure', async () => {
    (fetch as jest.Mock).mockResolvedValueOnce({ ok: false }); // First fails

    try {
      await requestQueue.add({ action: 'add', data: { title: 'Bad Task' } });
    } catch (e) {
      // expected
    }

    // Since we don't have direct access to private queue, we verify by calling another action
    (fetch as jest.Mock).mockResolvedValueOnce({ ok: true });
    await requestQueue.add({ action: 'add', data: { title: 'Good Task' } });

    // Expect the first failed one to block the queue, so the Good Task is still waiting behind it?
    // Looking at the implementation, it breaks out of the loop and leaves the queue populated.
    expect(fetch).toHaveBeenCalledTimes(1); 
  });
});
