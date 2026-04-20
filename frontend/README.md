# MyApp — Mobile Application

A modern React Native (Expo) mobile application featuring an interactive animated loading screen, user authentication (register & login), a drawer sidebar navigation, a project management list, a direct chat with the CEO, and a full options/settings screen.

---

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Project Structure](#project-structure)
4. [Screen-by-Screen Breakdown](#screen-by-screen-breakdown)
5. [Tech Stack & Dependencies](#tech-stack--dependencies)
6. [Getting Started](#getting-started)
7. [How It Works](#how-it-works)
8. [Customization](#customization)

---

## Overview

MyApp is a cross-platform mobile application built with **React Native** and **Expo**. It is designed as a company-internal tool where employees can manage projects and communicate directly with the CEO. The app includes a polished dark-themed UI with smooth animations throughout.

### App Flow

```
Loading Screen (animated)
       │
       ▼
┌──────────────┐     ┌─────────────────┐
│  Login Screen │◄───►│ Register Screen  │
└──────┬───────┘     └─────────────────┘
       │ (on successful auth)
       ▼
┌──────────────────────────────────────────┐
│              Main App (Drawer)           │
│  ┌────────────┐  ┌────────────────────┐  │
│  │  Sidebar   │  │   Content Area     │  │
│  │            │  │                    │  │
│  │ ┌────────┐ │  │  • Projects List   │  │
│  │ │ Logo & │ │  │  • Chat with CEO   │  │
│  │ │  Name  │ │  │  • Options         │  │
│  │ ├────────┤ │  │                    │  │
│  │ │Projects│ │  │                    │  │
│  │ │  Chat  │ │  │                    │  │
│  │ ├────────┤ │  │                    │  │
│  │ │Options │ │  │                    │  │
│  │ │User Row│ │  │                    │  │
│  │ └────────┘ │  └────────────────────┘  │
│  └────────────┘                          │
└──────────────────────────────────────────┘
```

---

## Features

### Interactive Loading Screen
- **Animated logo** with spring bounce effect
- **Spinning ring** that rotates continuously behind the logo
- **Pulsing dots** ("Loading...") with sequential fade animation
- **Progress bar** that fills smoothly using a bezier curve
- **Floating particles** — 4 glowing dots that float upward and fade in/out at different positions
- Automatically transitions to the auth/main screen when all animations complete (~3.5 seconds)

### User Authentication
- **Register** — create an account with full name, email, password, and password confirmation
  - Email format validation (regex)
  - Minimum 6-character password requirement
  - Password match confirmation
  - Duplicate email detection
- **Login** — sign in with email and password
  - Credential verification against stored accounts
  - Show/hide password toggle
- Accounts are persisted locally via AsyncStorage
- Session persistence — returning users are automatically logged in

### Sidebar (Drawer Navigation)
- **Top section**: Company logo (styled "M" circle) + app name + company tagline
- **Middle section**: Two main navigation buttons
  - **Projects** — folder icon, navigates to the projects list
  - **Chat with CEO** — chat icon, navigates to the CEO chat
- **Bottom section**:
  - **Options** button — settings gear icon
  - **User info row** — avatar with initials, name, email, and a quick logout button
- Active route is highlighted with a red accent color and left border indicator
- Icons switch between outline and filled variants based on active state

### Projects Screen
- Displays a scrollable list of projects, each showing:
  - Project name and creation date
  - Color-coded status badge (Planning = red, In Progress = yellow, Completed = green)
  - Folder icon
- **Add project** — floating action button (FAB) in the bottom-right opens a modal dialog
  - Enter project name, tap "Create" to add as a new "Planning" project
- **Delete project** — long-press any project card to trigger a confirmation dialog
- **Empty state** — shows a friendly message with icon when no projects exist
- Comes with 3 sample projects pre-loaded

### Chat with CEO Screen
- Chat-style messaging interface simulating a conversation with the CEO (Alex Morgan)
- **Chat header** — CEO avatar, name, title, and green "Online" status indicator
- **Message bubbles** — CEO messages appear on the left (dark), user messages on the right (red)
- **Timestamps** — each message displays the time it was sent
- **Auto-reply** — after the user sends a message, the CEO responds automatically (~1.2 second delay) with a random contextual reply from a pool of 8 responses
- **Auto-scroll** — chat scrolls to the bottom when new messages arrive
- **Input bar** — multiline text input with a send button that disables when empty
- Starts with 2 welcome messages from the CEO

### Options / Settings Screen
- **Profile section** — user avatar (initial), full name, and email
- **Preferences**:
  - Notifications toggle (switch)
  - Dark Mode toggle (switch)
- **General settings**:
  - Edit Profile (coming soon placeholder)
  - Change Password (coming soon placeholder)
  - Help & Support (displays support email)
  - About (displays app version and copyright)
- **Account section**:
  - Clear All Data — deletes all stored accounts and data (with confirmation)
- **Log Out button** — signs out with confirmation dialog, returns to login screen

---

## Project Structure

```
MyApp/
├── App.js                              # App entry point — manages loading, auth, and navigation state
├── app.json                            # Expo configuration (app name, icons, splash)
├── babel.config.js                     # Babel config with react-native-reanimated plugin
├── package.json                        # Dependencies and scripts
├── index.js                            # Expo entry registration
│
├── assets/                             # App icons and splash image assets
│   ├── adaptive-icon.png
│   ├── favicon.png
│   ├── icon.png
│   └── splash-icon.png
│
└── src/
    ├── screens/
    │   ├── LoadingScreen.js            # Animated loading/splash screen
    │   ├── LoginScreen.js              # User login form
    │   ├── RegisterScreen.js           # User registration form
    │   ├── ProjectsScreen.js           # Project list with CRUD operations
    │   ├── ChatScreen.js               # CEO chat messaging interface
    │   └── OptionsScreen.js            # Settings and profile screen
    │
    ├── navigation/
    │   ├── AuthNavigator.js            # Stack navigator for Login ↔ Register
    │   └── AppNavigator.js             # Drawer navigator for main app screens
    │
    └── components/
        └── CustomDrawer.js             # Custom sidebar drawer component
```

---

## Screen-by-Screen Breakdown

### 1. LoadingScreen.js

The first screen users see. Runs a choreographed animation sequence:

| Animation           | Type           | Duration | Description                                                |
|---------------------|----------------|----------|------------------------------------------------------------|
| Logo bounce         | Spring         | ~800ms   | Logo scales from 0 to 1 with a spring bounce effect        |
| Logo fade-in        | Timing         | 800ms    | Logo opacity goes from 0 to 1                              |
| Spinning ring       | Loop (timing)  | 2000ms/rev | Continuous rotation behind the logo — red/blue gradient ring |
| Text fade-in        | Timing         | 600ms    | "MyApp" and "Loading..." text fades in                     |
| Pulsing dots        | Loop (sequence)| 1800ms   | Three dots pulse sequentially (0.3 → 1.0 opacity)         |
| Progress bar        | Timing (bezier)| 2000ms   | Bar fills from 0% to 100% width                           |
| Floating particles  | Loop (parallel)| 2000ms   | 4 particles float upward while fading in and out           |

When the progress bar completes, `onFinish()` is called to transition to the next screen.

### 2. LoginScreen.js

- Two input fields: **Email** (email keyboard) and **Password** (secure entry)
- Password visibility toggle button (eye icon)
- "Sign In" button validates inputs, checks credentials against AsyncStorage
- "Don't have an account? Sign Up" link navigates to RegisterScreen
- On success, calls `onLogin(user)` which updates App.js state

### 3. RegisterScreen.js

- Four input fields: **Full Name**, **Email**, **Password**, **Confirm Password**
- Validation rules:
  - All fields required
  - Valid email format (`/^[^\s@]+@[^\s@]+\.[^\s@]+$/`)
  - Password ≥ 6 characters
  - Passwords must match
  - Email must not already exist
- New user is saved to AsyncStorage `users` array
- On success, auto-logs in and navigates to main app

### 4. ProjectsScreen.js

- **FlatList** renders project cards
- Each card has: folder icon, project name, date, and a status badge
- Status colors: Planning (#e94560 red), In Progress (#ffc107 amber), Completed (#4ecca3 green)
- **FAB (+)** opens a modal with a text input to create new projects (default status: "Planning")
- **Long press** on a card shows a delete confirmation alert
- **Empty state** component shown when the list is empty

### 5. ChatScreen.js

- **FlatList** renders message bubbles
- CEO messages: left-aligned, dark background, shows avatar + sender name
- User messages: right-aligned, red background
- **CEO auto-reply**: after user sends a message, a random reply is generated after a 1.2s delay
- **Input bar**: multiline TextInput (max 500 chars) + round send button
- The `FlatList` auto-scrolls to the end when new messages are added via `onContentSizeChange`

### 6. OptionsScreen.js

- **ScrollView** with sections
- Profile section displays user avatar (first letter of name), name, and email
- Settings rows use a reusable `SettingRow` component with icon + label + right widget
- Toggle switches for Notifications and Dark Mode (local state only)
- "Coming soon" alerts for Edit Profile and Change Password
- Log Out clears `currentUser` from AsyncStorage and resets app state
- Clear All Data runs `AsyncStorage.clear()` and logs out

### 7. CustomDrawer.js

- Custom drawer content component passed to `createDrawerNavigator`
- Reads `state.routes[state.index].name` to highlight the active route
- Menu items defined as an array for easy extension
- Active items get: red background tint, red text, red left border indicator, filled icon
- Bottom section separated by a divider line

---

## Tech Stack & Dependencies

| Package                                      | Version  | Purpose                                           |
|----------------------------------------------|----------|---------------------------------------------------|
| `expo`                                       | ~54.0    | Development platform and build toolchain          |
| `react`                                      | 19.1.0   | UI component library                              |
| `react-native`                               | 0.81.5   | Native mobile rendering engine                    |
| `@react-navigation/native`                   | ^7.2     | Navigation container and routing core             |
| `@react-navigation/drawer`                   | ^7.9     | Drawer/sidebar navigation                         |
| `@react-navigation/native-stack`             | ^7.14    | Stack navigation for auth screens                 |
| `react-native-gesture-handler`               | ~2.28    | Touch gesture system (required by drawer)         |
| `react-native-reanimated`                    | ~4.1     | High-performance animations (required by drawer)  |
| `react-native-screens`                       | ~4.16    | Native screen optimization                        |
| `react-native-safe-area-context`             | ~5.6     | Safe area insets for notches/status bars           |
| `@react-native-async-storage/async-storage`  | 2.2.0    | Local key-value storage for auth persistence      |
| `@expo/vector-icons`                         | ^15.1    | Icon library (Ionicons used throughout)            |
| `expo-font`                                  | ~14.0    | Font loading (required by vector icons)            |
| `expo-status-bar`                            | ~3.0     | Status bar styling                                |

---

## Getting Started

### Prerequisites

- **Node.js** v20+ or v22+ (recommended)
- **npm** (comes with Node.js)
- **Expo Go** app installed on your phone ([iOS](https://apps.apple.com/app/expo-go/id982107779) / [Android](https://play.google.com/store/apps/details?id=host.exp.exponent))

### Installation

```bash
# Navigate to the project folder
cd MyApp

# Install dependencies (already done, but run again if needed)
npm install

# Start the development server
npx expo start
```

### Running the App

After running `npx expo start`, you'll see a QR code in the terminal:

- **Android**: Open the Expo Go app → tap "Scan QR code" → scan the code
- **iOS**: Open the Camera app → point at the QR code → tap the Expo notification
- **Web** (preview): Press `w` in the terminal to open in a browser
- **Android Emulator**: Press `a` in the terminal (requires Android Studio)
- **iOS Simulator**: Press `i` in the terminal (requires Xcode, macOS only)

---

## How It Works

### Authentication Flow

```
App.js boots
    │
    ├─ Checks AsyncStorage for "currentUser"
    │   ├─ Found → sets user state → shows AppNavigator (drawer)
    │   └─ Not found → user = null → shows AuthNavigator (login/register)
    │
    ├─ LoadingScreen plays animations (~3.5s)
    │   └─ onFinish → isLoading = false → renders auth or app
    │
    ├─ Login: validates credentials against "users" array in AsyncStorage
    │   └─ Match → stores "currentUser" → onLogin(user) → App re-renders with drawer
    │
    ├─ Register: validates inputs → appends to "users" array → stores "currentUser"
    │   └─ onLogin(user) → App re-renders with drawer
    │
    └─ Logout: removes "currentUser" from AsyncStorage
        └─ setUser(null) → App re-renders with auth screens
```

### Data Storage

All data is stored locally on the device using AsyncStorage:

| Key             | Type     | Description                              |
|-----------------|----------|------------------------------------------|
| `users`         | JSON array | All registered user accounts `[{id, name, email, password}]` |
| `currentUser`   | JSON object | Currently logged-in user `{id, name, email, password}` |

> **Note**: This is a demo app. In production, passwords should be hashed and stored on a secure backend server, not in local storage.

### Navigation Architecture

```
NavigationContainer (dark theme)
├── AuthNavigator (NativeStackNavigator) — when user = null
│   ├── Login Screen
│   └── Register Screen
│
└── AppNavigator (DrawerNavigator) — when user exists
    ├── Projects Screen
    ├── Chat Screen
    └── Options Screen (receives user + onLogout as props)
```

### Theme

The app uses a consistent dark color palette:

| Color       | Hex       | Usage                                    |
|-------------|-----------|------------------------------------------|
| Dark Navy   | `#1a1a2e` | Screen backgrounds                       |
| Deep Blue   | `#16213e` | Cards, inputs, drawer background         |
| Royal Blue  | `#0f3460` | Borders, dividers                        |
| Crimson Red | `#e94560` | Primary accent, buttons, highlights      |
| Mint Green  | `#4ecca3` | Success states, online indicators        |
| Amber       | `#ffc107` | In-progress status                       |

---

## Customization

### Change Company Name & Logo

Edit [src/components/CustomDrawer.js](src/components/CustomDrawer.js):
```js
// Line 30-31
<Text style={styles.appName}>YourCompany</Text>
<Text style={styles.companyTag}>Your Tagline</Text>
```

Edit the logo letter in the same file and in [src/screens/LoadingScreen.js](src/screens/LoadingScreen.js).

### Change CEO Name

Edit [src/screens/ChatScreen.js](src/screens/ChatScreen.js):
```js
const CEO_NAME = 'Your CEO Name';
```

### Add More CEO Replies

Add strings to the `CEO_REPLIES` array in [src/screens/ChatScreen.js](src/screens/ChatScreen.js).

### Change Color Scheme

Update the hex values in the `DarkTheme` object in [App.js](App.js) and in the `StyleSheet.create()` blocks across all screen files. The main accent color `#e94560` appears in every file.

### Add New Sidebar Items

Edit the `menuItems` array in [src/components/CustomDrawer.js](src/components/CustomDrawer.js):
```js
const menuItems = [
  { name: 'Projects', icon: 'folder-open', label: 'Projects' },
  { name: 'Chat', icon: 'chatbubbles', label: 'Chat with CEO' },
  { name: 'NewScreen', icon: 'icon-name', label: 'New Feature' },  // add here
];
```

Then register the new screen in [src/navigation/AppNavigator.js](src/navigation/AppNavigator.js).

---

## Scripts

| Command              | Description                          |
|----------------------|--------------------------------------|
| `npm start`          | Start the Expo development server    |
| `npm run android`    | Start and open on Android device/emulator |
| `npm run ios`        | Start and open on iOS simulator      |
| `npm run web`        | Start and open in web browser        |

---

## License

This project is private and not licensed for public distribution.
