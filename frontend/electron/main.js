const { app, BrowserWindow, Menu, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');

let mainWindow;

function fixDistPaths() {
  const indexPath = path.join(__dirname, '..', 'dist', 'index.html');
  if (fs.existsSync(indexPath)) {
    let html = fs.readFileSync(indexPath, 'utf-8');
    html = html.replace(/href="\//g, 'href="./');
    html = html.replace(/src="\//g, 'src="./');
    fs.writeFileSync(indexPath, html, 'utf-8');
  }
}

/**
 * Opens an OAuth popup window.
 * The backend should redirect to: {BASE_URL}/auth/callback?token=JWT&user=JSON
 * This function watches all navigation and extracts token + user from the callback URL.
 */
function openOAuthPopup(url) {
  return new Promise((resolve, reject) => {
    const authWindow = new BrowserWindow({
      width: 500,
      height: 700,
      parent: mainWindow,
      modal: true,
      show: true,
      title: 'Sign In',
      backgroundColor: '#1a1a2e',
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
      },
    });

    authWindow.loadURL(url);

    // Watch for the callback redirect containing the token
    const handleNavigation = (navUrl) => {
      try {
        const parsed = new URL(navUrl);
        const token = parsed.searchParams.get('token');
        const userParam = parsed.searchParams.get('user');

        if (token && userParam) {
          const user = JSON.parse(decodeURIComponent(userParam));
          authWindow.close();
          resolve({ token, user });
        }
      } catch (e) {
        // Not the callback URL yet, keep going
      }
    };

    authWindow.webContents.on('will-navigate', (event, navUrl) => {
      handleNavigation(navUrl);
    });

    authWindow.webContents.on('will-redirect', (event, navUrl) => {
      handleNavigation(navUrl);
    });

    authWindow.on('closed', () => {
      reject(new Error('Auth window was closed'));
    });
  });
}

// IPC handler: renderer asks main process to do OAuth
ipcMain.handle('oauth-login', async (event, provider) => {
  // BASE_URL must match what api.js uses
  const BASE_URL = 'http://localhost:3001/api';
  const url = `${BASE_URL}/auth/${provider}/redirect`;
  return await openOAuthPopup(url);
});

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 420,
    height: 780,
    minWidth: 360,
    minHeight: 640,
    title: 'MyApp',
    icon: path.join(__dirname, '..', 'assets', 'icon.png'),
    backgroundColor: '#1a1a2e',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
    autoHideMenuBar: true,
    titleBarStyle: 'default',
    resizable: true,
  });

  const isDev = process.argv.includes('--dev');

  if (isDev) {
    mainWindow.loadURL('http://localhost:8081');
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    fixDistPaths();
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// Remove the default menu bar
Menu.setApplicationMenu(null);

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  app.quit();
});

app.on('activate', () => {
  if (mainWindow === null) {
    createWindow();
  }
});
