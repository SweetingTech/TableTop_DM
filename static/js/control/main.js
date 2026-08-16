import './api_client.js';
import './legacy-control.js';

// The Control Plane now has a module entrypoint. legacy-control.js still
// exposes window.control and the few inline handler facades used by the
// existing template.
