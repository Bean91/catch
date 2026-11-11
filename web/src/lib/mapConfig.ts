// The one place the map's tile provider is named. Swap these three constants (or point
// TILE_URL at a self-hosted/commercial tile server) for a public deployment: OpenStreetMap's
// tile usage policy is aimed at light personal use, not commercial-scale traffic — see
// docs/weather-endpoints.md ("Map tiles") and PLAN.md's session 20 blockers.
export const TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
export const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';
export const TILE_MAX_ZOOM = 19;
