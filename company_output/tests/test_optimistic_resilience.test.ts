import { requestQueue } from '../src/services/requestQueue';

// Mock global fetch to simulate network latency and race conditions
global.fetch = jest.fn();

describe('Optimistic UI Resilience', () => {
    beforeEach(() => {
        (fetch as jest.Mock).mockClear();
    });

    test('should maintain state integrity during rapid-fire operations', async () => {
        // Mock delayed response
        (fetch as jest.Mock).mockImplementation(() =>
            new Promise(resolve => setTimeout(() => resolve({ ok: true }), 50))
        );

        // Rapid fire trigger
        const p1 = requestQueue.add({ action: 'add', data: { title: 'Task 1' } });
        const p2 = requestQueue.add({ action: 'add', data: { title: 'Task 2' } });

        await Promise.all([p1, p2]);

        expect(fetch).toHaveBeenCalledTimes(2);
        // The implementation processes sequentially, which is good for state integrity
    });

    test('should trigger error recovery when a request in queue fails', async () => {
        // First request fails
        (fetch as jest.Mock).mockResolvedValueOnce({ ok: false });
        (fetch as jest.Mock).mockResolvedValueOnce({ ok: true });

        // Queue order matters
        await requestQueue.add({ action: 'add', data: { title: 'Task 1' } });
        await requestQueue.add({ action: 'add', data: { title: 'Task 2' } });

        // If the queue logic holds, it should stop on fail, so Task 2 hasn't been sent yet
        expect(fetch).toHaveBeenCalledTimes(1);
    });
});
