import React from 'react';
import ReactDOM from 'react-dom/client';
import { Layout } from './components/templates/Layout';

const App = () => (
  <Layout>
    <h1>Quantum Swarm Task MVP</h1>
    <p>System initialized.</p>
  </Layout>
);

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
