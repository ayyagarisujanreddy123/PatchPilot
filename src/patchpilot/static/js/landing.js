/** Preserve dashboard links used before the landing page existed. */
function redirectLegacyDashboard() {
    const route = /^#\/(fleet|run|metrics|recipes|events)(?:\/|$)/;
    const mock = new URLSearchParams(window.location.search).get("mock") === "1";
    if (mock || route.test(window.location.hash)) {
        window.location.replace(`/dashboard${window.location.search}${window.location.hash || "#/fleet"}`);
    }
}

window.addEventListener("hashchange", redirectLegacyDashboard);
redirectLegacyDashboard();
