import './api_client.js';
import './legacy-app.js';

// The legacy module owns the runtime App object for now. Importing it here
// gives the Game Console a module entrypoint while keeping existing inline
// template handlers stable through window.App.
