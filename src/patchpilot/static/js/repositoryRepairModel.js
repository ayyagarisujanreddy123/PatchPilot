/** Connected-repair UI guards. The server remains authoritative for identity and proof. */
export const REPOSITORY_ACTIVE_STATES = new Set(["QUEUED", "FETCHING", "BASELINE", "PLANNING", "STAGING", "PUBLISHING"]);
const states = new Set([...REPOSITORY_ACTIVE_STATES, "READY_TO_PUBLISH", "NO_CHANGE", "REJECTED", "PUBLISHED", "FAILED"]);

export function validateRepositoryUrl(value) {
    let url;
    try { url = new URL(String(value).trim()); } catch { throw new Error("Enter a GitHub repository URL, such as https://github.com/owner/repository."); }
    if (url.protocol !== "https:" || url.hostname !== "github.com" || url.port || url.username || url.password || url.search || url.hash
        || !/^\/[A-Za-z0-9_-]+\/[A-Za-z0-9_.-]+(?:\/tree\/[^/]+(?:\/[^/]+)*)?\/?$/.test(url.pathname)) {
        throw new Error("Use an HTTPS github.com repository URL or /tree/branch link, without credentials or query parameters.");
    }
    const path = url.pathname.split("/").slice(0, 3).join("/").replace(/\.git$/, "");
    if (!path.split("/")[2]) { throw new Error("Enter the complete GitHub repository URL."); }
    return `https://github.com${path}`;
}

export function validateRepositoryConnection(value) {
    if (!value?.connectionId || !value.assessmentId || !value.repository || !value.baseCommit || !value.manifest
        || !Array.isArray(value.capabilities) || !value.capabilities.includes("homepage")) {
        throw new Error("The backend returned an incomplete repository connection.");
    }
    return value;
}

export function validateRepositoryRepair(value) {
    if (!value?.repairId || !value.connectionId || !value.assessmentId || !states.has(value.state)
        || !Array.isArray(value.checks) || !Array.isArray(value.events) || !Array.isArray(value.capabilities) || !Array.isArray(value.limitations)) {
        throw new Error("The backend returned an incomplete repository repair report.");
    }
    return value;
}

export function hasPublishableProof(report) {
    return report?.state === "READY_TO_PUBLISH" && Boolean(report.patch?.unifiedDiff && report.proposal)
        && ["BASELINE", "CANDIDATE"].every((phase) => report.checks.some((check) => check.phase === phase))
        && report.checks.filter((check) => check.phase === "CANDIDATE").every((check) => check.passed === true);
}

export function safePullRequestUrl(report) {
    try {
        const url = new URL(report.pullRequest?.url);
        return url.protocol === "https:" && url.hostname === "github.com" && !url.username && !url.password && !url.port
            && url.pathname.toLowerCase() === `/${report.repository}/pull/${report.pullRequest.number}`.toLowerCase() && !url.search && !url.hash ? url.href : null;
    } catch { return null; }
}
