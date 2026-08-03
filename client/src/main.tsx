/**
 * ============================================================================
 * FILE: main.tsx
 * LOCATION: client/src/main.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    React application entry point that bootstraps the entire A2UI application.
 *
 * ROLE IN PROJECT:
 *    Initializes the React DOM tree after bounded storage boot, applies
 *    StrictMode, and wraps the root App component with ThemeProvider and
 *    QueryProvider before mounting to the #root element in index.html.
 *
 * KEY COMPONENTS:
 *    - createRoot: Creates React 18+ concurrent root for DOM mounting
 *    - StrictMode: Enables development-only checks for deprecated patterns
 *    - ThemeProvider: Manages light/dark theme with localStorage persistence
 *    - QueryProvider: Wraps app with React Query client for data fetching
 *    - startApplication: Awaits storage connect/hydrate before render
 *
 * DEPENDENCIES:
 *    - External: react, react-dom/client
 *    - Internal: ./App, ./providers/QueryProvider, ./providers/ThemeProvider,
 *      ./lib/startApplication, ./index.css
 *
 * USAGE:
 *    // Standard React 18+ bootstrap — executed automatically by Vite
 * ============================================================================
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { QueryProvider } from './providers/QueryProvider'
import { ThemeProvider } from './providers/ThemeProvider'
import { startApplication } from './lib/startApplication'

function renderApplication() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ThemeProvider defaultTheme="system" storageKey="agui-theme">
        <QueryProvider>
          <App />
        </QueryProvider>
      </ThemeProvider>
    </StrictMode>,
  )
}

void startApplication(renderApplication)
