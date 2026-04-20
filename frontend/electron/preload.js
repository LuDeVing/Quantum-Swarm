const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAuth', {
  oauthLogin: (provider) => ipcRenderer.invoke('oauth-login', provider),
});
