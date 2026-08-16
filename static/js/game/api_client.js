export async function apiFetch(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try {
            const body = await response.json();
            message = body.error || body.message || message;
        } catch (_) {
            // Response was not JSON; keep HTTP status text.
        }
        throw new Error(message);
    }
    return response.json();
}
