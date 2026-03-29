type Request = {
  action: 'add' | 'update' | 'delete';
  data: any;
};

class RequestQueue {
  private queue: Request[] = [];
  private isProcessing = false;

  async add(req: Request) {
    this.queue.push(req);
    return this.process();
  }

  private async process() {
    if (this.isProcessing || this.queue.length === 0) return;
    this.isProcessing = true;

    while (this.queue.length > 0) {
      const req = this.queue[0];
      try {
        await this.syncWithBackend(req);
        this.queue.shift();
      } catch (error) {
        console.error('Request failed, retrying later...', error);
        break; // Stop and wait for retry or next trigger
      }
    }
    this.isProcessing = false;
  }

  private async syncWithBackend(req: Request) {
    // This connects to the backend API defined by other devs
    const response = await fetch('/api/tasks', {
      method: req.action === 'add' ? 'POST' : req.action === 'update' ? 'PUT' : 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.data),
    });
    if (!response.ok) throw new Error('Sync failed');
  }
}

export const requestQueue = new RequestQueue();
