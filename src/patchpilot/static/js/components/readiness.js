/** Prerequisite feedback always supplies a useful next action. */
import { el } from "../util.js";
import { icon } from "../icons.js";

export function renderReadiness({ health, ui, busy }, handlers) {
    let title = "Checking your workspace", message = "Connecting to the controller and checking the demo prerequisites.";
    let tone = "neutral", symbol = "clock", action = null;
    if (["MOCK", "SIMULATION"].includes(health?.mode)) {
        title = "Simulated walkthrough"; tone = "warn";
        message = "Explore with sample data. No website is changed in this mode.";
    } else if (ui.preparing || ui.resetting || busy) {
        title = ui.preparing ? "Preparing your demo sites" : ui.resetting ? "Restoring the demo baseline" : "A repair is in progress";
        message = "You can follow the recorded progress. New changes are paused until this operation finishes.";
        tone = "progress";
    } else if (health?.ready && health?.prepared) {
        title = "Ready when you are"; symbol = "shield"; tone = "verified";
        message = "Your local workspace is connected. Start with an assessment; you approve any repair.";
    } else if (health) {
        tone = "warn"; symbol = "info";
        if (!health.dockerAvailable) {
            title = "Start Docker to continue";
            message = "The local Docker engine is needed to inspect and stage the registered PHP sites.";
        } else if (!health.plannerConfigured) {
            title = "Connect your AI planner";
            message = "Add your Anthropic key to the local .env, then refresh status. The key stays outside this page.";
        } else if (!health.prepared) {
            title = "Set up the local demo sites";
            message = "Prepare the four registered PHP sites. The first setup may take a few minutes.";
            action = el("button", { className: "btn btn--primary btn--small", attrs: { id: "prepare-fixtures", type: "button" } }, "Prepare demo sites");
            action.addEventListener("click", handlers.onPrepare);
        } else {
            title = "The workspace needs attention";
            message = health.message ?? "Review the controller before starting another operation.";
        }
        if (!action) {
            action = el("button", { className: "btn btn--secondary btn--small", attrs: { id: "refresh-readiness", type: "button" } }, "Refresh status");
            action.addEventListener("click", handlers.onRefreshState);
        }
    }
    return el("section", { className: `readiness readiness--${tone}`, attrs: { "aria-label": "Workspace readiness" } }, [
        icon(symbol), el("div", { className: "readiness__copy" }, [el("strong", {}, title), el("p", {}, message)]), action,
    ]);
}
